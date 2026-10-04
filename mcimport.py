"""Import con i modelli di Minecraft letti dal client.jar (o da un resource pack).

Ogni stato della palette diventa una mesh cotta da mcmodels; le texture sono
estratte dal jar e impacchettate nel .blend. Join: una mesh sola, le facce con
cullface spariscono se il vicino le copre (come in Minecraft). Instance: un
oggetto per blocco, i blocchi uguali condividono la mesh.
"""

import os
import tempfile

import bpy
import numpy as np

from . import fastjoin
from .mcmodels import SIDES, BlockModels, full_sides
from .schem import parse_state

# colori di default (bioma pianure) delle facce con tintindex
GRASS, FOLIAGE, WATER = 0x91BD59, 0x77AB2F, 0x3F76E4
_TINT_BY_NAME = {
    "birch_leaves": 0x80A755, "spruce_leaves": 0x619961, "lily_pad": 0x208030,
    "water": WATER, "bubble_column": WATER, "water_cauldron": WATER,
    "attached_melon_stem": 0xE0C71C, "attached_pumpkin_stem": 0xE0C71C, "vine": FOLIAGE,
}


def _linear(c):
    """sRGB 0..1 -> lineare: i colori dei socket di Blender sono lineari."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _rgb(hex_color):
    return tuple(((hex_color >> s) & 255) / 255.0 for s in (16, 8, 0))


def tint_color(state, tintindex):
    """Colore (r, g, b) 0..1 di una faccia con tintindex, come in Minecraft."""
    if tintindex < 0:
        return None
    name, props = parse_state(state)
    short = name.split(":", 1)[1]
    if short == "redstone_wire":  # colore dalla potenza, formula di RedStoneWireBlock
        f = int(props.get("power", "0")) / 15.0
        return (f * 0.6 + (0.4 if f > 0 else 0.3), max(0.0, f * f * 0.7 - 0.5), max(0.0, f * f * 0.6 - 0.7))
    if short in ("melon_stem", "pumpkin_stem"):  # colore dall'eta', come StemBlock
        age = int(props.get("age", "0"))
        return (age * 32 / 255.0, (255 - age * 8) / 255.0, age * 4 / 255.0)
    if short in _TINT_BY_NAME:
        return _rgb(_TINT_BY_NAME[short])
    if short.endswith("_leaves"):
        return _rgb(FOLIAGE)
    return _rgb(GRASS)  # erba, felci, canne da zucchero, ...


class Textures:
    """Texture del jar -> immagini Blender impacchettate nel .blend."""

    def __init__(self, assets):
        self.assets = assets
        self._cache = {}
        # immagini di un import precedente dalla stessa sorgente (nome senza .001)
        self._existing = {}
        for image in bpy.data.images:
            if image.get("mc_source") == assets.source:
                self._existing.setdefault(image.name.rsplit(".", 1)[0] if image.name[-4:-3] == "." and
                                          image.name[-3:].isdigit() else image.name, image)

    def get(self, location):
        """(immagine o None, fotogrammi, "opaque" / "cutout" / "blend")."""
        if location in self._cache:
            return self._cache[location]
        result = (None, 1, "opaque")
        raw = self.assets.texture(location)[0] if location else None
        if raw is not None:
            name = "mc " + location.split(":", 1)[-1]
            image = self._existing.get(name)
            if image is None:
                fd, path = tempfile.mkstemp(suffix=".png")
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(raw)
                    image = bpy.data.images.load(path)
                    image.pack()
                finally:
                    os.remove(path)
                image.name = name
                image["mc_source"] = self.assets.source
                self._existing[name] = image
            w, h = image.size
            frames = h // w if w and h > w and h % w == 0 else 1  # animata: una striscia
            alpha = np.empty(w * h * 4, np.float32)
            image.pixels.foreach_get(alpha)
            alpha = alpha[3::4].reshape(h, w)[h - (h // frames):]  # primo fotogramma, in alto
            if alpha.min() > 0.999:
                kind = "opaque"
            elif np.all((alpha < 0.01) | (alpha > 0.99)):
                kind = "cutout"
            else:
                kind = "blend"
            result = (image, frames, kind)
        self._cache[location] = result
        return result


def _socket(sockets, identifier):
    return next(s for s in sockets if s.identifier == identifier)


class Materials:
    """Un materiale per combinazione di strati ((texture, tinta), ...)."""

    def __init__(self, textures):
        self.textures = textures
        self.list, self._index = [], {}
        # materiali di un import precedente con gli stessi strati e la stessa sorgente
        self._existing = {m["mc_key"]: m for m in bpy.data.materials if isinstance(m.get("mc_key"), str)}

    def index(self, layers):
        if layers not in self._index:
            key = "%s %r" % (self.textures.assets.source, layers)
            mat = self._existing.get(key)
            if mat is None:
                mat = self._make(layers)
                mat["mc_key"] = key
            self._index[layers] = len(self.list)
            self.list.append(mat)
        return self._index[layers]

    def _make(self, layers):
        name = "mc " + " + ".join((loc or "missing").split("/")[-1] for loc, _tint in layers)
        if any(tint for _loc, tint in layers):
            name += " (tinted)"
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree
        for node in list(nt.nodes):
            nt.nodes.remove(node)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        out.location = (500, 0)
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (200, 0)
        bsdf.inputs["Roughness"].default_value = 1.0
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        color, y = None, 300
        for depth, (loc, tint) in enumerate(layers):
            image, _frames, kind = self.textures.get(loc)
            if image is None:
                if color is None:
                    bsdf.inputs["Base Color"].default_value = (1, 0, 1, 1)
                continue
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image, tex.interpolation = image, "Closest"
            tex.location = (-700, y)
            y -= 300
            layer_color = tex.outputs["Color"]
            if tint:
                mul = nt.nodes.new("ShaderNodeMix")
                mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
                mul.location = (-400, y + 300)
                _socket(mul.inputs, "Factor_Float").default_value = 1.0
                nt.links.new(layer_color, _socket(mul.inputs, "A_Color"))
                _socket(mul.inputs, "B_Color").default_value = (*map(_linear, tint), 1.0)
                layer_color = _socket(mul.outputs, "Result_Color")
            if color is None:
                color = layer_color
                if kind != "opaque":
                    nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
            else:  # overlay sopra lo strato precedente, mescolato con il suo alpha
                mix = nt.nodes.new("ShaderNodeMix")
                mix.data_type = "RGBA"
                mix.location = (-150, y + 300)
                nt.links.new(tex.outputs["Alpha"], _socket(mix.inputs, "Factor_Float"))
                nt.links.new(color, _socket(mix.inputs, "A_Color"))
                nt.links.new(layer_color, _socket(mix.inputs, "B_Color"))
                color = _socket(mix.outputs, "Result_Color")
        if color is not None:
            nt.links.new(color, bsdf.inputs["Base Color"])
        return mat


class Template:
    """Uno stato pronto per la mesh: facce, materiali e cosa copre dei vicini."""

    def __init__(self, state, models, materials):
        baked = models.bake(state)
        self.state, self.note = state, baked.note
        self.name = parse_state(state)[0]
        self.corners, self.uvs, self.mats, self.cull, self.opaque = [], [], [], [], []
        self.occludes, self.full = set(), set()
        faces = baked.faces
        if baked.note == "unknown":  # nessun blockstate (blocco di una mod, id sconosciuto): cubo magenta
            faces = models._box(None, (0, 0, 0, 16, 16, 16))
        sides = full_sides(type(baked)(faces))
        for i, face in enumerate(faces):
            layers = tuple((loc, tint_color(state, tint)) for loc, tint in face.layers)
            image, frames, kind = materials.textures.get(layers[0][0])
            uv = face.uv.copy()
            if frames > 1:  # texture animata: solo il primo fotogramma
                uv[:, 1] = 1.0 - (1.0 - uv[:, 1]) / frames
            self.corners.append(face.corners)
            self.uvs.append(uv)
            self.mats.append(materials.index(layers))
            self.cull.append(face.cull)
            self.opaque.append(kind == "opaque")
            for side, faces in sides.items():
                if i in faces:
                    self.full.add(side)
                    if kind == "opaque":
                        self.occludes.add(side)


# --- connessioni di staccionate, muretti e vetri (i .schematic 1.12 non le salvano).
# Regole di FenceBlock / WallBlock / IronBarsBlock: si attaccano a un lato pieno
# del vicino (non foglie, zucche, meloni, barriere, shulker), ai blocchi della
# stessa famiglia e ai cancelletti messi di traverso; muretti e vetri anche tra loro.
_NEVER = ("_leaves", "barrier", "pumpkin", "jack_o_lantern", "melon", "shulker_box")
_DIRS = {"east": ((1, 0, 0), 1), "west": ((-1, 0, 0), 0),  # direzione in Blender, lato di SIDES
         "north": ((0, 1, 0), 3), "south": ((0, -1, 0), 2)}


def _family(name):
    """"fence" (legno), "nether_fence", "wall", "pane" (vetri e sbarre), "gate" o None."""
    short = name.split(":", 1)[1]
    if short.endswith("_fence_gate"):
        return "gate"
    if short == "nether_brick_fence":
        return "nether_fence"
    if short.endswith("_fence"):
        return "fence"
    if short.endswith("_wall") and not short.endswith(("_wall_sign", "_wall_banner", "_wall_head",
                                                       "_wall_skull", "_wall_torch", "_wall_fan",
                                                       "_wall_hanging_sign")):
        return "wall"
    if short.endswith("_pane") or short == "iron_bars":
        return "pane"
    return None


def _attaches(fam, side, other_state, other_full):
    """Il blocco di famiglia fam si attacca al vicino sul lato side?"""
    name, props = parse_state(other_state)
    other = _family(name)
    if other == "gate":  # solo se il cancelletto e' di traverso
        axis = "x" if props.get("facing") in ("east", "west") else "z"
        return fam != "pane" and axis == ("z" if side in ("east", "west") else "x")
    if other == fam or {fam, other} == {"wall", "pane"}:
        return True
    if name.split(":", 1)[1].endswith(_NEVER):
        return False
    return _DIRS[side][1] ^ 1 in other_full  # il lato del vicino che ci guarda e' pieno


def connect_states(cells_by_state, states, full, assets):
    """Aggiunge north/east/south/west (e up per i muretti) agli stati delle
    staccionate, dei muretti e dei vetri, guardando i blocchi accanto.
    cells_by_state = {indice: celle (n, 3)}, full = {indice: lati pieni};
    torna {indice: [(cella, nuovo stato)]}."""
    where = {}
    for idx, cells in cells_by_state.items():
        for cell in map(tuple, cells.tolist()):
            where[cell] = idx
    out = {}
    for idx, cells in cells_by_state.items():
        name, props = parse_state(states[idx])
        fam = _family(name)
        if fam in (None, "gate"):
            continue
        data = assets.json("blockstates", name) or {}
        tall = fam == "wall" and "low" in str(data)  # muretti 1.16+: none / low / tall
        for cell in map(tuple, cells.tolist()):
            new = dict(props)
            linked = {}
            for side, ((dx, dy, dz), _s) in _DIRS.items():
                other = where.get((cell[0] + dx, cell[1] + dy, cell[2] + dz))
                ok = other is not None and _attaches(fam, side, states[other], full.get(other, ()))
                linked[side] = ok
                new[side] = ("low" if ok else "none") if tall else ("true" if ok else "false")
            if fam == "wall":  # niente palo solo in mezzo a un tratto dritto
                straight = (linked["north"] and linked["south"] and not linked["east"] and not linked["west"]) or \
                           (linked["east"] and linked["west"] and not linked["north"] and not linked["south"])
                new["up"] = "false" if straight else "true"
            state = name + "[" + ",".join("%s=%s" % kv for kv in sorted(new.items())) + "]"
            out.setdefault(idx, []).append((cell, state))
    return out


def build_join(name, cells_by_template, templates, materials):
    """Mesh unica. Una faccia con cullface sparisce se il vicino ha, sul lato che
    la tocca, una faccia piena opaca, o e' lo stesso blocco con una faccia piena
    (vetro accanto a vetro, acqua accanto ad acqua)."""
    occluders = {s: [] for s in range(6)}
    same = {}
    for key, cells in cells_by_template.items():
        t = templates[key]
        for s in t.occludes:
            occluders[s].append(cells)
        for s in t.full:
            same.setdefault((t.name, s), []).append(cells)

    def keyset(chunks):
        return np.sort(fastjoin.cell_keys(np.concatenate(chunks))) if chunks else np.zeros(0, np.int64)
    occluders = {s: keyset(c) for s, c in occluders.items()}
    same = {k: keyset(c) for k, c in same.items()}

    def inside(keys, cells):
        if not len(keys):
            return np.zeros(len(cells), bool)
        k = fastjoin.cell_keys(cells)
        i = np.minimum(np.searchsorted(keys, k), len(keys) - 1)
        return keys[i] == k

    corners, uvs, sizes, mats, opaque = [], [], [], [], []
    for key, cells in cells_by_template.items():
        t = templates[key]
        if not t.corners or not len(cells):
            continue
        hidden = {}
        for s in set(c for c in t.cull if c >= 0):
            neighbours = cells + np.array(SIDES[s])
            opposite = s ^ 1  # lati in coppie: -X/+X, -Y/+Y, -Z/+Z
            hidden[s] = inside(occluders[opposite], neighbours) | \
                inside(same.get((t.name, opposite), np.zeros(0, np.int64)), neighbours)
        for face, uv, mat, cull, solid in zip(t.corners, t.uvs, t.mats, t.cull, t.opaque):
            keep = cells if cull < 0 else cells[~hidden[cull]]
            if not len(keep):
                continue
            k = len(face)
            corners.append((keep[:, None, :] + face[None, :, :]).reshape(-1, 3))
            uvs.append(np.tile(uv, (len(keep), 1)))
            sizes.append(np.full(len(keep), k, np.int64))
            mats.append(np.full(len(keep), mat, np.int64))
            opaque.append(np.full(len(keep), solid, bool))
    mesh = bpy.data.meshes.new(name)
    if corners:
        sizes = np.concatenate(sizes)
        corners, keep = _split_coincident(np.concatenate(corners), sizes, np.concatenate(opaque))
        sizes, uvs, mats = sizes[keep], np.concatenate(uvs)[np.repeat(keep, sizes)], [np.concatenate(mats)[keep]]
        used = sorted(set(np.concatenate(mats).tolist()))
        remap = np.zeros(max(used) + 1, np.int64)
        remap[used] = np.arange(len(used))
        fastjoin.fill_mesh(mesh, corners, sizes, uvs, remap[mats[0]], [materials.list[m] for m in used])
    return mesh


_GAP = 1e-4  # distacco delle facce coincidenti che restano (come mcmodels._merge_overlays)


def _split_coincident(corners, sizes, opaque):
    """Facce di blocchi vicini sugli stessi vertici (il lato di una scala contro
    quello di un'altra, foglie contro acqua): Blender non le accetta.
    Una coppia di facce opache una contro l'altra non si vede: via tutte e due.
    Le altre si staccano di _GAP, ognuna verso l'interno del suo blocco.
    Torna (angoli delle facce tenute, maschera delle facce tenute)."""
    keep = np.ones(len(sizes), bool)
    if not len(sizes) or np.any(sizes != 4):  # i modelli di Minecraft hanno solo quadrilateri
        return corners, keep
    quads = corners.reshape(-1, 4, 3)
    _, vert, _ = fastjoin.unique_rows(np.round(corners / fastjoin._EPS).astype(np.int64))
    _, group, counts = fastjoin.unique_rows(np.sort(vert.reshape(-1, 4), axis=1))
    shared = np.flatnonzero(counts[group] > 1)
    if not len(shared):
        return corners, keep
    normal = np.cross(quads[:, 1] - quads[:, 0], quads[:, 2] - quads[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1), 1e-12)[:, None]
    quads = quads.copy()
    by_group = {}
    for f in shared.tolist():
        by_group.setdefault(int(group[f]), []).append(f)
    for faces in by_group.values():
        if len(faces) == 2 and all(opaque[faces]) and np.dot(normal[faces[0]], normal[faces[1]]) < -0.99:
            keep[faces] = False
            continue
        for rank, f in enumerate(faces):
            quads[f] -= normal[f] * _GAP * (rank + 1)
    return quads[keep].reshape(-1, 3), keep


def template_mesh(t, materials):
    """La mesh di un solo blocco (Instance): tutte le facce, coordinate 0..1."""
    mesh = bpy.data.meshes.new("mc " + t.state.split(":", 1)[-1])
    if not t.corners:
        return mesh
    used = sorted(set(t.mats))
    remap = {m: i for i, m in enumerate(used)}
    fastjoin.fill_mesh(mesh, np.concatenate(t.corners), np.array([len(c) for c in t.corners]),
                       np.concatenate(t.uvs), [remap[m] for m in t.mats], [materials.list[m] for m in used])
    return mesh


class Job:
    """Un import con i modelli: palette di stati + indice di palette per blocco."""

    def __init__(self, assets, palette, indices, width, length, legacy=False):
        self.assets, self.models = assets, BlockModels(assets)
        self.materials = Materials(Textures(assets))
        self.palette, self.width, self.length, self.legacy = list(palette), width, length, legacy
        idx = fastjoin.int_array(indices)
        filled = np.flatnonzero(np.array([parse_state(s)[0] not in _AIR for s in self.palette])[idx]) \
            if len(idx) else np.zeros(0, np.int64)
        cells = fastjoin.cells(filled, width, length)
        order = np.argsort(idx[filled], kind="stable")
        keys, starts = np.unique(idx[filled][order], return_index=True)
        ends = list(starts[1:]) + [len(order)]
        self.cells = {int(k): cells[order[a:b]] for k, a, b in zip(keys, starts, ends)}
        self.templates = {}
        self.count = int(len(filled))

    def steps(self):
        """Quante unita' di lavoro prima di costruire (per la barra di avanzamento)."""
        return len(self.cells) + (1 if self.legacy else 0)

    def run(self):
        """Generatore: un template per passo, poi (1.12) le connessioni."""
        for key in list(self.cells):
            self.templates[key] = Template(self.palette[key], self.models, self.materials)
            yield
        if self.legacy:
            full = {k: t.full for k, t in self.templates.items()}
            moves = connect_states(self.cells, self.palette, full, self.assets)
            # connect_states rida' tutte le celle di ogni gruppo: prima si svuotano i
            # gruppi, poi si riempiono quelli di arrivo (che possono essere gli stessi:
            # una staccionata isolata resta nello stato che aveva)
            position = {state: i for i, state in enumerate(self.palette)}
            arriving = {}
            for idx, moved in moves.items():
                self.cells[idx] = np.zeros((0, 3), np.int64)
                for cell, state in moved:
                    if state not in position:
                        position[state] = len(self.palette)
                        self.palette.append(state)
                    arriving.setdefault(position[state], []).append(cell)
            for new, cells in arriving.items():
                old = self.cells.get(new, np.zeros((0, 3), np.int64))
                self.cells[new] = np.vstack((old, np.array(cells, np.int64).reshape(-1, 3)))
            for key in self.cells:
                if key not in self.templates:
                    self.templates[key] = Template(self.palette[key], self.models, self.materials)
            yield

    def report(self):
        """{nota: {nome: blocchi}} per i blocchi approssimati o saltati."""
        out = {}
        for key, cells in self.cells.items():
            t = self.templates.get(key)
            if t is not None and t.note in ("entity", "unknown", "fluid") and len(cells):
                if t.note == "entity" and t.corners:
                    note = "entity_box"
                else:
                    note = t.note
                name = t.name.split(":", 1)[-1]
                out.setdefault(note, {})[name] = out.get(note, {}).get(name, 0) + len(cells)
        return out


_AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
