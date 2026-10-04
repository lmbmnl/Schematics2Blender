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


def read_schem(root):
    """NBT di uno Sponge Schematic -> (blocks, data, width, length, unknown).

    blocks e data sono liste indicizzate come nel .schematic
    (x + z * width + y * width * length). Gli stati senza equivalente legacy
    hanno id negativi: unknown[id] e' il loro nome.
    """
    schematic = root["Schematic"] if "Schematic" in root and root["Schematic"].id == TAG_COMPOUND else root
    version = schematic["Version"].value if "Version" in schematic else 1
    # "unsigned short": salvati come short con segno
    width, height, length = (_field(schematic, key).value & 0xFFFF
                             for key in ("Width", "Height", "Length"))
    total = width * height * length
    if version >= 3:
        if "Blocks" not in schematic:  # lo schematic puo' non avere blocchi
            return [0] * total, [0] * total, width, length, {}
        container = schematic["Blocks"]
        palette, raw = _field(container, "Palette"), _field(container, "Data").value
    else:
        palette, raw = _field(schematic, "Palette"), _field(schematic, "BlockData").value

    unknown, codes = {}, {}
    ids, metas = {}, {}
    for state, tag in palette.value.items():
        legacy = legacy_of(state)
        if legacy is None:
            name = parse_state(state)[0]
            if name not in codes:
                codes[name] = -1 - len(codes)
                unknown[codes[name]] = name
            legacy = (codes[name], 0)
        ids[tag.value], metas[tag.value] = legacy

    indices = read_varints(raw, total)
    try:
        blocks = [ids[i] for i in indices]
        data = [metas[i] for i in indices]
    except KeyError as error:
        raise IOError("file .schem corrotto: indice %s fuori dalla palette" % error)
    return blocks, data, width, length, unknown
