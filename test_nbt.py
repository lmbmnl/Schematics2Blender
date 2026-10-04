"""Controllo del lettore NBT: python test_nbt.py (non serve Blender)."""

import gzip
import struct
import sys
import types

# importa nbt/nbt.py senza passare per il package dell'addon (che importa bpy)
sys.path.insert(0, "nbt")
import nbt as nbt_module  # noqa: E402


def _name(text):
    raw = text.encode()
    return struct.pack(">H", len(raw)) + raw


def _sample(compress=True):
    out = b"\x0a" + _name("Schematic")
    out += b"\x02" + _name("Width") + struct.pack(">h", 3)
    out += b"\x02" + _name("Height") + struct.pack(">h", 2)
    out += b"\x02" + _name("Length") + struct.pack(">h", 1)
    out += b"\x08" + _name("Materials") + _name("Alpha")
    # 155 e' oltre 127: deve restare senza segno, altrimenti gli id dei blocchi
    # alti (quartz, ecc.) diventano negativi e nessun blocco corrisponde
    out += b"\x07" + _name("Blocks") + struct.pack(">i", 6) + bytes(bytearray([1, 2, 3, 155, 0, 17]))
    out += b"\x07" + _name("Data") + struct.pack(">i", 6) + bytes(bytearray([0, 1, 2, 3, 4, 5]))
    out += b"\x01" + _name("Signed") + struct.pack(">b", -7)
    out += b"\x03" + _name("Count") + struct.pack(">i", 70000)
    out += b"\x06" + _name("Ratio") + struct.pack(">d", 0.25)
    out += b"\x0b" + _name("Ints") + struct.pack(">i", 2) + struct.pack(">ii", -1, 2)
    out += b"\x09" + _name("Entities") + b"\x0a" + struct.pack(">i", 0)
    out += b"\x00"
    return gzip.compress(out) if compress else out


def main():
    for compress in (True, False):
        buffer = types.SimpleNamespace(read=lambda data=_sample(compress): data)
        schematic = nbt_module.NBTFile(buffer=buffer)

        assert schematic.name == "Schematic", schematic.name
        assert schematic["Width"].value == 3
        assert schematic["Height"].value == 2
        assert schematic["Length"].value == 1
        assert schematic["Materials"].value == "Alpha"
        assert list(schematic["Blocks"].value) == [1, 2, 3, 155, 0, 17], list(schematic["Blocks"].value)
        assert schematic["Data"][3] == 3
        assert schematic["Signed"].value == -7
        assert schematic["Count"].value == 70000
        assert schematic["Ratio"].value == 0.25
        assert schematic["Ints"].value == [-1, 2]
        assert len(schematic["Entities"].value) == 0
        assert "Blocks" in schematic

    truncated = types.SimpleNamespace(read=lambda: _sample()[:20])
    try:
        nbt_module.NBTFile(buffer=truncated)
    except (IOError, OSError):
        pass
    else:
        raise AssertionError("un file troncato deve dare errore")

    print("test_nbt: ok")


if __name__ == "__main__":
    main()
