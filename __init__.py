import math
import os
import time

import bmesh
import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from . import nbt
from .blockmanager import BlockManager

# ogni tick del modal lavora ~40ms e poi restituisce il controllo a Blender,
# cosi' la percentuale si aggiorna invece di bloccare la finestra
_TICK_SECONDS = 0.04

MODE_ITEMS = [
    ("INSTANCE", "Instance", "Un oggetto separato per ogni blocco"),
    ("JOIN", "Join", "Unisce tutti i blocchi in una mesh sola e salda i vertici sovrapposti"),
]


def _read_schematic(filepath):
    """Legge il .schematic e torna (blocks, data, width, length)."""
    if os.path.splitext(filepath)[1].lower() != ".schematic":
        raise IOError("Il file selezionato non e' un *.schematic")
    nbtfile = nbt.nbt.NBTFile(filepath, "rb")
    return (nbtfile["Blocks"].value, nbtfile["Data"],
            nbtfile["Width"].value, nbtfile["Length"].value)


def _prepare_scene():
    bpy.data.scenes[0].render.engine = "CYCLES"
    bpy.data.scenes[0].render.fps = 20
    bpy.data.scenes[0].render.fps_base = 1
    bpy.types.Object.blockId = bpy.props.IntProperty(
        name="Block ID", description="Stores the id of this object's block", default=0)
    bpy.types.Object.blockMetadata = bpy.props.IntProperty(
        name="Block Metadata", description="Stores the metadata of this object's block", default=0)


def join_blocks(context, objects, threshold=0.0001):
    """Unisce i blocchi in una mesh sola e salda i vertici coincidenti."""
    view_layer_objects = context.view_layer.objects
    meshes = [ob for ob in objects if ob.type == "MESH" and ob.name in view_layer_objects]
    if not meshes:
        return None
    view_layer_objects.active = meshes[0]
    if len(meshes) > 1:
        # temp_override: join() funziona anche chiamato da un timer modal,
        # dove il contesto non ha la selezione della viewport
        with context.temp_override(active_object=meshes[0], object=meshes[0],
                                   selected_objects=meshes,
                                   selected_editable_objects=meshes):
            bpy.ops.object.join()
    joined = meshes[0]

    # merge by distance con bmesh: non serve passare per la modalita' Edit,
    # che da un timer modal non e' sempre disponibile
    bm = bmesh.new()
    bm.from_mesh(joined.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=threshold)
    bm.to_mesh(joined.data)
    bm.free()
    joined.data.update()
    joined.name = "Schematic"
    return joined


class SCHEMATIC_OT_import(Operator, ImportHelper):
    """Importa uno schematic MCEdit"""

    bl_idname = "import_scene.schematic"
    bl_label = "Import Schematic"

    filename_ext = ".schematic"
    filter_glob: StringProperty(default="*.schematic", options={"HIDDEN"})

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
        self._blocks, self._data, self._width, self._length = _read_schematic(self.filepath)
        self._index = 0
        self._total = len(self._blocks)
        self._existing = {ob.name for ob in bpy.data.objects}
        _prepare_scene()

    def _place(self, index, block_id):
        width, length = self._width, self._length
        self._blockManager.draw(
            None,
            index % width - math.floor(width / 2),
            length - math.floor((index % (width * length)) / width) - math.ceil(length / 2) - 1,
            math.floor(index / (width * length)),
            block_id,
            self._data[index],
        )

    def _step(self, budget_seconds=None):
        """Piazza i blocchi successivi; torna True quando ha finito."""
        deadline = None if budget_seconds is None else time.perf_counter() + budget_seconds
        while self._index < self._total:
            block_id = self._blocks[self._index]
            if block_id != 0:
                self._place(self._index, block_id)
            self._index += 1
            if deadline is not None and time.perf_counter() >= deadline:
                break
        return self._index >= self._total

    def _new_objects(self):
        return [ob for ob in bpy.data.objects if ob.name not in self._existing]

    def _finish(self, context):
        if self.mode == "JOIN":
            join_blocks(context, self._new_objects())

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
        self.report({"INFO"}, "Importati %d blocchi (%s)" % (self._total, self.mode.lower()))
        return {"FINISHED"}

    def _report_progress(self, context, done=False):
        percent = 100 if done else int(100 * self._index / max(self._total, 1))
        context.window_manager.progress_update(percent)
        context.workspace.status_text_set(
            None if done
            else "MCEdit2Blender: %d%% (%d/%d blocchi)" % (percent, self._index, self._total))

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
        return {"FINISHED"}


_CLASSES = (SCHEMATIC_OT_import, SCHEMATIC_OT_mode, SCHEMATIC_OT_run)


def import_images_button(self, context):
    self.layout.operator(SCHEMATIC_OT_import.bl_idname, text="MCEdit Schematic (.schematic)")


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(import_images_button)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(import_images_button)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
