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

# un file Sponge salvato con estensione .schematic viene riconosciuto lo stesso
path3 = write("sponge_named.schematic", ts.sponge(states, indices, w, h, l, version=2))
clear()
assert len(new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=path3))) == 9

# JOIN: un oggetto solo
clear()
joined = new_objects(lambda: bpy.ops.import_scene.schematic_run(filepath=path, mode="JOIN"))
assert len(joined) == 1 and joined[0].name.startswith("Schematic")

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
