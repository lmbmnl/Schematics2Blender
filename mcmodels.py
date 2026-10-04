"""Modelli dei blocchi di Minecraft (blockstates + models JSON) -> facce.

Nei modelli le coordinate sono pixel 0..16 con x est, y su, z sud. Le facce
escono in coordinate Blender della cella 0..1: x est, y nord (= -z), z su,
come il resto dell'addon. Niente bpy qui dentro.

Riferimenti: formato dei modelli e dei blockstates del Minecraft Wiki
(Tutorials/Models); UV di default e rotazioni come in BlockElement /
FaceBakery / BlockModelRotation di Minecraft.
"""

import math

import numpy as np

from .schem import parse_state

# lati di Blender: indice -> vettore
SIDES = ((-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1))
_MC_DIRS = {"down": (0, -1, 0), "up": (0, 1, 0), "north": (0, 0, -1),
            "south": (0, 0, 1), "west": (-1, 0, 0), "east": (1, 0, 0)}

INVISIBLE = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air", "minecraft:barrier",
             "minecraft:light", "minecraft:structure_void", "minecraft:moving_piston"}
FLUIDS = {"minecraft:water": "minecraft:block/water_still", "minecraft:lava": "minecraft:block/lava_still",
          "minecraft:bubble_column": "minecraft:block/water_still"}
# disegnati da Minecraft come entita' (il modello ha solo la texture "particle"):
# una scatola con quella texture; gli altri (cartelli, stendardi, teste...) si saltano
ENTITY_BOXES = {"chest": (1, 0, 1, 15, 14, 15), "trapped_chest": (1, 0, 1, 15, 14, 15),
                "ender_chest": (1, 0, 1, 15, 14, 15), "shulker_box": (0, 0, 0, 16, 16, 16),
                "bed": (0, 0, 0, 16, 9, 16), "decorated_pot": (1, 0, 1, 15, 16, 15)}
# valori usati quando lo stato non ha la proprieta' (es. blocchi convertiti dalla 1.12)
DEFAULTS = {"shape": "straight", "half": "bottom", "type": "bottom", "axis": "y",
            "facing": "north", "face": "wall", "powered": "false", "open": "false",
            "lit": "false", "snowy": "false", "waterlogged": "false", "attached": "false",
            "north": "none", "south": "none", "east": "none", "west": "none", "up": "true",
            "down": "false", "hinge": "left", "in_wall": "false", "age": "0", "level": "0"}


# blocchi rinominati tra una versione e l'altra, nei due sensi:
# lo schematic puo' essere piu' vecchio o piu' nuovo del client.jar
_RENAMES = (
    ("minecraft:grass", "minecraft:short_grass"),  # 1.20.3
    ("minecraft:grass_path", "minecraft:dirt_path"),  # 1.17
    ("minecraft:sign", "minecraft:oak_sign"),  # 1.14
    ("minecraft:wall_sign", "minecraft:oak_wall_sign"),  # 1.14
)
RENAMED = dict(_RENAMES + tuple((new, old) for old, new in _RENAMES))


def _mc_to_blender(p):
    """Pixel Minecraft (x, y, z) -> cella Blender 0..1."""
    p = np.asarray(p, float) / 16.0
    return np.stack((p[..., 0], 1.0 - p[..., 2], p[..., 1]), axis=-1)


def _dir_to_blender(vec):
    """Direzione Minecraft -> direzione Blender (x, -z, y)."""
    return np.array((vec[0], -vec[2], vec[1]), float)


def _rotation(axis, degrees):
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _variant_rotation(x, y):
    """Rotazione del blockstate: prima x poi y, in senso orario (Minecraft)."""
    return _rotation("y", -y) @ _rotation("x", -x)


def _nearest_dir(vec):
    best = max(_MC_DIRS, key=lambda d: np.dot(_MC_DIRS[d], vec))
    return best


def _face_points(d, f, t):
    """Angoli della faccia d dell'elemento f..t (pixel), in ordine
    alto-sinistra, alto-destra, basso-destra, basso-sinistra della texture."""
    x1, y1, z1 = f
    x2, y2, z2 = t

    def P(u, v):
        if d == "up":
            return (x1 + u * (x2 - x1), y2, z1 + v * (z2 - z1))
        if d == "down":
            return (x1 + u * (x2 - x1), y1, z2 - v * (z2 - z1))
        if d == "north":
            return (x2 - u * (x2 - x1), y2 - v * (y2 - y1), z1)
        if d == "south":
            return (x1 + u * (x2 - x1), y2 - v * (y2 - y1), z2)
        if d == "west":
            return (x1, y2 - v * (y2 - y1), z1 + u * (z2 - z1))
        return (x2, y2 - v * (y2 - y1), z2 - u * (z2 - z1))  # east
    return np.array([P(0, 0), P(1, 0), P(1, 1), P(0, 1)], float)


def _default_uv(d, f, t):
    x1, y1, z1 = f
    x2, y2, z2 = t
    return {"down": (x1, 16 - z2, x2, 16 - z1), "up": (x1, z1, x2, z2),
            "north": (16 - x2, 16 - y2, 16 - x1, 16 - y1), "south": (x1, 16 - y2, x2, 16 - y1),
            "west": (z1, 16 - y2, z2, 16 - y1), "east": (16 - z2, 16 - y2, 16 - z1, 16 - y1)}[d]


def _projected_uv(d, points):
    """UV di un punto come la proiezione di default della direzione d (per uvlock)."""
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    u, v = {"down": (x, 16 - z), "up": (x, z), "north": (16 - x, 16 - y), "south": (x, 16 - y),
            "west": (z, 16 - y), "east": (16 - z, 16 - y)}[d]
    return np.stack((u, v), axis=1)


class Face:
    __slots__ = ("corners", "uv", "layers", "cull")

    def __init__(self, corners, uv, layers, cull):
        self.corners = corners  # (k, 3) cella Blender 0..1, antiorario visto da fuori
        self.uv = uv            # (k, 2) UV Blender 0..1 (v in su)
        self.layers = layers    # ((texture, tintindex), ...): base + eventuali overlay
        self.cull = cull        # lato Blender (0..5) che la nasconde se coperto, o -1


class Baked:
    """Un blocco pronto: facce + cosa si e' dovuto approssimare."""

    def __init__(self, faces, note=None):
        self.faces = faces
        self.note = note  # None, "fluid", "entity", "invisible", "unknown"


class BlockModels:
    def __init__(self, assets):
        self.assets = assets
        self._models, self._baked = {}, {}

    # -- blockstate -> [(modello, x, y, uvlock)]
    def _prop(self, props, key):
        return props.get(key, DEFAULTS.get(key))

    def _when(self, cond, props):
        if "OR" in cond:
            return any(self._when(c, props) for c in cond["OR"])
        if "AND" in cond:
            return all(self._when(c, props) for c in cond["AND"])
        return all(str(self._prop(props, k)) in str(v).split("|") for k, v in cond.items())

    def variants(self, name, props):
        """Modelli da usare per lo stato, o None se il blocco non ha un blockstate."""
        state = self.assets.json("blockstates", name)
        if state is None and name in RENAMED:  # schematic di un'altra versione del jar
            state = self.assets.json("blockstates", RENAMED[name])
        if state is None:
            return None
        chosen = []
        if "variants" in state:
            best, best_score = None, None
            for key, value in state["variants"].items():
                conds = dict(p.split("=", 1) for p in key.split(",") if "=" in p)
                score = 0.0
                for k, v in conds.items():
                    if k in props:
                        if props[k] != v:
                            score = None
                            break
                        score += 1
                    elif DEFAULTS.get(k) == v:
                        score += 0.5  # proprieta' mancante: preferisci il valore di default
                if score is not None and (best_score is None or score > best_score):
                    best, best_score = value, score
            if best is not None:
                chosen.append(best)
        for part in state.get("multipart", ()):
            if "when" not in part or self._when(part["when"], props):
                chosen.append(part["apply"])
        out = []
        for c in chosen:
            c = c[0] if isinstance(c, list) else c  # varianti casuali: la prima
            out.append((c["model"], c.get("x", 0), c.get("y", 0), c.get("uvlock", False)))
        return out

    # -- modello con genitori risolti
    def model(self, location):
        if location in self._models:
            return self._models[location]
        textures, elements, chain, loc = {}, None, [], location
        while loc and len(chain) < 32:
            if loc.startswith("builtin/") or loc.startswith("minecraft:builtin/"):
                break
            data = self.assets.json("models", loc)
            if data is None:
                break
            chain.append(data)
            if elements is None and "elements" in data:
                elements = data["elements"]
            loc = data.get("parent")
        for data in reversed(chain):  # il figlio sovrascrive il genitore
            textures.update(data.get("textures", {}))
        self._models[location] = (textures, elements or [])
        return self._models[location]

    @staticmethod
    def texture_of(ref, textures):
        seen = 0
        while ref and ref.startswith("#") and seen < 16:
            ref = textures.get(ref[1:])
            seen += 1
        if not ref or ref.startswith("#"):
            return None
        return ref if ":" in ref else "minecraft:" + ref

    # -- facce
    def _element_faces(self, element, textures, rot, uvlock):
        f, t = np.array(element["from"], float), np.array(element["to"], float)
        er = element.get("rotation")
        out = []
        for d, spec in element.get("faces", {}).items():
            if d not in _MC_DIRS:
                continue
            pts = _face_points(d, f, t)
            u1, v1, u2, v2 = spec.get("uv") or _default_uv(d, f, t)
            uv = np.array([(u1, v1), (u2, v1), (u2, v2), (u1, v2)], float)
            k = int(spec.get("rotation", 0)) // 90 % 4
            if k:
                uv = np.roll(uv, k, axis=0)  # texture girata in senso orario
            if er:
                origin = np.array(er.get("origin", (8, 8, 8)), float)
                angle = float(er.get("angle", 0))
                m = _rotation(er["axis"], angle)
                pts = (pts - origin) @ m.T
                if er.get("rescale"):
                    scale = np.ones(3)
                    scale[[a for a, n in enumerate("xyz") if n != er["axis"]]] = 1 / math.cos(math.radians(angle))
                    pts = pts * scale
                pts = pts + origin
            direction = np.array(_MC_DIRS[d], float)
            if rot is not None:
                pts = (pts - 8) @ rot.T + 8
                direction = rot @ direction
            if uvlock and rot is not None:
                uv = _projected_uv(_nearest_dir(direction), pts)
            cull = spec.get("cullface")
            if cull in _MC_DIRS and rot is not None:
                cull = _nearest_dir(rot @ np.array(_MC_DIRS[cull], float))
            corners = _mc_to_blender(pts)
            normal = np.cross(corners[1] - corners[0], corners[2] - corners[0])
            if np.linalg.norm(normal) < 1e-9:
                normal = np.cross(corners[2] - corners[0], corners[3] - corners[0])
                if np.linalg.norm(normal) < 1e-9:
                    continue  # faccia degenere
            if np.dot(normal, _dir_to_blender(direction)) < 0:  # la normale deve uscire dalla faccia
                corners, uv = corners[::-1].copy(), uv[::-1].copy()
            uv_bl = np.stack((uv[:, 0] / 16.0, 1.0 - uv[:, 1] / 16.0), axis=1)
            side = (SIDES.index(tuple(int(v) for v in _dir_to_blender(_MC_DIRS[cull])))
                    if cull in _MC_DIRS else -1)
            tex = self.texture_of(spec.get("texture"), textures)
            out.append(Face(corners, uv_bl, ((tex, int(spec.get("tintindex", -1))),), side))
        return out

    def _box(self, texture, box, tint=-1):
        """Scatola con una texture; cullface solo sui lati che toccano il bordo."""
        x1, y1, z1, x2, y2, z2 = box
        touches = {"down": y1 == 0, "up": y2 == 16, "north": z1 == 0,
                   "south": z2 == 16, "west": x1 == 0, "east": x2 == 16}
        faces = {}
        for d in _MC_DIRS:
            faces[d] = {"texture": texture, "tintindex": tint}
            if touches[d]:
                faces[d]["cullface"] = d
        element = {"from": [x1, y1, z1], "to": [x2, y2, z2], "faces": faces}
        return self._element_faces(element, {}, None, False)

    def bake(self, state):
        """Stato ("minecraft:oak_stairs[facing=east]") -> Baked (in cache)."""
        if state in self._baked:
            return self._baked[state]
        name, props = parse_state(state)
        if name in INVISIBLE:
            baked = Baked([], "invisible")
        elif name in FLUIDS:
            baked = Baked(self._box(FLUIDS[name], (0, 0, 0, 16, 16, 16),
                                    0 if "water" in FLUIDS[name] else -1), "fluid")
        else:
            variants = self.variants(name, props)
            if variants is None:
                baked = Baked([], "unknown")
            else:
                faces, particle = [], None
                for model, x, y, uvlock in variants:
                    textures, elements = self.model(model)
                    particle = particle or self.texture_of(textures.get("particle"), textures)
                    rot = _variant_rotation(x, y) if (x or y) else None
                    for element in elements:
                        faces += self._element_faces(element, textures, rot, uvlock)
                note = None
                if not faces:
                    short = name.split(":", 1)[1]
                    box = next((b for key, b in ENTITY_BOXES.items()
                                if short == key or short.endswith("_" + key)), None)
                    if box and particle:
                        faces, note = self._box(particle, box), "entity"
                    else:
                        note = "entity" if particle else "unknown"
                baked = Baked(_merge_overlays(faces), note)
        self._baked[state] = baked
        return baked


def _normal(face):
    c = face.corners
    n = np.cross(c[1] - c[0], c[2] - c[0])
    if np.linalg.norm(n) < 1e-12:
        n = np.cross(c[2] - c[0], c[3] - c[0])
    return n / (np.linalg.norm(n) or 1.0)


def _merge_overlays(faces):
    """Facce coincidenti dello stesso blocco.

    Stessa direzione (il lato dell'erba + l'overlay colorato): una faccia sola
    con piu' strati. Direzioni opposte (elementi piatti visibili dai due lati,
    es. la cima dell'azalea): Minecraft scarta il retro, Blender no e le due
    facce sfarfallerebbero, quindi ognuna si sposta di 0,1 mm verso la sua normale.
    """
    out, index = [], {}
    for face in faces:
        n = _normal(face)
        shape = tuple(sorted(map(tuple, np.round(face.corners, 5).tolist())))
        key = (shape, tuple(np.round(n, 3)))
        if key in index:
            first = out[index[key]]
            first.layers = first.layers + face.layers
            if first.cull < 0:
                first.cull = face.cull
            continue
        index[key] = len(out)
        out.append(face)
    by_shape = {}
    for face in out:
        by_shape.setdefault(tuple(sorted(map(tuple, np.round(face.corners, 5).tolist()))), []).append(face)
    for group in by_shape.values():
        if len(group) > 1:
            for face in group:
                face.corners = face.corners + _normal(face) * 1e-4
    return out


def full_sides(baked):
    """{lato: [indici delle facce che coprono per intero quel lato della cella]}."""
    sides = {}
    for i, face in enumerate(baked.faces):
        c = face.corners
        for s, vec in enumerate(SIDES):
            axis = [a for a in range(3) if vec[a]][0]
            edge = 1.0 if vec[axis] > 0 else 0.0
            if np.all(np.abs(c[:, axis] - edge) < 1e-6):
                others = [a for a in range(3) if a != axis]
                lo, hi = c[:, others].min(0), c[:, others].max(0)
                if len(c) == 4 and np.all(np.abs(lo) < 1e-6) and np.all(np.abs(hi - 1) < 1e-6):
                    sides.setdefault(s, []).append(i)
    return sides
