"""Pezzi che l'addon dava per scontati su Blender 2.7x e non esistono piu'."""

import os

import bmesh
import bpy


def ensure_diffuse(mat):
    """Ricrea la coppia di default 2.7x "Diffuse BSDF" -> "Material Output".

    Da Blender 2.80 un materiale nuovo nasce con un Principled BSDF, mentre
    l'addon cerca nodes["Diffuse BSDF"].
    """
    nt = mat.node_tree
    for node in list(nt.nodes):
        if node.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(node)
    diffuse = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.location = [0, 0]
    nt.links.new(diffuse.outputs[0], nt.nodes["Material Output"].inputs[0])


def fix_normals(mesh):
    """Normali verso l'esterno, come Edit Mode > Normals > Recalculate Outside.

    Prima ogni blocco entrava e usciva dalla modalita' Edit con bpy.ops: lento e
    sempre piu' lento al crescere della scena (costo quadratico sull'import).
    normals_make_consistent esegue proprio recalc_face_normals su un bmesh.
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def texture_dir():
    """Le texture stanno nell'addon, non accanto al .blend aperto."""
    return os.path.join(os.path.dirname(__file__), "textures", "blocks")


# Il codice usa i nomi texture pre-MC 1.6, le texture incluse hanno quelli nuovi.
_WOOL = ["white", "orange", "magenta", "light_blue", "yellow", "lime", "pink",
         "gray", "silver", "cyan", "purple", "blue", "brown", "green", "red", "black"]

TEXTURE_ALIASES = {
    "tree_side": "log_oak",
    "tree_top": "log_oak_top",
    "tree_spruce": "log_spruce",
    "texture_side": "pumpkin_side",
    "hellsand": "soul_sand",
    "lightgem": "glowstone",
    "netherquartz": "quartz_ore",
    "mycel_side": "mycelium_side",
    "mycel_top": "mycelium_top",
    "pumpkin_face": "pumpkin_face_off",
    "pumpkin_jack": "pumpkin_face_on",
    "quartzblock_side": "quartz_block_side",
    "quartzblock_top": "quartz_block_top",
    "quartzblock_bottom": "quartz_block_bottom",
    "quartzblock_chiseled": "quartz_block_chiseled",
    "quartzblock_chiseled_top": "quartz_block_chiseled_top",
    "sandstone_side": "sandstone_normal",
    "stoneslab_side": "stone_slab_side",
    "stoneslab_top": "stone_slab_top",
    "workbench_front": "crafting_table_front",
    "workbench_side": "crafting_table_side",
    "workbench_top": "crafting_table_top",
    "blockDiamond": "diamond_block",
    "blockEmerald": "emerald_block",
    "blockGold": "gold_block",
    "blockLapis": "lapis_block",
    "blockRedstone": "redstone_block",
    "blockSnow": "snow",
    "commandBlock": "command_block",
    "musicBlock": "noteblock",
    "netherBrick": "nether_brick",
    "oreCoal": "coal_ore",
    "oreDiamond": "diamond_ore",
    "oreEmerald": "emerald_ore",
    "oreGold": "gold_ore",
    "oreIron": "iron_ore",
    "oreLapis": "lapis_ore",
    "oreRedstone": "redstone_ore",
    "redstoneLight": "redstone_lamp_off",
    "redstoneLight_lit": "redstone_lamp_on",
    "stoneMoss": "cobblestone_mossy",
    "whiteStone": "end_stone",
}
TEXTURE_ALIASES.update(
    {"cloth_%d" % i: "wool_colored_%s" % color for i, color in enumerate(_WOOL)})

_MISSING_NAME = "mcedit2blender_missing"


def load_texture(path, image_name):
    """Carica la texture, con un placeholder magenta se il file non c'e'.

    Senza questo una sola texture mancante fa abortire l'import di tutto
    lo schematic.
    """
    if os.path.isfile(path):
        image = bpy.data.images.load(path)
        image.name = image_name
        return image
    placeholder = bpy.data.images.get(_MISSING_NAME)
    if placeholder is None:
        placeholder = bpy.data.images.new(_MISSING_NAME, 16, 16)
        placeholder.generated_color = (1.0, 0.0, 1.0, 1.0)
    print("MCEdit2Blender: texture mancante, uso il placeholder:", path)
    return placeholder


def action_fcurves(action):
    """Le fcurve di un'azione, con le Action a livelli di Blender 4.4+.

    Prima erano in action.fcurves, che ora non esiste piu'.
    """
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    curves = []
    for layer in action.layers:
        for strip in layer.strips:
            for channelbag in strip.channelbags:
                curves.extend(channelbag.fcurves)
    return curves
