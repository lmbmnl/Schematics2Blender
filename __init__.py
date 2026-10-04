import math
import os
import time

import bpy
import numpy as np
from bpy.props import EnumProperty, StringProperty
from bpy.types import AddonPreferences, Operator
from bpy_extras.io_utils import ImportHelper

from . import colors, compat, fastjoin, mcassets, mcimport, nbt
from .blockmanager import BlockManager
from .blocks.Unknown import Unknown
from .schem import is_sponge, read_schem, read_schem_states, state_of_legacy

# ogni tick del modal lavora ~40ms e poi restituisce il controllo a Blender,
# cosi' la percentuale si aggiorna invece di bloccare la finestra
_TICK_SECONDS = 0.04

_KEY = 4096  # chiave Join = id * _KEY + metadata
_CHUNK = 500  # Instance con i modelli: oggetti creati per passo


MODE_ITEMS = [
    ("INSTANCE", "Instance", "Un oggetto separato per ogni blocco"),
    ("JOIN", "Join", "Unisce tutti i blocchi in una mesh sola e salda i vertici sovrapposti"),
]


EXTENSIONS = (".schematic", ".schem")


def _read_schematic(filepath):
    """Legge .schematic (MCEdit) o .schem (Sponge, WorldEdit 1.13+).

    Torna (blocks, data, width, length, unknown): id e metadata legacy per
    blocco, unknown = {id negativo: nome} dei blocchi moderni senza modello.
    Il formato si riconosce dal contenuto: c'e' chi salva Sponge come .schematic.
    """
    nbtfile = _open_nbt(filepath)
    if is_sponge(nbtfile):
        return read_schem(nbtfile)
    return _legacy_arrays(nbtfile)


def _read_states(filepath):
    """Per i modelli di Minecraft: (palette di stati, indice per blocco, width,
    length, da_1.12). Il .schematic 1.12 viene convertito in stati moderni."""
    nbtfile = _open_nbt(filepath)
    if is_sponge(nbtfile):
        indices, palette, width, length = read_schem_states(nbtfile)
        return palette, indices, width, length, False
    blocks, data, width, length, _unknown = _legacy_arrays(nbtfile)
    keys = fastjoin.int_array(blocks) * _KEY + (fastjoin.int_array(data) & (_KEY - 1))
    unique, indices = np.unique(keys, return_inverse=True)
    palette = []
    for key in unique.tolist():
        block_id, metadata = key // _KEY, key % _KEY
        state = "minecraft:air" if block_id == 0 else state_of_legacy(block_id, metadata)
        palette.append(state or "minecraft:legacy_id_%d" % block_id)  # senza equivalente: magenta
    return palette, indices, width, length, True


def _open_nbt(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".litematic":
        raise IOError("I file Litematica (.litematic) non sono supportati")
    if ext not in EXTENSIONS:
        raise IOError("Il file selezionato non e' un .schematic o .schem")
    return nbt.nbt.NBTFile(filepath, "rb")


def _legacy_arrays(nbtfile):
    for key in ("Blocks", "Data", "Width", "Length"):
        if key not in nbtfile:
            raise IOError("file .schematic non valido: manca il campo %s" % key)
    return (nbtfile["Blocks"].value, nbtfile["Data"],
            nbtfile["Width"].value & 0xFFFF, nbtfile["Length"].value & 0xFFFF, {})


def _prepare_scene(scene):
    # scelta del progetto originale: Cycles e 20 fps (i tick di Minecraft, il fuoco
    # anima un fotogramma per frame). Ora sulla scena corrente, non scenes[0]
    scene.render.engine = "CYCLES"
    scene.render.fps = 20
    scene.render.fps_base = 1


class SCHEMATIC_OT_import(Operator, ImportHelper):
    """Importa uno schematic di Minecraft (.schematic MCEdit o .schem WorldEdit)"""

    bl_idname = "import_scene.schematic"
    bl_label = "Import Schematic"

    filename_ext = ".schematic"
    filter_glob: StringProperty(default="*.schematic;*.schem", options={"HIDDEN"})

    def execute(self, context):
        return bpy.ops.import_scene.schematic_mode("INVOKE_DEFAULT", filepath=self.filepath)


class SCHEMATIC_OT_mode(Operator):
    """Chiede come assemblare i blocchi importati"""

    bl_idname = "import_scene.schematic_mode"
    bl_label = "Import Schematic"

    filepath: StringProperty(subtype="FILE_PATH")

    def invoke(self, context, event):
        # invoke_popup: solo i due pulsanti, senza l'OK di invoke_props_dialog
        # (che in 5.2 non accetta confirm=False)
        return context.window_manager.invoke_popup(self, width=300)

    def draw(self, context):
        col = self.layout.column()
        col.label(text=os.path.basename(self.filepath))
        col.separator()
        row = col.row(align=True)
        row.scale_y = 1.5
        for mode, label, _description in MODE_ITEMS:
            op = row.operator("import_scene.schematic_run", text=label)
            op.filepath = self.filepath
            op.mode = mode
        col.separator()
        col.label(text="Join: una mesh sola, vertici sovrapposti saldati", icon="INFO")

    def execute(self, context):
        return {"CANCELLED"}


class SCHEMATIC_OT_run(Operator):
    """Importa i blocchi mostrando l'avanzamento"""

    bl_idname = "import_scene.schematic_run"
    bl_label = "Import Schematic"

    filepath: StringProperty(subtype="FILE_PATH")
    mode: EnumProperty(items=MODE_ITEMS, default="INSTANCE")

    _blockManager = BlockManager()

    def _setup(self, context):
        self._job = None
        path = compat.assets_path()
        if path:  # modelli e texture di Minecraft dal client.jar / resource pack
            self._setup_models(context, path)
            return
        (self._blocks, self._data, self._width, self._length,
         self._unknown) = _read_schematic(self.filepath)
        self._missing = {}  # nome -> quanti blocchi moderni senza modello
        self._index = 0
        blocks = fastjoin.int_array(self._blocks)
        self._count = int(np.count_nonzero(blocks))
        if self.mode == "JOIN":
            # un esemplare per ogni (id, metadata), poi una mesh sola (fastjoin)
            filled = np.flatnonzero(blocks)
            keys = blocks[filled] * _KEY + (fastjoin.int_array(self._data)[filled] & (_KEY - 1))
            self._join_keys, inverse = np.unique(keys, return_inverse=True)
            cells = fastjoin.cells(filled, self._width, self._length)
            order = np.argsort(inverse, kind="stable")
            bounds = np.searchsorted(inverse[order], np.arange(len(self._join_keys) + 1))
            self._join_cells = {int(k): cells[order[bounds[i]:bounds[i + 1]]]
                                for i, k in enumerate(self._join_keys)}
            self._templates, self._separate = {}, []
            self._total = len(self._join_keys)
        else:
            self._total = len(self._blocks)
        _prepare_scene(context.scene)

    def _setup_models(self, context, path):
        try:
            assets = mcassets.Assets([path])
        except (IOError, OSError) as error:
            raise IOError("Minecraft Assets nelle preferenze: %s" % error)
        if not assets.has_blockstates():
            assets.close()
            raise IOError("Minecraft Assets nelle preferenze: niente modelli dei blocchi in %s" % path)
        palette, indices, width, length, legacy = _read_states(self.filepath)
        self._job = mcimport.Job(assets, palette, indices, width, length, legacy)
        self._count, self._index, self._missing = self._job.count, 0, {}
        self._total = self._job.steps() + (math.ceil(self._count / _CHUNK) if self.mode == "INSTANCE" else 0)
        self._run = self._job_steps(context)
        self._meshes = []
        _prepare_scene(context.scene)

    def _job_steps(self, context):
        yield from self._job.run()
        if self.mode != "INSTANCE":
            return
        name = os.path.splitext(os.path.basename(self.filepath))[0]
        collection = bpy.data.collections.new(name)
        context.collection.children.link(collection)
        made = 0
        for key, cells in self._job.cells.items():
            t = self._job.templates[key]
            if not t.corners or not len(cells):
                continue
            mesh = mcimport.template_mesh(t, self._job.materials)
            self._meshes.append(mesh)
            short = t.name.split(":", 1)[-1]
            for x, y, z in cells.tolist():
                ob = bpy.data.objects.new(short, mesh)
                ob.location = (x, y, z)
                ob["mc_state"] = t.state
                collection.objects.link(ob)
                made += 1
                if made % _CHUNK == 0:
                    yield

    def _make(self, x, y, z, block_id, metadata):
        if block_id < 0:  # blocco moderno (.schem) senza equivalente: cubo magenta col suo nome
            name = self._unknown[block_id]
            Unknown(0, 0, "Unknown " + name.replace("minecraft:", "")).make(x, y, z, 0)
        else:
            self._blockManager.draw(None, x, y, z, block_id, metadata)

    def _place(self, index, block_id):
        width, length = self._width, self._length
        x = index % width - math.floor(width / 2)
        y = length - math.floor((index % (width * length)) / width) - math.ceil(length / 2) - 1
        z = math.floor(index / (width * length))
        if block_id < 0:
            name = self._unknown[block_id]
            self._missing[name] = self._missing.get(name, 0) + 1
        self._make(x, y, z, block_id, self._data[index])

    def _template(self, key):
        """Crea un esemplare del blocco, ne copia la mesh e lo elimina."""
        block_id, metadata = key // _KEY, key % _KEY
        if block_id < 0:
            name = self._unknown[block_id]
            self._missing[name] = self._missing.get(name, 0) + len(self._join_cells[key])
        before = set(bpy.data.objects)
        self._make(0, 0, 0, block_id, metadata)
        for ob in [ob for ob in bpy.data.objects if ob not in before]:
            if fastjoin.separate_reason(ob) is None and key not in self._templates:
                self._templates[key] = fastjoin.make_template(ob, (0.5, 0.5, 0.5))
            elif key not in self._templates:
                self._separate.append(key)  # resta un oggetto per blocco
            mesh = ob.data if ob.type == "MESH" else None
            bpy.data.objects.remove(ob)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)

    def _summary(self):
        text = "Importati %d blocchi (%s)" % (self._count, self.mode.lower())
        if self._job is not None:
            labels = {"unknown": "senza modello, in magenta", "entity": "non disegnati (entita')",
                      "entity_box": "approssimati con una scatola", "fluid": "fluidi a blocco pieno"}
            for note, names in sorted(self._job.report().items()):
                shown = ", ".join(sorted(names, key=names.get, reverse=True)[:4])
                more = " e altri %d" % (len(names) - 4) if len(names) > 4 else ""
                text += "; %s: %s%s" % (labels[note], shown, more)
            return text
        if self._missing:
            names = sorted(self._missing, key=self._missing.get, reverse=True)
            shown = ", ".join(n.replace("minecraft:", "") for n in names[:5])
            more = " e altri %d" % (len(names) - 5) if len(names) > 5 else ""
            text += "; %d tipi senza modello, in magenta: %s%s" % (len(names), shown, more)
        return text

    def _step(self, budget_seconds=None):
        """Avanza l'import; torna True quando ha finito.

        Instance: piazza i blocchi. Join: crea gli esemplari, uno per tipo.
        """
        deadline = None if budget_seconds is None else time.perf_counter() + budget_seconds
        if self._job is not None:
            for _ in self._run:
                self._index = min(self._index + 1, self._total - 1)
                if deadline is not None and time.perf_counter() >= deadline:
                    return False
            self._index = self._total
            return True
        while self._index < self._total:
            if self.mode == "JOIN":
                self._template(int(self._join_keys[self._index]))
            else:
                block_id = self._blocks[self._index]
                if block_id != 0:
                    self._place(self._index, block_id)
            self._index += 1
            if deadline is not None and time.perf_counter() >= deadline:
                break
        return self._index >= self._total

    def _finish(self, context):
        if self._job is not None:
            if self.mode == "JOIN":
                mesh = mcimport.build_join("Schematic", self._job.cells, self._job.templates,
                                           self._job.materials)
                joined = bpy.data.objects.new("Schematic", mesh)
                context.collection.objects.link(joined)
                context.view_layer.update()
                for ob in context.view_layer.objects:
                    ob.select_set(False)
                joined.select_set(True)
                context.view_layer.objects.active = joined
                self._meshes.append(mesh)
            # colori a tinta unita per le texture nuove (pannello Schematic nella vista 3D)
            colors.after_import(context.scene, self._job.materials.list, self._meshes)
            self._job.assets.close()
            return
        if self.mode != "JOIN":
            return
        mesh = fastjoin.build_mesh("Schematic", self._join_cells, self._templates)
        joined = bpy.data.objects.new("Schematic", mesh)
        context.collection.objects.link(joined)
        for key in self._separate:  # blocchi con dati sull'oggetto: restano separati
            for x, y, z in self._join_cells[key].tolist():
                self._make(x, y, z, key // _KEY, key % _KEY)
        context.view_layer.update()  # i nuovi oggetti entrano nel view layer
        for ob in context.view_layer.objects:  # come gli importer di Blender
            ob.select_set(False)
        joined.select_set(True)
        context.view_layer.objects.active = joined

    # --- interattivo: modal con percentuale ---

    def invoke(self, context, event):
        try:
            self._setup(context)
        except (IOError, KeyError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        window_manager = context.window_manager
        window_manager.progress_begin(0, 100)
        self._timer = window_manager.event_timer_add(_TICK_SECONDS, window=context.window)
        window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._cleanup(context)
            self.report({"WARNING"},
                        "Import annullato a %d blocchi su %d" % (self._index, self._total))
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}

        finished = self._step(_TICK_SECONDS)
        self._report_progress(context, done=finished)
        if not finished:
            return {"RUNNING_MODAL"}

        self._finish(context)
        self._cleanup(context)
        self.report({"INFO"}, self._summary())
        return {"FINISHED"}

    def _report_progress(self, context, done=False):
        percent = 100 if done else int(100 * self._index / max(self._total, 1))
        context.window_manager.progress_update(percent)
        context.workspace.status_text_set(
            None if done
            else "Schematics2Blender: %d%% (%d/%d %s)" % (
                percent, self._index, self._total,
                "tipi di blocco" if self.mode == "JOIN" else "blocchi"))

    def _cleanup(self, context):
        window_manager = context.window_manager
        window_manager.event_timer_remove(self._timer)
        window_manager.progress_end()
        context.workspace.status_text_set(None)

    # --- diretto, per script e test ---

    def execute(self, context):
        try:
            self._setup(context)
        except (IOError, KeyError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self._step()
        self._finish(context)
        self.report({"INFO"}, self._summary())
        return {"FINISHED"}


class SCHEMATIC_OT_open_textures(Operator):
    """Apre la cartella delle texture (la crea se serve)"""

    bl_idname = "import_scene.schematic_open_textures"
    bl_label = "Open Texture Folder"

    def execute(self, context):
        path = compat.user_texture_dir(create=True) or compat.texture_dir()
        os.makedirs(path, exist_ok=True)
        bpy.ops.wm.path_open(filepath=path)
        return {"FINISHED"}


class SCHEMATIC_AP_preferences(AddonPreferences):
    bl_idname = __package__

    assets_path: StringProperty(
        name="Minecraft Assets", subtype="FILE_PATH",
        description="client.jar di Minecraft (.minecraft/versions/<versione>/<versione>.jar), "
                    "un resource pack .zip o una cartella con assets/: modelli e texture "
                    "di tutti i blocchi di quella versione. Vuoto: i modelli dell'addon (1.12)")
    texture_dir: StringProperty(
        name="Texture Folder", subtype="DIR_PATH",
        description="Cartella con le texture dei blocchi (nomi 1.12, es. stone.png). "
                    "Vuota: la cartella texture dell'utente, che resta dopo gli aggiornamenti")

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.prop(self, "assets_path")
        status = compat.assets_status(self.assets_path)
        box.label(text=status[0], icon=status[1])
        layout.label(text="Senza Minecraft Assets: modelli dell'addon (1.12) e queste texture:")
        layout.prop(self, "texture_dir")
        used = compat.texture_dir()
        count = (sum(1 for n in os.listdir(used) if n.lower().endswith(".png"))
                 if os.path.isdir(used) else 0)
        col = layout.column(align=True)
        col.label(text="In uso: " + used, icon="TEXTURE")
        col.label(text="%d texture trovate" % count if count else
                  "Nessuna texture: i blocchi saranno magenta", icon="INFO")
        layout.operator(SCHEMATIC_OT_open_textures.bl_idname, icon="FILE_FOLDER")


_CLASSES = (SCHEMATIC_AP_preferences, SCHEMATIC_OT_open_textures,
            SCHEMATIC_OT_import, SCHEMATIC_OT_mode, SCHEMATIC_OT_run)


def import_images_button(self, context):
    self.layout.operator(SCHEMATIC_OT_import.bl_idname, text="Minecraft Schematic (.schematic, .schem)")


def register():
    # prima venivano creati a ogni import e mai rimossi
    bpy.types.Object.blockId = bpy.props.IntProperty(
        name="Block ID", description="Stores the id of this object's block", default=0)
    bpy.types.Object.blockMetadata = bpy.props.IntProperty(
        name="Block Metadata", description="Stores the metadata of this object's block", default=0)
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    colors.register()
    bpy.types.TOPBAR_MT_file_import.append(import_images_button)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(import_images_button)
    colors.unregister()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Object.blockId
    del bpy.types.Object.blockMetadata


if __name__ == "__main__":
    register()
