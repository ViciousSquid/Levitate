"""Fetch Levitate's surface materials: photo-scanned PBR textures from Poly Haven.

    python -m game.tools.fetch_textures        # -> assets/textures/levitate/

The walls, floors, coping and metal trim of the mazes are real surfaces,
scanned and published by Poly Haven (https://polyhaven.com) under CC0 -- free
for any use, no attribution required (credited all the same, in
``assets/textures/levitate/CREDITS.md``, which this writes). The files are
committed, so the game never needs the network; run this only to change the
selection in :data:`MATERIALS`.

Each material is stored the way Fio's physically shaded frame looks for it
(engine/renderer/forward/environment.py), beside its base colour:

* ``<name>.jpg``     base colour;
* ``<name>_n.jpg``   normal map, OpenGL convention;
* ``<name>_h.jpg``   height (Poly Haven's displacement), for parallax;
* ``<name>_m.jpg``   ambient occlusion, roughness and metalness in R, G, B;
* ``<name>.mat.json`` the depth of the relief, in world units.

``materials.json`` records each material's real size, which
game/tools/make_mazes.py maps it at.
"""

from __future__ import annotations

import io
import json
import os
import urllib.request

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "assets", "textures", "levitate")
API = "https://api.polyhaven.com"
#: Poly Haven asks API clients to identify themselves.
AGENT = "levitate-texture-fetch/1.0"
RESOLUTION = "1k"

#: Levitate's material -> the Poly Haven texture it is, and how deep its
#: relief is drawn (world units; 1 unit = 1 cm).
MATERIALS = {
    # Breakwater: a board-formed concrete sea wall on a cracked asphalt apron.
    "wall_slate": dict(asset="concrete", parallax=1.2),
    "floor_slate": dict(asset="asphalt_02", parallax=0.8),
    # Sandglass: sandstone block walls on gravelly sand.
    "wall_sand": dict(asset="sandstone_blocks_05", parallax=4.0),
    "floor_sand": dict(asset="gravelly_sand", parallax=1.5),
    # Mossgarden: old mossy brick on moss-jointed cobbles.
    "wall_moss": dict(asset="castle_brick_01", parallax=2.5),
    "floor_moss": dict(asset="mossy_cobblestone", parallax=3.0),
    # Shared: the coping along the walls, and worn steel plate.
    "cap_stone": dict(asset="concrete_wall_008", parallax=0.4),
    "trim_metal": dict(asset="metal_plate_02", parallax=0.5),
}

#: Poly Haven map -> our file suffix.
MAPS = (("Diffuse", ""), ("nor_gl", "_n"), ("arm", "_m"), ("Displacement", "_h"))


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch(name, spec):
    asset = spec["asset"]
    info = json.loads(_get(f"{API}/info/{asset}"))
    files = json.loads(_get(f"{API}/files/{asset}"))
    for source, suffix in MAPS:
        data = _get(files[source][RESOLUTION]["jpg"]["url"])
        path = os.path.join(OUT, f"{name}{suffix}.jpg")
        if suffix == "_h":
            # Height: one channel, stretched to use the whole range (the
            # relief's depth is the material's ``parallax``).
            height = Image.open(io.BytesIO(data)).convert("L")
            low, high = height.getextrema()
            if high > low:
                height = height.point(lambda v: int((v - low) * 255.0 / (high - low) + 0.5))
            height.save(path, quality=90)
        else:
            with open(path, "wb") as f:      # as published: no second encode
                f.write(data)
        print("wrote", os.path.relpath(path, ROOT), f"({os.path.getsize(path) // 1024} KB)")
    with open(os.path.join(OUT, f"{name}.mat.json"), "w") as f:
        json.dump({"parallax": spec["parallax"]}, f)
        f.write("\n")
    size_cm = [round(v / 10.0, 1) for v in info["dimensions"][:2]]
    return {"source": asset, "name": info["name"], "authors": sorted(info.get("authors", {})),
            "size_cm": size_cm, "parallax": spec["parallax"]}


def main():
    os.makedirs(OUT, exist_ok=True)
    manifest = {name: fetch(name, spec) for name, spec in MATERIALS.items()}
    with open(os.path.join(OUT, "materials.json"), "w") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    lines = ["# Texture credits", "",
             "The wall, floor, coping and metal materials are photo-scanned textures from",
             "[Poly Haven](https://polyhaven.com), published under",
             "[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) (public domain).",
             "Fetched at %s by `game/tools/fetch_textures.py`." % RESOLUTION, "",
             "| Levitate! material | Poly Haven texture | Authors |", "|---|---|---|"]
    for name, entry in manifest.items():
        lines.append("| `%s` | [%s](https://polyhaven.com/a/%s) | %s |" % (
            name, entry["name"], entry["source"], ", ".join(entry["authors"])))
    lines += ["", "The pad plates (`pad_*.png`) are Levitate!'s own, drawn in code by",
              "`game/tools/make_pads.py`.", ""]
    with open(os.path.join(OUT, "CREDITS.md"), "w") as f:
        f.write("\n".join(lines))
    print("wrote materials.json and CREDITS.md")


if __name__ == "__main__":
    main()
