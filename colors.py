"""Colori al posto delle texture: un materiale a tinta unita per ogni texture.

Ogni texture di Minecraft usata nel file (materiali "mc ..." dell'import con i
modelli) riceve un materiale Principled BSDF con il suo colore medio, che si
cambia e si rinomina dal pannello nella barra laterale della vista 3D.
"Usa colori" mette questi materiali al posto di quelli con le texture (e
viceversa). Colori e nomi si salvano in un preset, un file dell'addon che
resta dopo gli aggiornamenti e vale per tutti i file .blend.
"""

import json
import os

import bpy
import numpy as np
from bpy.props import BoolProperty, FloatVectorProperty, IntProperty
from bpy.types import Operator, Panel, UIList

PRESET_NAME = "texture_colors.json"


# --- quale texture c'e' in un materiale "mc ..."

def _image_node(mat):
    if mat.node_tree is None:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image), None)


def texture_of(mat):
    """"minecraft:block/stone" per un materiale dell'import con i modelli, o None.
    Con piu' strati (fianco dell'erba) conta il primo, quello sotto."""
    if mat is None or mat.get("mc_flat") or not mat.get("mc_key"):
        return None
    if mat.get("mc_texture") is not None:
        return mat["mc_texture"] or None  # "" = texture mancante (magenta)
    node = _image_node(mat)  # materiali fatti dalla 0.4.0/0.4.1: dal nome dell'immagine
    if node is None or not node.image.name.startswith("mc "):
        return None
    name = node.image.name[3:]
    if name[-4:-3] == "." and name[-3:].isdigit():
        name = name[:-4]
    return "minecraft:" + name


def _tint_of(mat):
    if mat.get("mc_tint") is not None:
        return tuple(mat["mc_tint"])
    for node in mat.node_tree.nodes if mat.node_tree else ():
        if node.type == "MIX" and getattr(node, "blend_type", "") == "MULTIPLY":
            value = next(s for s in node.inputs if s.identifier == "B_Color").default_value
            return tuple(value[:3])
    return (1.0, 1.0, 1.0)


def _linear(values):
    return np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def average_color(image, tint=(1.0, 1.0, 1.0)):
    """Colore medio lineare dei pixel visibili (primo fotogramma), per la tinta."""
    w, h = image.size
    if not w or not h:
        return (0.5, 0.5, 0.5)
    px = np.empty(w * h * 4, np.float32)
    image.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    if h > w and h % w == 0:
        px = px[h - w:]  # animata: il primo fotogramma e' in alto (Blender parte dal basso)
    px = px.reshape(-1, 4)
    visible = px[px[:, 3] > 0.5]
    if not len(visible):
        visible = px
    # image.pixels dei png a 8 bit sono sRGB: la media si fa in lineare
    rgb = _linear(visible[:, :3].astype(np.float64)).mean(axis=0) * np.array(tint[:3])
    return tuple(float(c) for c in np.clip(rgb, 0.0, 1.0))


# --- preset

def preset_path(create=False):
    """File del preset: nella cartella utente dell'estensione (resta dopo gli
    aggiornamenti), o accanto all'addon se avviato dai sorgenti."""
    try:
        folder = bpy.utils.extension_path_user(__package__, path="presets", create=create)
    except ValueError:
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets")
        if create:
            os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, PRESET_NAME)


def load_preset():
    """{texture: {"color": [r, g, b] lineare, "name": nome del materiale}}."""
    path = preset_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    textures = data.get("textures", {}) if isinstance(data, dict) else {}
    return {k: v for k, v in textures.items() if isinstance(v, dict)}


def save_preset(materials):
    """Aggiunge / aggiorna nel preset le texture di questi materiali a tinta unita;
    quelle gia' salvate e non presenti nel file restano. Torna (percorso, quante)."""
    textures = load_preset()
    count = 0
    for mat in materials:
        texture = mat.get("mc_flat")
        if texture:
            textures[texture] = {"color": [round(c, 6) for c in mat.s2b_color], "name": mat.name}
            count += 1
    path = preset_path(create=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "textures": textures}, f, indent=1, sort_keys=True)
    return path, count


# --- materiali a tinta unita

def flat_materials():
    return {m["mc_flat"]: m for m in bpy.data.materials if m.get("mc_flat")}


def _set_color(mat, color):
    """Colore del Principled BSDF e della vista Solid."""
    if mat.node_tree is not None:
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    mat.diffuse_color = (*color, 1.0)


def _color_update(mat, _context):
    _set_color(mat, tuple(mat.s2b_color))


def _has_alpha(image):
    px = np.empty(image.size[0] * image.size[1] * 4, np.float32)
    image.pixels.foreach_get(px)
    return bool(len(px)) and float(px[3::4].min()) < 0.99


def _new_flat(texture, color, name, mask=None):
    """mask: immagine con trasparenza (fiori, foglie, vetro, torce): il colore e'
    pieno ma la sagoma resta quella della texture, dal suo canale alpha."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat["mc_flat"] = texture
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is not None:
        bsdf.inputs["Roughness"].default_value = 1.0
        if mask is not None:
            tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tex.image, tex.interpolation = mask, "Closest"
            tex.location = (bsdf.location.x - 350, bsdf.location.y - 200)
            mat.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    mat.s2b_color = color  # chiama _color_update
    _set_color(mat, tuple(color))
    return mat


def ensure_flats(materials=None):
    """Un materiale a tinta unita per ogni texture dei materiali "mc ..." (tutti
    quelli del file se materials e' None). Colore e nome dal preset, se c'e',
    altrimenti colore medio e nome della texture. Torna quanti ne ha creati."""
    flats = flat_materials()
    preset = load_preset()
    made = 0
    for mat in list(bpy.data.materials if materials is None else materials):
        texture = texture_of(mat)
        if texture is None or texture in flats:
            continue
        saved = preset.get(texture, {})
        color = saved.get("color")
        if not (isinstance(color, list) and len(color) == 3):
            source = _image_node(mat)
            color = average_color(source.image, _tint_of(mat)) if source else (0.5, 0.5, 0.5)
        name = saved.get("name") or texture.split("/")[-1]
        node = _image_node(mat)
        mask = node.image if node is not None and _has_alpha(node.image) else None
        flats[texture] = flat = _new_flat(texture, tuple(color), name, mask)
        flat["mc_image"] = node.image.name if node else ""  # anteprima nella lista
        made += 1
    return made


def apply_preset():
    """Colori e nomi del preset sui materiali a tinta unita gia' nel file."""
    preset = load_preset()
    count = 0
    for texture, mat in flat_materials().items():
        saved = preset.get(texture)
        if not saved:
            continue
        color = saved.get("color")
        if isinstance(color, list) and len(color) == 3:
            mat.s2b_color = color
        if saved.get("name"):
            mat.name = saved["name"]
        count += 1
    return count


def reset_color(mat):
    """Torna al colore medio della texture."""
    texture = mat.get("mc_flat")
    for source in bpy.data.materials:
        if texture_of(source) == texture:
            node = _image_node(source)
            if node is not None:
                mat.s2b_color = average_color(node.image, _tint_of(source))
                return True
    return False


def use_colors(on, meshes=None):
    """Mette i materiali a tinta unita al posto di quelli con le texture (on) o
    rimette le texture. I materiali tolti restano nel file (fake user) e la mesh
    ricorda quali erano, slot per slot."""
    if on:
        ensure_flats()
    flats = flat_materials()
    changed = 0
    for mesh in list(bpy.data.meshes if meshes is None else meshes):
        if on:
            if mesh.get("mc_textured"):
                continue  # gia' a colori
            before, swapped = [], False
            for i, mat in enumerate(mesh.materials):
                flat = flats.get(texture_of(mat))
                before.append(mat.name if flat is not None else "")
                if flat is not None:
                    mat.use_fake_user = True  # resta nel .blend per tornare alle texture
                    mesh.materials[i] = flat
                    swapped = True
            if swapped:
                mesh["mc_textured"] = before
                changed += 1
        else:
            names = mesh.get("mc_textured")
            if not names:
                continue
            for i, name in enumerate(list(names)[:len(mesh.materials)]):
                mat = bpy.data.materials.get(name) if name else None
                if mat is not None:
                    mesh.materials[i] = mat
            del mesh["mc_textured"]
            changed += 1
    return changed


def _use_colors_update(scene, _context):
    use_colors(scene.s2b_use_colors)


def after_import(scene, materials, meshes):
    """Dopo un import con i modelli: materiali a tinta unita per le texture
    nuove e, se "Usa colori" e' attivo, subito sulle mesh importate."""
    ensure_flats(materials)
    if scene.s2b_use_colors:
        use_colors(True, meshes)


# --- interfaccia

class SCHEMATIC_UL_colors(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        image = bpy.data.images.get(item.get("mc_image", ""))
        icon = 0
        if image is not None:
            image.preview_ensure()
            icon = image.preview.icon_id
        if icon:
            row.label(text="", icon_value=icon)
        else:
            row.label(text="", icon="TEXTURE")
        swatch = row.row(align=True)
        swatch.ui_units_x = 2.5
        swatch.prop(item, "s2b_color", text="")  # clic: ruota dei colori
        row.prop(item, "name", text="")

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flags = [self.bitflag_filter_item if m.get("mc_flat") else 0 for m in items]
        if self.filter_name:
            needle = self.filter_name.lower()
            flags = [f if f and (needle in m.name.lower() or needle in str(m.get("mc_flat")).lower()) else 0
                     for f, m in zip(flags, items)]
        order = bpy.types.UI_UL_list.sort_items_by_name(items, "name")
        return flags, order


class SCHEMATIC_OT_colors_create(Operator):
    """Crea un materiale a tinta unita (colore medio) per ogni texture di Minecraft nel file"""

    bl_idname = "schematic.colors_create"
    bl_label = "Crea colori dalle texture"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        made = ensure_flats()
        if context.scene.s2b_use_colors:
            use_colors(True)
        self.report({"INFO"}, "%d colori creati" % made if made else
                    "Nessuna texture nuova (servono import fatti con Minecraft Assets)")
        return {"FINISHED"}


class SCHEMATIC_OT_colors_reset(Operator):
    """Rimette il colore medio della texture"""

    bl_idname = "schematic.colors_reset"
    bl_label = "Colore medio"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mats = bpy.data.materials
        index = context.scene.s2b_color_index
        if not (0 <= index < len(mats)) or not mats[index].get("mc_flat"):
            self.report({"WARNING"}, "Seleziona un colore nella lista")
            return {"CANCELLED"}
        if not reset_color(mats[index]):
            self.report({"WARNING"}, "La texture di questo colore non e' piu' nel file")
            return {"CANCELLED"}
        return {"FINISHED"}


class SCHEMATIC_OT_colors_save(Operator):
    """Salva colori e nomi nel preset dell'addon: valgono per i prossimi import e gli altri file"""

    bl_idname = "schematic.colors_save"
    bl_label = "Salva preset"

    def execute(self, context):
        try:
            path, count = save_preset(flat_materials().values())
        except OSError as error:
            self.report({"ERROR"}, "Preset non salvato: %s" % error)
            return {"CANCELLED"}
        self.report({"INFO"}, "%d colori salvati in %s" % (count, path))
        return {"FINISHED"}


class SCHEMATIC_OT_colors_load(Operator):
    """Rimette colori e nomi salvati nel preset sui materiali di questo file"""

    bl_idname = "schematic.colors_load"
    bl_label = "Carica preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = apply_preset()
        self.report({"INFO"}, "%d colori dal preset" % count if count else "Nessun colore del preset in questo file")
        return {"FINISHED"}


class SCHEMATIC_PT_colors(Panel):
    bl_label = "Colori delle texture"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Schematic"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "s2b_use_colors", icon="COLOR")
        layout.operator(SCHEMATIC_OT_colors_create.bl_idname, icon="ADD")
        layout.template_list("SCHEMATIC_UL_colors", "", bpy.data, "materials", scene, "s2b_color_index", rows=8)
        mats = bpy.data.materials
        index = scene.s2b_color_index
        if 0 <= index < len(mats) and mats[index].get("mc_flat"):
            box = layout.box()
            box.label(text=mats[index]["mc_flat"], icon="TEXTURE")
            box.prop(mats[index], "name", text="Nome")
            box.prop(mats[index], "s2b_color", text="Colore")
            box.operator(SCHEMATIC_OT_colors_reset.bl_idname, icon="LOOP_BACK")
        row = layout.row(align=True)
        row.operator(SCHEMATIC_OT_colors_save.bl_idname, icon="FILE_TICK")
        row.operator(SCHEMATIC_OT_colors_load.bl_idname, icon="IMPORT")
        count = len(load_preset())
        layout.label(text="Preset: %d texture salvate" % count if count else "Preset: vuoto", icon="PRESET")


CLASSES = (SCHEMATIC_UL_colors, SCHEMATIC_OT_colors_create, SCHEMATIC_OT_colors_reset,
           SCHEMATIC_OT_colors_save, SCHEMATIC_OT_colors_load, SCHEMATIC_PT_colors)


def register():
    bpy.types.Material.s2b_color = FloatVectorProperty(
        name="Colore", subtype="COLOR", size=3, min=0.0, max=1.0, default=(0.5, 0.5, 0.5),
        update=_color_update, description="Colore a tinta unita al posto della texture")
    bpy.types.Scene.s2b_use_colors = BoolProperty(
        name="Usa colori al posto delle texture", default=False, update=_use_colors_update,
        description="Sostituisce i materiali con le texture di Minecraft con quelli a tinta unita")
    bpy.types.Scene.s2b_color_index = IntProperty(default=-1)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.s2b_color_index
    del bpy.types.Scene.s2b_use_colors
    del bpy.types.Material.s2b_color
