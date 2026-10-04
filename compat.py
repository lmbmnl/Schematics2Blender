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


# dentro la cartella scelta le .png possono stare anche in una di queste
# sottocartelle; prima le piu' profonde (la radice di un resource pack ha pack.png)
_PNG_SUBDIRS = (
    os.path.join("assets", "minecraft", "textures", "blocks"),  # resource pack 1.8-1.12
    os.path.join("textures", "blocks"),
    "blocks",
    "",
)


def png_folder(folder):
    """La cartella con le .png dentro folder, o None."""
    for sub in _PNG_SUBDIRS:
        path = os.path.join(folder, sub)
        if os.path.isdir(path) and any(n.lower().endswith(".png") for n in os.listdir(path)):
            return os.path.normpath(path)
    return None


def user_texture_dir(create=False):
    """Cartella texture dell'utente, fuori dall'addon: resta dopo aggiornamenti
    e reinstallazioni. None se l'addon non e' installato come estensione."""
    try:
        return bpy.utils.extension_path_user(__package__, path="textures", create=create)
    except ValueError:  # avviato dai sorgenti o dai test
        return None


def _prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return getattr(addon, "preferences", None)


def assets_path():
    """client.jar / resource pack scelto nelle preferenze, o "" (modelli 1.12)."""
    return bpy.path.abspath(getattr(_prefs(), "assets_path", "") or "")


def assets_status(path):
    """(testo, icona) per le preferenze."""
    if not path:
        return "Non impostato: si usano i modelli dell'addon (solo blocchi 1.12)", "INFO"
    from .mcassets import Assets
    try:
        assets = Assets([bpy.path.abspath(path)])
    except (IOError, OSError) as error:
        return str(error), "ERROR"
    try:
        if not assets.has_blockstates():
            return "Non contiene i modelli dei blocchi (assets/minecraft/blockstates)", "ERROR"
        return "Modelli e texture di Minecraft trovati", "CHECKMARK"
    finally:
        assets.close()


def texture_dirs():
    """Dove cercare le texture, in ordine."""
    dirs = []
    addon = bpy.context.preferences.addons.get(__package__)
    chosen = getattr(getattr(addon, "preferences", None), "texture_dir", "")
    if chosen:
        dirs.append(bpy.path.abspath(chosen))  # 1. scelta nelle preferenze
    user = user_texture_dir()
    if user:
        dirs.append(user)  # 2. cartella utente dell'estensione
    dirs.append(os.path.join(os.path.dirname(__file__), "textures"))  # 3. vecchio posto
    return dirs


def texture_dir():
    """La prima cartella che contiene delle .png (altrimenti la vecchia)."""
    for folder in texture_dirs():
        found = png_folder(folder)
        if found:
            return found
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

_MISSING_NAME = "schematics2blender_missing"


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
    print("Schematics2Blender: texture mancante, uso il placeholder:", path)
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
