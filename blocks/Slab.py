import bpy

from ..compat import fix_normals
import mathutils
from .Block import Block

class Slab(Block):
    """Slab block with a single texture"""
    
    def makeObject(self, x, y, z, metadata):
        """
        py:function:: makeObject(self)
        
        Make a new block and returns its object.
        
        Return type: <class 'bpy_types.Object'>
        """
        mesh = bpy.data.meshes.new(name="Block")
        mesh.from_pydata([[-0.5,-0.5,-0.25],[0.5,-0.5,-0.25],[-0.5,0.5,-0.25],[0.5,0.5,-0.25],[-0.5,-0.5,0.25],[0.5,-0.5,0.25],[-0.5,0.5,0.25],[0.5,0.5,0.25]],[],[[0,1,3,2],[4,5,7,6],[0,1,5,4],[0,2,6,4],[2,3,7,6],[1,3,7,5]])
        mesh.update()
        
        obj = bpy.data.objects.new("Block", mesh)
        obj.location.x = x + 0.5
        obj.location.y = y + 0.5
        obj.location.z = z + 0.25 + 0.5 * (metadata >> 3 & 1)
        obj.blockId = self._id
        obj.blockMetadata = metadata
        bpy.context.collection.objects.link(obj)
        
        fix_normals(mesh)
        
        return obj
    
    def makeUVMap(self, obj, metadata):
        obj.data.uv_layers.new();
        if metadata & 8:
            obj.data.uv_layers[0].data.foreach_set("uv", [0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0.5, 1, 0.5, 1, 1, 0, 1, 1, 0.5, 1, 1, 0, 1, 0, 0.5, 0, 0.5, 0, 1, 1, 1, 1, 0.5, 1, 0.5, 0, 0.5, 0, 1, 1, 1])
        else:
            obj.data.uv_layers[0].data.foreach_set("uv", [0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 0.5, 0, 0.5, 1, 0, 1, 0.5, 0, 0.5, 0, 0, 0, 0, 0, 0.5, 1, 0.5, 1, 0, 1, 0, 0, 0, 0, 0.5, 1, 0.5])