# MCEdit2Blender
A Blender addon to quickly import Minecraft worlds using MCEdit .schematic files.

## Information
 Here are a few things we do (or plan to do) that help distinguish us from other similar projects:
- No additional setup is required after importing a schematic to achieve the look and feel of Minecraft
- We are designed with animators in mind. Individual objects for each block, animated particle systems, and custom configuration for blocks like pistons and doors all to make it easier to animate.
- We do not rely on [Mineways](http://www.realtimerendering.com/erich/minecraft/public/mineways/) or [jMc2Obj](https://github.com/jmc2obj/j-mc-2-obj) to generate objects but instead do it ourselves which gives us greater control over the entire process.
- MCEdit schematic files are used instead of direct importing from a minecraft world. This is one of the most popular and well supported formats for saving parts of a map and have the advantage of being able to use various different tools to generate them. WorldEdit and MCEdit are both easy tools that can be used to select 3d regions to render.
- It is relatively simple for mods to extend our plugin to add support for their own blocks.
- Easily swap texture packs within Blender.

This project is still in very early beta. We currently only have support for about 40% of all of the vanilla minecraft blocks and we are still missing some very important features. We will not be providing instructions for installation and usage until the project has been developed a little bit more. The source code is all here however so if you want to try it out you still theoretically could. The [NBT](https://github.com/twoolie/NBT) library by twoolie and the block textures from minecraft are currently the only two dependencies.

## Contributing
We welcome contributions. If you have a feature you want to add, just make a branch, do your thing, and submit a pull request when you're ready. If you need something to do, check the issues page or the TODO file. If you any problems, feel free to open a new issue and someone should get back to you soon. More details on building and testing MCEdit2Blender will come soon.

## Supported files
- `.schematic`: MCEdit / WorldEdit up to Minecraft 1.12 (numeric block ids).
- `.schem`: Sponge Schematic v1, v2 and v3, saved by WorldEdit from Minecraft 1.13 on.
  Modern block states are converted to the legacy ids the blocks above understand;
  blocks with no equivalent are imported as magenta cubes named after the block
  and listed at the end of the import.

The format is detected from the file contents. `.litematic` files are not supported.

## Textures
Minecraft's block textures belong to Mojang and are not included. Put them in
`textures/blocks/` inside the installed add-on folder, e.g. on Windows
`%APPDATA%\Blender Foundation\Blender\<version>\extensions\user_default\mcedit2blender\textures\blocks\`.
Missing textures show up as magenta. Reinstalling or updating the add-on replaces
its folder, so the textures have to be copied again.

## Tests
```
python test_nbt.py
python test_schem.py
blender -b --factory-startup --python test_import.py
```

## Credits
Block state conversion table (`legacy_blocks.py`) generated from
[PrismarineJS/minecraft-data](https://github.com/PrismarineJS/minecraft-data) (MIT).
