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

## Minecraft Assets (recommended)
Set **Minecraft Assets** in the add-on preferences to the `client.jar` of your
Minecraft version and the add-on uses Minecraft's own block models and textures,
read straight from the jar (nothing is copied out of it except the textures packed
into the .blend). Almost every vanilla block is then drawn as in the game: walls,
stairs, slabs, fences, plants, overlays (grass sides), tinted grass/leaves/water.
- Windows: `%APPDATA%\.minecraft\versions\<version>\<version>.jar`
  (e.g. `...\versions\1.20.1\1.20.1.jar`; start that version once in the launcher
  so the jar is downloaded). Use the same or a newer version than the schematic.
- A resource pack `.zip`, or a folder that contains `assets/`, also works if it
  has `assets/minecraft/blockstates`, `models` and `textures`.

Old `.schematic` files (1.12) are converted to modern block states; fence, wall,
pane and iron bar connections are rebuilt from the neighbouring blocks.

Known limits: water and lava are full blocks; signs, banners, heads and other block
entities are not drawn (chests, beds, shulker boxes and pots are plain boxes);
random variants use the first model; tints are the plains biome ones; stair shapes
of 1.12 files are not recomputed (straight); blocks from mods are magenta cubes.

### Texture colours panel
3D Viewport sidebar (N) > **Schematic** > **Colori delle texture**: every Minecraft
texture in the file gets a plain Principled BSDF material with the texture's average
colour (alpha-weighted, in linear space, times the biome tint). Click the swatch to
change the colour, type in the field to rename the material. **Usa colori** swaps the
textured materials for the plain ones (and back); transparent textures (flowers,
leaves, glass, torches) keep their shape through the texture's alpha. **Salva preset**
stores colours and names in `presets/texture_colors.json` in the add-on's user folder
(kept by updates); they are used by every later import, in any .blend file.
A material made of two textures (grass block side: dirt + overlay) uses the bottom one.
**Solo texture usate** (on by default) lists only the textures of materials on objects
of the current scene; turn it off to see every colour in the file.

With **Minecraft Assets** empty the add-on uses its own 1.12 models and the
texture folder below.

## Install
Blender > Edit > Preferences > Get Extensions > the arrow menu at the top right >
**Install from Disk...** and pick the zip. Then **File > Import > Minecraft Schematic**.

Four import modes:
- **Instance**: one object per block (with Minecraft Assets: in a collection named
  after the file, blocks of the same state share one mesh).
- **Join**: one mesh for the whole schematic; faces hidden between touching blocks
  are left out.
- **Join by Material**: the same faces as Join, one object per material (all the
  faces with the same texture in one mesh), in a collection named after the file.
  A block with several textures (grass block: top, side, dirt) ends up in several
  objects.
- **Join by Block**: one object per block type (every oak stair, in any direction,
  in `oak_stairs`; a crafting table with its materials in `crafting_table`), in a
  collection named after the file. Different blocks with the same texture (planks,
  stairs, slabs) are different objects sharing one material. Each object is closed:
  only faces between blocks of the same type are removed, so hiding one type leaves
  no holes in the others.

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
show up as magenta. These textures are only used when **Minecraft Assets** is empty.

## Tests
```
python test_nbt.py
python test_schem.py
blender -b --factory-startup --python test_import.py
blender -b --factory-startup --python test_models.py
```

## Credits and license
Based on [MCEdit2Blender](https://github.com/ConnorKrammer/MCEdit2Blender) by
ConnorKrammer and contributors, released under the GPL-3.0; this add-on is
GPL-3.0-or-later as well (see `LICENSE`).
Block state conversion table (`legacy_blocks.py`) generated from
[PrismarineJS/minecraft-data](https://github.com/PrismarineJS/minecraft-data) (MIT).
Minecraft is a trademark of Mojang; its textures are not part of this project.
