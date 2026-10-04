"""Lettura degli asset di Minecraft: client.jar, resource pack (.zip) o cartella.

Il client.jar e' uno zip con dentro assets/minecraft/...: blockstates, modelli
e texture dei blocchi. Niente viene copiato o ridistribuito, si legge al volo.
Niente bpy qui dentro.
"""

import json
import os
import zipfile


def split_location(location, default_ns="minecraft"):
    """"minecraft:block/stone" -> ("minecraft", "block/stone")."""
    if ":" in location:
        ns, _, path = location.partition(":")
        return ns, path
    return default_ns, location


class Assets:
    """Una o piu' sorgenti (la prima che ha il file vince: resource pack sopra il jar)."""

    def __init__(self, paths):
        self._sources = []
        # identifica la sorgente: immagini e materiali si riusano solo se uguale
        self.source = "|".join(os.path.abspath(p) for p in paths)
        for path in paths:
            self._sources.append(self._open(path))
        self._json = {}

    @staticmethod
    def _open(path):
        if os.path.isdir(path):
            return ("dir", path)  # cartella che contiene assets/ (resource pack estratto)
        if zipfile.is_zipfile(path):
            return ("zip", zipfile.ZipFile(path))
        raise IOError("Non e' un client.jar, un resource pack o una cartella: %s" % path)

    def close(self):
        for kind, src in self._sources:
            if kind == "zip":
                src.close()
        self._sources = []

    def read(self, relpath):
        """Byte del file assets/<relpath>, o None."""
        for kind, src in self._sources:
            if kind == "zip":
                try:
                    return src.read("assets/" + relpath)
                except KeyError:
                    continue
            else:
                full = os.path.join(src, "assets", *relpath.split("/"))
                if os.path.isfile(full):
                    with open(full, "rb") as f:
                        return f.read()
        return None

    def json(self, kind, location):
        """JSON di blockstates/ o models/ per una resource location, o None."""
        key = (kind, location)
        if key not in self._json:
            ns, path = split_location(location)
            raw = self.read("%s/%s/%s.json" % (ns, kind, path))
            self._json[key] = json.loads(raw.decode("utf-8")) if raw is not None else None
        return self._json[key]

    def texture(self, location):
        """(byte del png, mcmeta o None) di "minecraft:block/stone", o (None, None)."""
        ns, path = split_location(location)
        raw = self.read("%s/textures/%s.png" % (ns, path))
        meta = self.read("%s/textures/%s.png.mcmeta" % (ns, path))
        return raw, (json.loads(meta.decode("utf-8")) if meta else None)

    def has_blockstates(self):
        return self.read("minecraft/blockstates/stone.json") is not None
