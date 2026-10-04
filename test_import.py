# Run: blender -b --factory-startup --python test_import.py
# Import reale di .schematic e .schem con l'operatore dell'addon.
import gzip
import importlib.util
import os
import sys
import tempfile

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "schematics2blender", os.path.join(HERE, "__init__.py"), submodule_search_locations=[HERE])
addon = importlib.util.module_from_spec(spec)
sys.modules["schematics2blender"] = addon
spec.loader.exec_module(addon)
sys.path.insert(0, HERE)
import test_schem as ts  # noqa: E402  (scrittore NBT dei test)

TMP = tempfile.mkdtemp()


def write(name, data):
    path = os.path.join(TMP, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def legacy(blocks, data, w, h, l):
    body = (ts._short("Width", w) + ts._short("Height", h) + ts._short("Length", l)
            + ts._bytes("Blocks", blocks) + ts._bytes("Data", data))
    return gzip.compress(ts._compound("Schematic", body))


def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)


def new_objects(run):
    before = set(bpy.data.objects)
    assert run() == {"FINISHED"}
    return [ob for ob in bpy.data.objects if ob not in before]


addon.register()
scene = bpy.context.scene

# --- .schem (v3): posizioni, id legacy, blocchi senza modello
states = ["minecraft:air", "minecraft:stone", "minecraft:oak_log[axis=x]",
          "minecraft:copper_block", "minecraft:oak_stairs[facing=south,half=bottom,shape=straight]"]
w, h, l = 3, 2, 2
indices = [1, 2, 0, 3, 4, 1,
           0, 0, 1, 3, 3, 2]
path = write("test.schem", ts.sponge(states, indices, w, h, l, version=3))
clear()
objs = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=path, mode="INSTANCE"))
assert len(objs) == 9, len(objs)  # 12 celle, 3 d'aria
by_id = {}
for ob in objs:
    by_id.setdefault(ob.blockId, []).append(ob)
assert len(by_id[1]) == 3 and len(by_id[17]) == 2 and len(by_id[53]) == 1 and len(by_id[0]) == 3
copper = [ob for ob in by_id[0] if ob.data.materials[0].name == "Unknown copper_block"]
assert len(copper) == 3, [ob.data.materials[0].name for ob in by_id[0]]
assert tuple(copper[0].data.materials[0].node_tree.nodes["Diffuse BSDF"].inputs[0].default_value) == (1, 0, 1, 1)
# stesse coordinate del .schematic: x - floor(w/2), y dalla z del file capovolta, z = y del file
stone = sorted(tuple(round(c, 3) for c in ob.location) for ob in by_id[1])
# indici 0, 5, 8 -> (x, y, z) del file (0,0,0), (2,0,1), (2,1,0)
assert stone == [(-0.5, 0.5, 0.5), (1.5, -0.5, 0.5), (1.5, 0.5, 1.5)], stone

# lo stesso contenuto da .schematic dà gli stessi blocchi nelle stesse posizioni
key = lambda ob: (ob.blockId, ob.blockMetadata, tuple(round(c, 3) for c in ob.location))  # noqa: E731
from_schem = sorted(key(ob) for ob in objs if ob.blockId != 0)
lb = [1, 17, 0, 0, 53, 1, 0, 0, 1, 0, 0, 17]
ld = [0, 4, 0, 0, 2, 0, 0, 0, 0, 0, 0, 4]
path2 = write("test.schematic", legacy(lb, ld, w, h, l))
clear()
objs2 = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=path2, mode="INSTANCE"))
assert sorted(map(key, objs2)) == from_schem

# .nbt dei blocchi struttura: stessi blocchi nelle stesse posizioni del .schem
pos = [(i % w, i // (w * l), (i // w) % l) for i in range(w * h * l)]
nbt_path = write("test.nbt", ts.structure(states, [(v, pos[i]) for i, v in enumerate(indices)], (w, h, l)))
clear()
from_nbt = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=nbt_path, mode="INSTANCE"))
assert sorted(key(ob) for ob in from_nbt if ob.blockId != 0) == from_schem
not_structure = write("level.nbt", gzip.compress(ts._compound("", ts._int("x", 1))))
clear()
try:
    bpy.ops.import_scene.schematic_run(filepath=not_structure)
    raise AssertionError("doveva fallire")
except RuntimeError as error:
    assert "struttura" in str(error), error
assert not bpy.data.objects

# un file Sponge salvato con estensione .schematic viene riconosciuto lo stesso
path3 = write("sponge_named.schematic", ts.sponge(states, indices, w, h, l, version=2))
clear()
assert len(new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=path3))) == 9

# JOIN: un oggetto solo
clear()
joined = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=path, mode="JOIN"))
assert len(joined) == 1 and joined[0].name.startswith("Schematic")

# JOIN costruisce la mesh direttamente: un cubo pieno 6x5x4 = solo la superficie
cube = write("cube.schematic", legacy([1] * 120, [0] * 120, 6, 5, 4))
clear()
(solid,) = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=cube, mode="JOIN"))
assert len(solid.data.polygons) == 2 * (6 * 5 + 6 * 4 + 5 * 4) and not solid.data.validate()
assert solid.select_get() and bpy.context.view_layer.objects.active == solid

# JOIN = le facce degli oggetti INSTANCE, tolte quelle che toccano una faccia
# non trasparente di un altro blocco (stesse posizioni, UV e materiali)
import random  # noqa: E402
from collections import Counter  # noqa: E402

random.seed(7)
ids = sorted(addon.blockmanager.BlockManager._BlockDict)
W, H, L = 6, 5, 6
mb, md = [], []
for _ in range(W * H * L):
    r = random.random()
    mb.append(0 if r < 0.15 else 1 if r < 0.5 else random.choice(ids))
    md.append(random.randrange(16))
mix = write("mix.schematic", legacy(mb, md, W, H, L))


def faces_of(objs):
    out = []
    for ob in objs:
        me, mw = ob.data, ob.matrix_basis
        uv = me.uv_layers[0].data
        for poly in me.polygons:
            loops = range(poly.loop_start, poly.loop_start + poly.loop_total)
            corners = tuple(tuple(round(c, 6) for c in (mw @ me.vertices[me.loops[i].vertex_index].co))
                            for i in loops)
            out.append((corners, tuple(tuple(round(c, 4) for c in uv[i].uv) for i in loops),
                        me.materials[poly.material_index].name, ob))
    return out


def clear_material(ob):
    return any(n.type == "BSDF_TRANSPARENT" for m in ob.data.materials for n in m.node_tree.nodes)


clear()
inst = faces_of(new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=mix, mode="INSTANCE")))
solid_owner = {f[3]: not clear_material(f[3]) for f in inst}


def hidden(f):
    a = sorted(f[0])
    return any(g[3] is not f[3] and solid_owner[g[3]] and len(g[0]) == len(a)
               and max(abs(p - q) for u, v in zip(a, sorted(g[0])) for p, q in zip(u, v)) < 6e-5
               for g in inst)


expected = Counter(f[:3] for f in inst if not hidden(f))
clear()
(mixed,) = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=mix, mode="JOIN"))
assert Counter(f[:3] for f in faces_of([mixed])) == expected
assert not mixed.data.validate()

# Join by Block (1.12): un oggetto per tipo, chiuso; un tipo solo = come Join
clear()
(only,) = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=cube, mode="JOIN_BLOCK"))
base = lambda ob: ob.name.split(".")[0]  # noqa: E731  ("stone.001": mesh omonime di import precedenti)
assert base(only) == "stone" and len(only.data.polygons) == 2 * (6 * 5 + 6 * 4 + 5 * 4)
two_kinds = write("two_kinds.schematic", legacy([1, 3], [0, 0], 2, 1, 1))  # pietra e terra accanto
clear()
kinds = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=two_kinds, mode="JOIN_BLOCK"))
assert sorted((base(ob), len(ob.data.polygons)) for ob in kinds) == [("dirt", 6), ("stone", 6)]
clear()
by_block = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=mix, mode="JOIN_BLOCK"))
block_meshes = [ob for ob in by_block if ob.users_collection[0].name.startswith("mix")]
assert len({ob.name for ob in block_meshes}) == len(block_meshes)
assert all(not ob.data.validate() for ob in block_meshes if ob.type == "MESH")
assert sum(len(ob.data.polygons) for ob in block_meshes) >= sum(expected.values())  # >= facce del Join

# Join by Material: le stesse facce del Join, un oggetto per materiale
clear()
parts = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=mix, mode="JOIN_MATERIAL"))
meshes = [ob for ob in parts if ob.type == "MESH" and ob.users_collection[0].name.startswith("mix")]
assert Counter(f[:3] for f in faces_of(meshes)) == expected
assert all(len(ob.data.materials) == 1 and not ob.data.validate() for ob in meshes)
assert len({ob.data.materials[0].name for ob in meshes}) == len(meshes)
assert all(ob.select_get() for ob in meshes) and bpy.context.view_layer.objects.active in meshes

# texture: cartella scelta / utente / vecchio posto, anche dentro blocks/ o un resource pack
compat = addon.compat
pack = os.path.join(TMP, "pack")
deep = os.path.join(pack, "assets", "minecraft", "textures", "blocks")
os.makedirs(deep)
for folder in (pack, deep):
    open(os.path.join(folder, "pack.png" if folder == pack else "stone.png"), "wb").write(b"x")
assert compat.png_folder(pack) == deep  # non la radice con pack.png
flat = os.path.join(TMP, "flat")
os.makedirs(flat)
open(os.path.join(flat, "stone.png"), "wb").write(b"x")
assert compat.png_folder(flat) == flat and compat.png_folder(os.path.join(TMP, "none")) is None
assert compat.user_texture_dir() is None  # avviato dai sorgenti, non come estensione
assert compat.texture_dirs()[-1] == os.path.join(HERE, "textures")
real_dirs = compat.texture_dirs
compat.texture_dirs = lambda: [os.path.join(TMP, "none"), pack, flat]
assert compat.texture_dir() == deep
compat.texture_dirs = real_dirs

# formati non supportati / file rotti: errore leggibile, niente oggetti
for bad_name, data in (("x.litematic", b"x"), ("broken.schem", ts.sponge(states, indices[:-1], w, h, l))):
    p = write(bad_name, data)
    clear()
    try:
        bpy.ops.import_scene.schematic_run(filepath=p)
        raise AssertionError("doveva fallire: " + bad_name)
    except RuntimeError as error:
        assert "Litematica" in str(error) or "corrotto" in str(error), error
    assert not bpy.data.objects

# --- regressioni della review
clear()
bark = write("bark.schematic", legacy([17, 17, 17, 1], [12, 12, 2, 0], 4, 1, 1))
for _ in range(2):
    new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=bark))
names = {m.name for m in bpy.data.materials}
assert "Oak Log Side" in names and not any(n.startswith("Oak Log Side Side") for n in names)  # nome stabile
assert "Unknown 17" in names and not any("built-in" in n for n in names)  # betulla: nome giusto
assert any(ob.blockId == 1 for ob in bpy.data.objects)  # la pietra era registrata con id 3

# la selezione dell'utente non cambia (prima le scale facevano select_pattern)
clear()
mine = bpy.data.objects.new("Mine", None)
scene.collection.objects.link(mine)
mine.select_set(True)
stairs = write("stairs.schematic", legacy([53, 53], [1, 6], 2, 1, 1))
new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=stairs))
assert mine.select_get()

# le proprieta' blockId / blockMetadata nascono con register() e spariscono con unregister()
addon.unregister()
assert not hasattr(bpy.types.Object, "blockId")
print("test_import: ok")
