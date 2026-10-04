# Run: blender -b --factory-startup --python test_models.py
# Import con i modelli di Minecraft, su asset finti scritti qui (niente file Mojang).
import gzip
import importlib.util
import json
import os
import struct
import sys
import tempfile
import zlib

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "schematics2blender", os.path.join(HERE, "__init__.py"), submodule_search_locations=[HERE])
addon = importlib.util.module_from_spec(spec)
sys.modules["schematics2blender"] = addon
spec.loader.exec_module(addon)
sys.path.insert(0, HERE)
import test_schem as ts  # noqa: E402

TMP = tempfile.mkdtemp()
ASSETS = os.path.join(TMP, "pack")


def put(rel, data):
    path = os.path.join(ASSETS, "assets", "minecraft", *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else json.dumps(data).encode())


def png(rgba, size=2):
    """PNG RGBA size x size di un colore solo."""
    rows = b"".join(b"\0" + bytes(rgba) * size for _ in range(size))
    chunk = lambda kind, body: (struct.pack(">I", len(body)) + kind + body  # noqa: E731
                                + struct.pack(">I", zlib.crc32(kind + body)))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


faces = {d: {"texture": "#all", "cullface": d} for d in ("down", "up", "north", "south", "west", "east")}
put("models/block/cube_all.json", {"elements": [{"from": [0, 0, 0], "to": [16, 16, 16], "faces": faces}]})
for name in ("stone", "glass"):
    put("blockstates/%s.json" % name, {"variants": {"": {"model": "minecraft:block/" + name}}})
    put("models/block/%s.json" % name, {"parent": "minecraft:block/cube_all",
                                        "textures": {"all": "minecraft:block/" + name}})
put("textures/block/stone.png", png((128, 128, 128, 255)))
put("textures/block/glass.png", png((200, 220, 255, 0)))  # trasparente: cutout
put("textures/block/wall.png", png((90, 90, 90, 255)))
post = {d: {"texture": "#t"} for d in ("down", "up", "north", "south", "west", "east")}
put("models/block/wall_post.json", {"textures": {"t": "minecraft:block/wall"},
                                    "elements": [{"from": [4, 0, 4], "to": [12, 16, 12], "faces": post}]})
put("models/block/wall_side.json", {"textures": {"t": "minecraft:block/wall"},
                                    "elements": [{"from": [5, 0, 0], "to": [11, 14, 8], "faces": post}]})
put("blockstates/cobblestone_wall.json", {"multipart": [
    {"when": {"up": "true"}, "apply": {"model": "minecraft:block/wall_post"}},
    {"when": {"north": "low"}, "apply": {"model": "minecraft:block/wall_side", "uvlock": True}},
    {"when": {"east": "low"}, "apply": {"model": "minecraft:block/wall_side", "y": 90, "uvlock": True}},
    {"when": {"south": "low"}, "apply": {"model": "minecraft:block/wall_side", "y": 180, "uvlock": True}},
    {"when": {"west": "low"}, "apply": {"model": "minecraft:block/wall_side", "y": 270, "uvlock": True}},
]})

addon.compat.assets_path = lambda: ASSETS  # come se fosse scelto nelle preferenze
addon.register()


def write(name, data):
    path = os.path.join(TMP, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def run(path, mode):
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    assert bpy.ops.import_scene.schematic_run(filepath=path, mode=mode) == {"FINISHED"}
    return list(bpy.data.objects)


# due pietre accanto: Join = 10 facce (quella in mezzo sparisce), Instance = 2 oggetti
states = ["minecraft:air", "minecraft:stone", "modded:thing"]
two = write("two.schem", ts.sponge(states, [1, 1, 0], 3, 1, 1, version=3))
(joined,) = run(two, "JOIN")
assert len(joined.data.polygons) == 10 and not joined.data.validate()
assert joined.data.materials[0].name == "mc stone"
objs = run(two, "INSTANCE")
assert len(objs) == 2 and all(ob["mc_state"] == "minecraft:stone" for ob in objs)
assert objs[0].data == objs[1].data  # la mesh e' condivisa
# stesso spazio dell'import 1.12: la pietra in (0,0,0) del file occupa la cella (-1, -1, 0)
assert sorted(tuple(ob.location) for ob in objs) == [(-1, -1, 0), (0, -1, 0)], [tuple(ob.location) for ob in objs]
# il secondo import riusa materiali e immagini
assert [m.name for m in bpy.data.materials if m.name.startswith("mc stone")] == ["mc stone"]

# Join by Material: pietra e vetro in due oggetti, uno per materiale
mixed = write("mixed.schem", ts.sponge(["minecraft:air", "minecraft:stone", "minecraft:glass"],
                                       [1, 2, 1], 3, 1, 1))
(whole,) = run(mixed, "JOIN")
whole_faces = sorted((round(p.center.x, 4), round(p.center.y, 4), round(p.center.z, 4),
                      whole.data.materials[p.material_index].name) for p in whole.data.polygons)
parts = run(mixed, "JOIN_MATERIAL")
assert sorted(ob.name for ob in parts) == ["glass", "stone"]
assert parts[0].users_collection[0].name == "mixed"
part_faces = sorted((round(p.center.x, 4), round(p.center.y, 4), round(p.center.z, 4),
                     ob.data.materials[p.material_index].name) for ob in parts for p in ob.data.polygons)
assert part_faces == whole_faces and all(not ob.data.validate() for ob in parts)

# blocco senza blockstate (mod): cubo magenta
(odd,) = run(write("odd.schem", ts.sponge(states, [2], 1, 1, 1)), "JOIN")
assert len(odd.data.polygons) == 6
bsdf = odd.data.materials[0].node_tree.nodes["Principled BSDF"]
assert tuple(bsdf.inputs["Base Color"].default_value) == (1, 0, 1, 1)

# vetro accanto a vetro: la faccia in comune sparisce anche se trasparente; alpha collegato
glass = write("glass.schem", ts.sponge(["minecraft:air", "minecraft:glass"], [1, 1], 2, 1, 1))
(g,) = run(glass, "JOIN")
assert len(g.data.polygons) == 10
assert g.data.materials[0].node_tree.nodes["Principled BSDF"].inputs["Alpha"].is_linked

# .schematic 1.12: i muretti (139) prendono le connessioni dai vicini
body = (ts._short("Width", 3) + ts._short("Height", 1) + ts._short("Length", 1)
        + ts._bytes("Blocks", [139, 139, 1]) + ts._bytes("Data", [0, 0, 0]))
wall_path = write("walls.schematic", gzip.compress(ts._compound("Schematic", body)))
walls = run(wall_path, "INSTANCE")
got = sorted((ob.location.x, ob["mc_state"]) for ob in walls if "wall" in ob["mc_state"])
assert got == [(-1, "minecraft:cobblestone_wall[east=low,north=none,south=none,up=true,west=none]"),
               (0, "minecraft:cobblestone_wall[east=low,north=none,south=none,up=false,west=low]")], got  # dritto: niente palo
(wj,) = run(wall_path, "JOIN")
assert not wj.data.validate()

# staccionata o vetro isolato: resta nello stato che aveva (prima: IndexError a meta' import)
body = (ts._short("Width", 6) + ts._short("Height", 1) + ts._short("Length", 1)
        + ts._bytes("Blocks", [85, 0, 85, 85, 0, 102]) + ts._bytes("Data", [0] * 6))
alone = write("alone.schematic", gzip.compress(ts._compound("Schematic", body)))
assert len(run(alone, "INSTANCE")) == 4
(aj,) = run(alone, "JOIN")
assert not aj.data.validate()

# coppie di facce coincidenti tra blocchi diversi: niente facce doppie nella mesh
mcimport = addon.mcimport
import numpy as np  # noqa: E402
quad = np.array([[0, 0, 0], [0, 1, 0], [0, 1, 1], [0, 0, 1]], float)
corners = np.concatenate((quad, quad[::-1], quad + [5, 0, 0], quad[::-1] + [5, 0, 0]))
kept, keep = mcimport._split_coincident(corners, np.array([4, 4, 4, 4]),
                                        np.array([True, True, False, True]))
assert keep.tolist() == [False, False, True, True] and len(kept) == 8  # opache: via; altre: staccate
assert np.abs(kept[:4] - kept[4:]).max() > 0

# --- colori a tinta unita al posto delle texture (pannello Schematic)
colors = addon.colors
colors.preset_path = lambda create=False: os.path.join(TMP, "texture_colors.json")
(joined,) = run(two, "JOIN")
flats = colors.flat_materials()
assert "minecraft:block/stone" in flats  # creato da solo dopo l'import
stone = flats["minecraft:block/stone"]
srgb = 128 / 255.0
expected = ((srgb + 0.055) / 1.055) ** 2.4  # media in lineare del grigio 128
assert all(abs(c - expected) < 1e-4 for c in stone.s2b_color), tuple(stone.s2b_color)
bsdf = stone.node_tree.nodes["Principled BSDF"]
assert abs(bsdf.inputs["Base Color"].default_value[0] - expected) < 1e-4
stone.s2b_color = (0.1, 0.2, 0.3)  # come dalla ruota dei colori
assert tuple(round(c, 4) for c in bsdf.inputs["Base Color"].default_value) == (0.1, 0.2, 0.3, 1.0)
assert tuple(round(c, 4) for c in stone.diffuse_color) == (0.1, 0.2, 0.3, 1.0)

scene = bpy.context.scene
scene.s2b_use_colors = True
assert [m.name for m in joined.data.materials] == [stone.name]
textured = bpy.data.materials["mc stone"]
assert textured.use_fake_user  # resta nel file per tornare indietro
scene.s2b_use_colors = False
assert [m.name for m in joined.data.materials] == ["mc stone"] and "mc_textured" not in joined.data

# rinomina + preset: un file nuovo (qui: materiali cancellati) riprende nome e colore
stone.name = "Pietra"
assert colors.save_preset(colors.flat_materials().values())[1] >= 1
bpy.data.materials.remove(stone)
assert colors.ensure_flats() >= 1
again = colors.flat_materials()["minecraft:block/stone"]
assert again.name == "Pietra" and tuple(round(c, 4) for c in again.s2b_color) == (0.1, 0.2, 0.3)
again.s2b_color = (1, 1, 1)
assert colors.apply_preset() >= 1 and tuple(round(c, 4) for c in again.s2b_color) == (0.1, 0.2, 0.3)
assert colors.reset_color(again) and abs(again.s2b_color[0] - expected) < 1e-4

# "Usa colori" attivo: l'import mette subito i colori, anche in Instance
scene.s2b_use_colors = True
objs = run(two, "INSTANCE")
assert all(ob.data.materials[0] == again for ob in objs)
scene.s2b_use_colors = False
assert all(ob.data.materials[0].name == "mc stone" for ob in objs)

# texture con trasparenza (vetro): colore pieno ma sagoma dalla texture
run(glass, "JOIN")
clear_flat = colors.flat_materials()["minecraft:block/glass"]
assert clear_flat.node_tree.nodes["Principled BSDF"].inputs["Alpha"].is_linked
assert not again.node_tree.nodes["Principled BSDF"].inputs["Alpha"].is_linked  # pietra: opaca

addon.unregister()
assert not hasattr(bpy.types.Material, "s2b_color")
print("test_models: ok")
