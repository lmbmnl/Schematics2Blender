"""Controllo del lettore .schem: python test_schem.py (non serve Blender)."""

import gzip
import importlib
import os
import struct
import sys
import types

# importa schem.py come parte del package senza eseguire __init__.py (che importa bpy)
HERE = os.path.dirname(os.path.abspath(__file__))
package = types.ModuleType("s2b_pure")
package.__path__ = [HERE]
sys.modules["s2b_pure"] = package
schem = importlib.import_module("s2b_pure.schem")
nbt = importlib.import_module("s2b_pure.nbt.nbt")


# --- scrittore NBT minimo, solo per costruire i file di prova
def _name(text):
    raw = text.encode()
    return struct.pack(">H", len(raw)) + raw


def _short(name, v):
    return b"\x02" + _name(name) + struct.pack(">h", v)


def _int(name, v):
    return b"\x03" + _name(name) + struct.pack(">i", v)


def _bytes(name, raw):
    return b"\x07" + _name(name) + struct.pack(">i", len(raw)) + bytes(raw)


def _compound(name, body):
    return b"\x0a" + _name(name) + body + b"\x00"


def _varints(values):
    out = bytearray()
    for v in values:
        while True:
            byte = v & 0x7F
            v >>= 7
            out.append(byte | (0x80 if v else 0))
            if not v:
                break
    return out


def _palette(states):
    return b"".join(_int(s, i) for i, s in enumerate(states))


def sponge(states, indices, w, h, l, version=2):
    size = _short("Width", w) + _short("Height", h) + _short("Length", l)
    if version >= 3:
        blocks = _compound("Palette", _palette(states)) + _bytes("Data", _varints(indices))
        body = _int("Version", 3) + _int("DataVersion", 3700) + size + _compound("Blocks", blocks)
        return gzip.compress(_compound("", _compound("Schematic", body)))
    body = (_int("Version", version) + _int("DataVersion", 2586) + size
            + _int("PaletteMax", len(states)) + _compound("Palette", _palette(states))
            + _bytes("BlockData", _varints(indices)))
    return gzip.compress(_compound("Schematic", body))


def load(data):
    return nbt.NBTFile(buffer=types.SimpleNamespace(read=lambda: data))


def main():
    # stati moderni -> id/metadata legacy (tabella di minecraft-data)
    L = schem.legacy_of
    assert L("minecraft:stone") == (1, 0) and L("stone") == (1, 0)
    assert L("minecraft:air") == L("minecraft:cave_air") == (0, 0)
    assert L("minecraft:oak_log[axis=x]") == (17, 4) and L("minecraft:oak_log[axis=z]") == (17, 8)
    assert L("minecraft:oak_wood[axis=y]") == (17, 12)
    assert L("minecraft:oak_stairs[facing=west,half=top,shape=straight,waterlogged=false]") == (53, 5)
    assert L("minecraft:oak_stairs[facing=north,half=bottom,shape=inner_left,waterlogged=true]") == (53, 3)
    assert L("minecraft:stone_slab[type=top,waterlogged=false]") == (44, 8)
    assert L("minecraft:smooth_stone_slab[type=double]") == (43, 0)  # nome 1.14
    assert L("minecraft:oak_slab[type=bottom]") == (126, 0)
    assert L("minecraft:carved_pumpkin[facing=east]") == (86, 3)
    assert L("minecraft:pumpkin") == (86, 4)
    assert L("minecraft:farmland[moisture=7]") == (60, 7)
    assert L("minecraft:short_grass") == L("minecraft:grass") == (31, 1)  # nome 1.20.3
    assert L("minecraft:white_wool") == (35, 0) and L("minecraft:black_wool") == (35, 15)
    assert L("minecraft:redstone_ore[lit=true]") == (74, 0) and L("minecraft:redstone_ore[lit=false]") == (73, 0)
    assert L("minecraft:copper_block") is None  # 1.17: niente equivalente legacy
    assert L("somemod:machine[on=true]") is None

    # varint: un byte sotto 128, piu' byte sopra
    assert schem.read_varints(bytearray([1, 2, 3]), 3) == [1, 2, 3]
    assert schem.read_varints(_varints([300, 0, 128, 2 ** 31 - 1]), 4) == [300, 0, 128, 2 ** 31 - 1]
    for bad, count in ((bytearray([0x80]), 1), (bytearray([1, 2]), 3), (bytearray([0xFF] * 6), 1)):
        try:
            schem.read_varints(bad, count)
            raise AssertionError("varint non valido accettato: %r" % bad)
        except IOError:
            pass

    # v2 e v3: stessi blocchi, stesso risultato
    states = ["minecraft:air", "minecraft:stone", "minecraft:oak_log[axis=x]",
              "minecraft:copper_block", "minecraft:oak_stairs[facing=south,half=bottom,shape=straight]"]
    w, h, l = 3, 2, 2  # indice = x + z * w + y * w * l
    indices = [1, 2, 0, 3, 4, 1,
               0, 0, 1, 3, 3, 2]
    for version in (1, 2, 3):
        root = load(sponge(states, indices, w, h, l, version))
        assert schem.is_sponge(root), version
        blocks, data, width, length, unknown = schem.read_schem(root)
        assert (width, length) == (3, 2)
        assert unknown == {-1: "minecraft:copper_block"}
        assert blocks == [1, 17, 0, -1, 53, 1, 0, 0, 1, -1, -1, 17], (version, blocks)
        assert data == [0, 4, 0, 0, 2, 0, 0, 0, 0, 0, 0, 4], (version, data)

    # palette oltre 127 stati: indici varint su due byte
    many = ["minecraft:air"] + ["testmod:block_%d" % i for i in range(200)]  # stati tutti diversi
    many += ["minecraft:stone", "minecraft:red_wool"]
    idx = [201, 202, 0, 1, 200, 201]
    blocks, data, _w, _l, unknown = schem.read_schem(load(sponge(many, idx, 6, 1, 1)))
    assert blocks[:3] == [1, 35, 0] and data[:3] == [0, 14, 0], (blocks, data)
    assert unknown[blocks[3]] == "testmod:block_0" and unknown[blocks[4]] == "testmod:block_199"
    assert blocks[5] == 1 and len(unknown) == 200

    # Width oltre 32767: "unsigned short" salvato con segno
    big = gzip.compress(_compound("Schematic", _int("Version", 2) + _short("Width", -32768)
                                  + _short("Height", 0) + _short("Length", 1)
                                  + _compound("Palette", _palette(["minecraft:air"]))
                                  + _bytes("BlockData", b"")))
    assert schem.read_schem(load(big))[2] == 32768

    # un .schematic MCEdit non e' scambiato per Sponge
    legacy = gzip.compress(_compound("Schematic", _short("Width", 1) + _short("Height", 1)
                                     + _short("Length", 1) + _bytes("Blocks", [1]) + _bytes("Data", [0])))
    assert not schem.is_sponge(load(legacy))

    # file rotti: errori leggibili, non traceback
    broken = [
        sponge(states, indices[:-1], w, h, l),            # un blocco in meno
        sponge(states, indices[:-1] + [9], w, h, l),      # indice fuori palette
        gzip.compress(_compound("Schematic", _int("Version", 2) + _short("Width", 1))),  # campi mancanti
    ]
    for data in broken:
        try:
            schem.read_schem(load(data))
            raise AssertionError("file rotto accettato")
        except IOError:
            pass

    print("test_schem: ok")


if __name__ == "__main__":
    main()
