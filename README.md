# Schematics2Blender
A Blender add-on (4.2 or newer) that imports Minecraft schematics as blocks with
their textures, made with animators in mind: every block can be its own object.

## Supported files
- `.schematic`: MCEdit / WorldEdit up to Minecraft 1.12 (numeric block ids).
- `.schem`: Sponge Schematic v1, v2 and v3, saved by WorldEdit from Minecraft 1.13 on.
  Modern block states are converted to the 1.12 blocks the add-on models; blocks with
  no equivalent are imported as magenta cubes named after the block and listed at
  the end of the import.

The format is detected from the file contents. `.litematic` files are not supported.

## Install
Blender > Edit > Preferences > Get Extensions > the arrow menu at the top right >
**Install from Disk...** and pick the zip. Then **File > Import > Minecraft Schematic**.

Two import modes:
- **Instance**: one object per block.
- **Join**: one mesh for the whole schematic; faces hidden between touching blocks
  are left out.

## Textures
Minecraft's block textures belong to Mojang and are not included. The add-on
reads PNG files with the 1.12 names (`stone.png`, `log_oak.png`, ...) from, in order:
1. the **Texture Folder** chosen in the add-on preferences;
2. its user texture folder, which survives updates and reinstalls
   (preferences > **Open Texture Folder**), on Windows
   `%APPDATA%\Blender Foundation\Blender\<version>\extensions\.user\user_default\schematics2blender\textures\`;
3. `textures/blocks/` inside the add-on folder (cleared by every update).

In a folder the textures can also sit in `blocks/`, `textures/blocks/` or
`assets/minecraft/textures/blocks/` (a 1.8-1.12 resource pack). Missing textures
show up as magenta.

## Tests
```
python test_nbt.py
python test_schem.py
blender -b --factory-startup --python test_import.py
```

## Credits and license
Based on [MCEdit2Blender](https://github.com/ConnorKrammer/MCEdit2Blender) by
ConnorKrammer and contributors, released under the GPL-3.0; this add-on is
GPL-3.0-or-later as well (see `LICENSE`).
Block state conversion table (`legacy_blocks.py`) generated from
[PrismarineJS/minecraft-data](https://github.com/PrismarineJS/minecraft-data) (MIT).
Minecraft is a trademark of Mojang; its textures are not part of this project.
