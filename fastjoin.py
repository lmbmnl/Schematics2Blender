"""Modalita' Join veloce: una mesh sola costruita direttamente.

Prima ogni blocco diventava un oggetto, poi bpy.ops.object.join li univa
(8000 blocchi: oltre un minuto) e la mesh teneva anche le facce interne.

Ora per ogni combinazione (id, metadata) si crea UN esemplare con le classi
dei blocchi (stessa geometria, UV e materiali di sempre), se ne copia la
mesh e lo si elimina; poi la mesh finale si assembla con numpy, saltando le
facce coperte da un blocco pieno e opaco accanto.
"""

import bpy
import numpy as np

_EPS = 1e-5       # saldatura: i vertici dei vetri vicini distano 1e-4 e restano distinti
# Una faccia conta come lato intero entro 6e-5: i blocchi trasparenti dell'addon
# sono scalati 0.9999 (facce 5e-5 dentro il bordo) e vanno nascosti da un vicino
# opaco come in Minecraft; la cima del cactus, 1e-4 sotto il bordo, no.
_SIDE_EPS = 6e-5
_OFF, _B = 1 << 20, 1 << 21  # chiavi int64 delle celle (coordinate entro +-1M)
_DIRS = {(0, -1): (-1, 0, 0), (0, 1): (1, 0, 0), (1, -1): (0, -1, 0),
         (1, 1): (0, 1, 0), (2, -1): (0, 0, -1), (2, 1): (0, 0, 1)}


def int_array(values):
    """Blocks / Data del file (bytearray, Tag NBT o lista) -> array int64."""
    values = getattr(values, "value", values)
    if isinstance(values, (bytes, bytearray)):
        return np.frombuffer(bytes(values), np.uint8).astype(np.int64)
    return np.asarray(values, np.int64)


def cells(index, width, length):
    """Indici del file -> celle (x, y, z) di Blender, come SCHEMATIC_OT_run._place."""
    x = index % width - width // 2
    y = length - (index % (width * length)) // width - (length + 1) // 2 - 1
    z = index // (width * length)
    return np.stack((x, y, z), axis=1)


def cell_keys(cells):
    c = np.asarray(cells, np.int64).reshape(-1, 3) + _OFF
    return (c[:, 0] * _B + c[:, 1]) * _B + c[:, 2]


class Template:
    """La mesh di un blocco, con i vertici relativi al centro della sua cella."""

    def __init__(self, faces, uvs, face_mats, materials, sides, occludes):
        self.faces = faces          # [array (k, 3)] angoli di ogni faccia
        self.uvs = uvs              # [array (k, 2)]
        self.face_mats = face_mats  # [indice in materials]
        self.materials = materials  # [bpy.types.Material]
        self.sides = sides          # [(asse, segno) o None]: faccia che copre un lato intero
        self.occludes = occludes    # lati pieni e non trasparenti: nascondono la faccia del vicino


def _full_side(corners):
    """(asse, segno) se la faccia copre per intero un lato del cubo unitario."""
    for axis in range(3):
        for sign in (-1, 1):
            if np.all(np.abs(corners[:, axis] - sign * 0.5) < _SIDE_EPS):
                others = [a for a in range(3) if a != axis]
                lo, hi = corners[:, others].min(0), corners[:, others].max(0)
                if np.all(np.abs(lo + 0.5) < _SIDE_EPS) and np.all(np.abs(hi - 0.5) < _SIDE_EPS) \
                        and len(corners) == 4:
                    return axis, sign
    return None


def _has_transparency(materials):
    for mat in materials:
        if mat is not None and mat.node_tree is not None:
            if any(node.type == "BSDF_TRANSPARENT" for node in mat.node_tree.nodes):
                return True
    return False


def separate_reason(obj):
    """Perche' un esemplare non si puo' fondere nella mesh unica (None = si puo')."""
    if obj.type != "MESH":
        return "non e' una mesh"
    if obj.modifiers or obj.particle_systems or obj.constraints or obj.animation_data:
        return "ha modificatori, particelle o animazioni sull'oggetto"
    return None


def make_template(obj, center):
    """Copia la mesh dell'oggetto (posizione, rotazione e scala applicate)."""
    me = obj.data
    matrix = obj.matrix_basis  # oggetto appena creato, senza genitore
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    co = co @ np.array(matrix.to_3x3()).T + np.array(matrix.translation) - np.asarray(center)
    loop_vert = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", loop_vert)
    uv = np.zeros((len(me.loops), 2))
    if me.uv_layers:
        flat = np.empty(len(me.loops) * 2)
        me.uv_layers[0].data.foreach_get("uv", flat)
        uv = flat.reshape(-1, 2)
    materials = list(me.materials)
    faces, uvs, face_mats, sides = [], [], [], []
    for poly in me.polygons:
        loops = range(poly.loop_start, poly.loop_start + poly.loop_total)
        corners = co[loop_vert[loops]]
        faces.append(corners)
        uvs.append(uv[loops])
        face_mats.append(poly.material_index if materials else -1)
        sides.append(_full_side(corners))
    occludes = set() if _has_transparency(materials) else {side for side in sides if side}
    return Template(faces, uvs, face_mats, materials, sides, occludes)


def build_mesh(name, instances, templates):
    """instances = {chiave: array (n, 3) di celle intere}, templates = {chiave: Template}.

    Una faccia che copre un lato intero viene saltata se il blocco accanto ha,
    sul lato che la tocca, una faccia piena e non trasparente: le due facce
    coincidono e quella del vicino la copre. Vertici coincidenti saldati.
    """
    occluders = {}  # lato (asse, segno) -> chiavi ordinate delle celle che lo coprono
    for side in _DIRS:
        cells = [instances[k] for k, t in templates.items() if side in t.occludes and len(instances[k])]
        occluders[side] = np.sort(cell_keys(np.concatenate(cells))) if cells else np.zeros(0, np.int64)

    def covered(cells, side):
        axis, sign = side
        keys = occluders[(axis, -sign)]  # il vicino tocca questa faccia col lato opposto
        if not len(keys):
            return np.zeros(len(cells), bool)
        k = cell_keys(cells + _DIRS[side])
        idx = np.minimum(np.searchsorted(keys, k), len(keys) - 1)
        return keys[idx] == k

    material_slot, materials = {}, []
    corners, uvs, sizes, mats, solid = [], [], [], [], []
    for key, t in templates.items():
        cells = np.asarray(instances[key], np.int64).reshape(-1, 3)
        if not len(cells):
            continue
        centers = cells + 0.5
        hidden = {side: covered(cells, side) for side in set(t.sides) if side}
        clear = _has_transparency(t.materials)
        for face, uv, mat, side in zip(t.faces, t.uvs, t.face_mats, t.sides):
            keep = centers if side is None else centers[~hidden[side]]
            if not len(keep):
                continue
            k = len(face)
            corners.append((keep[:, None, :] + face[None, :, :]).reshape(-1, 3))
            uvs.append(np.tile(uv, (len(keep), 1)))
            sizes.append(np.full(len(keep), k, np.int64))
            solid.append(np.full(len(keep), not clear))
            if mat >= 0:
                m = t.materials[mat]
                if m.as_pointer() not in material_slot:
                    material_slot[m.as_pointer()] = len(materials)
                    materials.append(m)
                mats.append(np.full(len(keep), material_slot[m.as_pointer()], np.int64))
            else:
                mats.append(np.zeros(len(keep), np.int64))

    mesh = bpy.data.meshes.new(name)
    if not corners:
        return mesh
    corners, uvs = np.concatenate(corners), np.concatenate(uvs)
    sizes, mats, solid = np.concatenate(sizes), np.concatenate(mats), np.concatenate(solid)
    quant = np.round(corners / _EPS).astype(np.int64)

    # facce di blocchi diversi che coincidono (es. i gradini di due scale
    # impilate): se una delle due non e' trasparente si coprono a vicenda
    starts = np.concatenate(([0], np.cumsum(sizes)[:-1]))
    groups = {}
    for f, (a, k) in enumerate(zip(starts.tolist(), sizes.tolist())):
        key = tuple(sorted(map(tuple, quant[a:a + k].tolist())))
        groups.setdefault(key, []).append(f)
    drop = np.zeros(len(sizes), bool)
    for faces in groups.values():
        if len(faces) > 1:
            for f in faces:
                drop[f] = any(solid[g] for g in faces if g != f)
    if drop.any():
        keep_loop = np.repeat(~drop, sizes)
        corners, uvs, quant = corners[keep_loop], uvs[keep_loop], quant[keep_loop]
        sizes, mats = sizes[~drop], mats[~drop]
    if not len(sizes):
        return mesh
    return fill_mesh(mesh, corners, sizes, uvs, mats, materials)


_MIX = np.array([0x9E3779B97F4A7C15, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9,
                 0xD6E8FEB86659FD93, 0xFF51AFD7ED558CCD], np.uint64)


def unique_rows(rows):
    """Come np.unique(rows, axis=0, return_index=True, return_inverse=True,
    return_counts=True) ma molto piu' veloce sui milioni di righe: ogni riga di
    interi diventa un hash a 64 bit. Se due righe diverse avessero lo stesso
    hash (praticamente impossibile) si usa np.unique per righe: sempre esatto."""
    rows = np.ascontiguousarray(rows, np.int64)
    if rows.ndim == 1:
        rows = rows[:, None]
    h = np.zeros(len(rows), np.uint64)
    with np.errstate(over="ignore"):
        for j in range(rows.shape[1]):
            h = (h ^ rows[:, j].astype(np.uint64)) * _MIX[j % len(_MIX)]
            h ^= h >> np.uint64(31)
    _, first, inverse, counts = np.unique(h, return_index=True, return_inverse=True, return_counts=True)
    inverse = inverse.ravel()
    if not np.array_equal(rows[first][inverse], rows):
        _, first, inverse, counts = np.unique(rows, axis=0, return_index=True,
                                              return_inverse=True, return_counts=True)
        inverse = inverse.ravel()
    return first, inverse, counts


def fill_mesh(mesh, corners, sizes, uvs, mats, materials):
    """Riempie mesh: angoli (n, 3) faccia dopo faccia, sizes = angoli di ogni
    faccia, uvs (n, 2), mats = indice del materiale di ogni faccia.
    I vertici coincidenti vengono saldati."""
    quant = np.round(corners / _EPS).astype(np.int64)
    first, inverse, _counts = unique_rows(quant)
    verts = corners[first]
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", verts.ravel())
    mesh.loops.add(len(corners))
    mesh.loops.foreach_set("vertex_index", inverse.ravel().astype(np.int32))
    mesh.polygons.add(len(sizes))
    starts = np.concatenate(([0], np.cumsum(sizes)[:-1])).astype(np.int32)
    mesh.polygons.foreach_set("loop_start", starts)
    mesh.update(calc_edges=True)
    layer = mesh.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", np.asarray(uvs, float).ravel())
    for m in materials:
        mesh.materials.append(m)
    mesh.polygons.foreach_set("material_index", np.asarray(mats).astype(np.int32))
    mesh.update()
    return mesh
