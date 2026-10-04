"""Lettore NBT minimale, sostituisce il submodule twoolie/NBT mancante.

Espone solo quello che l'addon usa: NBTFile(path, 'rb'), accesso per chiave,
.value sui tag e indicizzazione dei byte array.
"""

import gzip
import struct

TAG_END, TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG, TAG_FLOAT, TAG_DOUBLE = range(7)
TAG_BYTE_ARRAY, TAG_STRING, TAG_LIST, TAG_COMPOUND = 7, 8, 9, 10
TAG_INT_ARRAY, TAG_LONG_ARRAY = 11, 12

_FMT = {
    TAG_BYTE: ">b", TAG_SHORT: ">h", TAG_INT: ">i", TAG_LONG: ">q",
    TAG_FLOAT: ">f", TAG_DOUBLE: ">d",
}


class Tag:
    """Un tag NBT. value e' il valore nativo; compound e list sono indicizzabili."""

    def __init__(self, tag_id, name, value):
        self.id = tag_id
        self.name = name
        self.value = value

    def __getitem__(self, key):
        return self.value[key]

    def __iter__(self):
        return iter(self.value)

    def __len__(self):
        return len(self.value)

    def __contains__(self, key):
        return key in self.value

    def keys(self):
        return self.value.keys()

    def __repr__(self):
        return "Tag(id=%d, name=%r)" % (self.id, self.name)


class _Reader:
    def __init__(self, data):
        self.d = data
        self.i = 0

    def take(self, n):
        if self.i + n > len(self.d):
            raise IOError("file NBT troncato")
        chunk = self.d[self.i:self.i + n]
        self.i += n
        return chunk

    def scalar(self, tag_id):
        fmt = _FMT[tag_id]
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def string(self):
        (n,) = struct.unpack(">H", self.take(2))
        return self.take(n).decode("utf-8", "replace")

    def payload(self, tag_id):
        if tag_id in _FMT:
            return self.scalar(tag_id)
        if tag_id == TAG_BYTE_ARRAY:
            # bytearray: id dei blocchi senza segno (0-255), come twoolie/NBT
            (n,) = struct.unpack(">i", self.take(4))
            return bytearray(self.take(n))
        if tag_id == TAG_STRING:
            return self.string()
        if tag_id == TAG_LIST:
            (item_id,) = struct.unpack(">b", self.take(1))
            (n,) = struct.unpack(">i", self.take(4))
            return [Tag(item_id, "", self.payload(item_id)) for _ in range(n)]
        if tag_id == TAG_COMPOUND:
            out = {}
            while True:
                (child_id,) = struct.unpack(">b", self.take(1))
                if child_id == TAG_END:
                    return out
                name = self.string()
                out[name] = Tag(child_id, name, self.payload(child_id))
        if tag_id in (TAG_INT_ARRAY, TAG_LONG_ARRAY):
            width = 4 if tag_id == TAG_INT_ARRAY else 8
            (n,) = struct.unpack(">i", self.take(4))
            code = ">%d%s" % (n, "i" if width == 4 else "q")
            return list(struct.unpack(code, self.take(n * width)))
        raise IOError("tag NBT sconosciuto: %d" % tag_id)


class NBTFile(Tag):
    """Il compound radice di un file .schematic (gzip o non compresso)."""

    def __init__(self, filename=None, mode="rb", buffer=None):
        raw = buffer.read() if buffer is not None else open(filename, "rb").read()
        if raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except (OSError, EOFError) as error:
                # l'operatore mostra IOError all'utente, non una traceback
                raise IOError('file .schematic corrotto: %s' % error)
        r = _Reader(raw)
        (root_id,) = struct.unpack(">b", r.take(1))
        if root_id != TAG_COMPOUND:
            raise IOError("la radice non e' un TAG_Compound")
        name = r.string()
        Tag.__init__(self, TAG_COMPOUND, name, r.payload(TAG_COMPOUND))
