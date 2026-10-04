"""Lettore dei file Sponge Schematic (.schem, versioni 1, 2 e 3).

Sono i file salvati da WorldEdit dalla 1.13 in poi. Al posto degli id numerici
hanno una palette di stati moderni ("minecraft:oak_stairs[facing=east,...]"):
qui vengono convertiti negli id e metadata legacy che i blocchi dell'addon
conoscono, cosi' il resto dell'import resta quello del .schematic.

Specifica: https://github.com/SpongePowered/Schematic-Specification
Niente bpy qui dentro: si testa anche fuori da Blender (test_schem.py).
"""

from .legacy_blocks import LEGACY
from .nbt.nbt import TAG_BYTE_ARRAY, TAG_COMPOUND

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}

# nomi cambiati dopo la 1.13, che la tabella legacy non conosce
RENAMED = {
    "minecraft:short_grass": "minecraft:grass",  # 1.20.3
    # 1.14: la vecchia "stone_slab" (pietra liscia) e' diventata smooth_stone_slab;
    # la nuova stone_slab non ha un equivalente legacy e usa la stessa
    "minecraft:smooth_stone_slab": "minecraft:stone_slab",
    "minecraft:dirt_path": "minecraft:grass_path",  # 1.17
}

# stati moderni assenti dalla tabella ma con un blocco dell'addon
EXTRA = {
    "minecraft:pumpkin": (86, 4),  # zucca senza faccia (86:4 nell'addon)
}


def is_sponge(root):
    """True se l'NBT e' uno Sponge Schematic e non un .schematic MCEdit."""
    if "Schematic" in root and root["Schematic"].id == TAG_COMPOUND:
        return True  # v3: tutto dentro il compound "Schematic"
    if "Palette" in root or "BlockData" in root:
        return True  # v1 / v2
    return "Blocks" in root and root["Blocks"].id != TAG_BYTE_ARRAY


def parse_state(state):
    """"minecraft:oak_log[axis=x]" -> ("minecraft:oak_log", {"axis": "x"})."""
    name, _, rest = state.strip().partition("[")
    if ":" not in name:
        name = "minecraft:" + name  # il dominio minecraft: e' implicito
    props = {}
    for pair in rest.rstrip("]").split(","):
        if "=" in pair:
            key, _, value = pair.partition("=")
            props[key.strip()] = value.strip()
    return name, props


def legacy_of(state):
    """Stato moderno -> (id, metadata) legacy, o None se non ha equivalente.

    Tra gli stati legacy con lo stesso nome vince quello con piu' proprieta'
    uguali (facing, half, type, axis...); le proprieta' che il legacy non
    aveva (waterlogged, shape delle scale...) non contano.
    """
    name, props = parse_state(state)
    if name in AIR:
        return 0, 0
    name = RENAMED.get(name, name)
    if name in EXTRA:
        return EXTRA[name]
    best = None
    for block_id, metadata, legacy_props in LEGACY.get(name, ()):
        score = sum(1 for key, value in legacy_props if props.get(key) == value)
        if best is None or score > best[0]:
            best = (score, block_id, metadata)
    return None if best is None else best[1:]


def read_varints(raw, count):
    """Array di varint (7 bit per byte, bit alto = continua) -> lista di int."""
    if not raw:
        values = []
    elif max(raw) < 0x80:  # palette sotto i 128 stati: un byte per blocco
        values = list(raw)
    else:
        values, value, shift = [], 0, 0
        for byte in raw:
            value |= (byte & 0x7F) << shift
            if byte & 0x80:
                shift += 7
                if shift > 28:
                    raise IOError("file .schem corrotto: varint troppo lungo")
            else:
                values.append(value)
                value, shift = 0, 0
        if shift:
            raise IOError("file .schem corrotto: varint troncato")
    if len(values) != count:
        raise IOError("file .schem corrotto: %d blocchi invece di %d" % (len(values), count))
    return values


def _field(compound, key):
    if key not in compound:
        raise IOError("file .schem non valido: manca il campo %s" % key)
    return compound[key]


def read_schem_states(root):
    """NBT di uno Sponge Schematic -> (indici, palette, width, length).

    indici[i] e' la posizione nella palette dello stato del blocco i
    (x + z * width + y * width * length); palette[n] e' lo stato moderno.
    """
    schematic = root["Schematic"] if "Schematic" in root and root["Schematic"].id == TAG_COMPOUND else root
    version = schematic["Version"].value if "Version" in schematic else 1
    # "unsigned short": salvati come short con segno
    width, height, length = (_field(schematic, key).value & 0xFFFF
                             for key in ("Width", "Height", "Length"))
    total = width * height * length
    if version >= 3:
        if "Blocks" not in schematic:  # lo schematic puo' non avere blocchi
            return [0] * total, ["minecraft:air"], width, length
        container = schematic["Blocks"]
        palette, raw = _field(container, "Palette"), _field(container, "Data").value
    else:
        palette, raw = _field(schematic, "Palette"), _field(schematic, "BlockData").value
    states = {}
    for state, tag in palette.value.items():
        states[tag.value] = state
    size = max(states) + 1 if states else 1
    by_index = [states.get(i, "minecraft:air") for i in range(size)]
    indices = read_varints(raw, total)
    if indices and max(indices) >= size:
        raise IOError("file .schem corrotto: indice %d fuori dalla palette" % max(indices))
    return indices, by_index, width, length


def is_structure(root):
    """True se l'NBT e' un file .nbt dei blocchi struttura (structure block)."""
    return "size" in root and "blocks" in root and ("palette" in root or "palettes" in root)


def read_structure_states(root):
    """NBT di un file .nbt dei blocchi struttura -> (indici, palette, width, length).

    Formato: size [x, y, z], palette [{Name, Properties}] ({id, properties}
    dalla 26.3; palettes: piu' palette alternative, si usa la prima) e
    blocks [{state, pos [x, y, z]}].
    Le celle senza blocco (structure void) restano vuote; i dati dei blocchi
    (contenuto dei bauli...) e le entita' non vengono letti.
    https://minecraft.wiki/w/Structure_file
    """
    size = [tag.value for tag in root["size"].value]
    if len(size) != 3 or min(size) < 0:
        raise IOError("file .nbt non valido: size %s" % size)
    width, height, length = size
    if "palette" in root:
        entries = root["palette"].value
    elif root["palettes"].value:
        entries = root["palettes"].value[0].value
    else:
        raise IOError("file .nbt non valido: palettes vuoto")
    palette = []
    for entry in entries:
        # fino alla 26.2: Name / Properties; dalla 26.3: id / properties
        name_key = "Name" if "Name" in entry else "id"
        props_key = "Properties" if "Properties" in entry else "properties"
        if name_key not in entry:
            raise IOError("file .nbt non valido: stato senza Name / id")
        state = entry[name_key].value
        props = entry[props_key].value if props_key in entry else {}
        if props:
            state += "[%s]" % ",".join("%s=%s" % (k, v.value) for k, v in sorted(props.items()))
        palette.append(state)
    void = len(palette)
    palette.append("minecraft:air")  # celle senza blocco nel file
    indices = [void] * (width * height * length)
    for block in root["blocks"].value:
        state = block["state"].value
        x, y, z = (tag.value for tag in block["pos"].value)
        if not (0 <= x < width and 0 <= y < height and 0 <= z < length):
            raise IOError("file .nbt corrotto: blocco fuori da size in %s" % ((x, y, z),))
        if not 0 <= state < void:
            raise IOError("file .nbt corrotto: stato %d fuori dalla palette" % state)
        indices[x + z * width + y * width * length] = state
    return indices, palette, width, length


def read_structure(root):
    """Come read_schem, per i file .nbt dei blocchi struttura."""
    return _legacy_arrays(*read_structure_states(root))


def read_schem(root):
    """NBT di uno Sponge Schematic -> (blocks, data, width, length, unknown).

    blocks e data sono liste indicizzate come nel .schematic
    (x + z * width + y * width * length). Gli stati senza equivalente legacy
    hanno id negativi: unknown[id] e' il loro nome.
    """
    return _legacy_arrays(*read_schem_states(root))


def _legacy_arrays(indices, palette, width, length):
    """Indici di palette di stati moderni -> id e metadata 1.12 (vedi read_schem)."""
    unknown, codes = {}, {}
    ids, metas = [], []
    for state in palette:
        legacy = legacy_of(state)
        if legacy is None:
            name = parse_state(state)[0]
            if name not in codes:
                codes[name] = -1 - len(codes)
                unknown[codes[name]] = name
            legacy = (codes[name], 0)
        ids.append(legacy[0])
        metas.append(legacy[1])
    blocks = [ids[i] for i in indices]
    data = [metas[i] for i in indices]
    return blocks, data, width, length, unknown


_LEGACY_STATE = {}


def state_of_legacy(block_id, metadata):
    """Id e metadata della 1.12 -> stato moderno ("minecraft:oak_log[axis=x]"), o None.

    La tabella mette shape=outer_right su tutte le scale (nella 1.12 la forma
    non era salvata): si toglie e vale il default, scala dritta.
    """
    if not _LEGACY_STATE:
        for name, entries in LEGACY.items():
            for bid, meta, props in entries:
                if (bid, meta) not in _LEGACY_STATE:
                    props = [(k, v) for k, v in props if not (k == "shape" and name.endswith("_stairs"))]
                    _LEGACY_STATE[(bid, meta)] = (
                        name + ("[%s]" % ",".join("%s=%s" % kv for kv in props) if props else ""))
    return _LEGACY_STATE.get((block_id, metadata)) or _LEGACY_STATE.get((block_id, 0))
