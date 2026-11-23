"""Random mazes: Levitate!'s levels, made to order.

A shipped maze is a line in ``game/tools/make_mazes.py``'s ``MAZES`` built
from a fixed seed. This makes the same thing from a seed nobody has seen
before: pick a world (or let chance), a size and how open the maze should
be, and :func:`generate` returns a complete Fio map -- walls, piers and
coping, flags, pads, power cells, lamps and the world's own skyline.

Three things use it:

* the launcher's **Random maze** entry, which writes a new one each time
  PLAY is pressed (:func:`write`);
* the editor's random level generator (Tools > Procedural Map Generator,
  ``editor/procedural_generator.py``), whose panel sets these parameters;
* a LevelChanger with *Generate level* on, which sends the player on to a
  fresh maze made with the settings it carries.
"""

from __future__ import annotations

import json
import os
import random

#: The worlds a maze can be built in: theme -> what the generator calls it.
WORLDS = {
    "slate": "Harbour",
    "sand": "Desert ruins",
    "moss": "Walled garden",
    "frost": "High country",
    "ember": "Foundry at night",
}
RANDOM_WORLD = "random"

#: Each setting's range, and :data:`DEFAULTS` within it. ``loops`` is the
#: share of interior walls knocked out, in percent; ``seed`` 0 means a new
#: maze every time.
LIMITS = {
    "cols": (5, 16),
    "rows": (5, 16),
    "loops": (0, 40),
    "plazas": (0, 6),
    "ledges": (0, 5),
    "time_limit": (60, 900),
    "seed": (0, 999999),
}
DEFAULTS = {"world": RANDOM_WORLD, "cols": 9, "rows": 9, "loops": 16, "plazas": 2,
            "ledges": 2, "time_limit": 300, "seed": 0}

#: Where the launcher's random maze is written, relative to the install
#: folder. Not listed among the mazes (its name starts with an underscore)
#: and not kept in the repository.
RANDOM_FILE = os.path.join("maps", "levitate", "_random.json")


def sanitize(params) -> dict:
    """*params* as a complete, in-range set of settings. They can come from
    map data (a LevelChanger carries them), so nothing in them is trusted."""
    params = params if isinstance(params, dict) else {}
    clean = {}
    world = str(params.get("world", DEFAULTS["world"])).strip().lower()
    clean["world"] = world if world in WORLDS else RANDOM_WORLD
    for name, (low, high) in LIMITS.items():
        try:
            value = int(float(params.get(name, DEFAULTS[name])))
        except (TypeError, ValueError):
            value = DEFAULTS[name]
        clean[name] = max(low, min(high, value))
    return clean


def spec_from(params, rng=random) -> dict:
    """The maze definition (as ``make_mazes.MAZES`` holds them) for
    *params*; *rng* supplies whatever they leave to chance."""
    params = sanitize(params)
    seed = params["seed"] or rng.randint(1, LIMITS["seed"][1])
    world = params["world"]
    if world == RANDOM_WORLD:
        world = random.Random(seed).choice(sorted(WORLDS))
    cells = params["cols"] * params["rows"]
    return dict(file="Random", title=f"{WORLDS[world]} {seed}", order=99, seed=seed,
                cols=params["cols"], rows=params["rows"], loops=params["loops"] / 100.0,
                # No more open squares or ledges than the maze has room for.
                plazas=min(params["plazas"], cells // 20),
                ledges=min(params["ledges"], cells // 16),
                theme=world, time_limit=params["time_limit"])


def generate(params=None, rng=random) -> dict:
    """A new maze as Fio map data."""
    from game.tools import make_mazes
    return make_mazes.build(spec_from(params or {}, rng))


def surprise(rng=random) -> dict:
    """Settings for a maze nobody chose: any world, a size between the
    smallest and the largest shipped mazes."""
    cols, rows = rng.randint(7, 12), rng.randint(7, 11)
    return dict(world=RANDOM_WORLD, cols=cols, rows=rows, loops=rng.randint(10, 24),
                plazas=rng.randint(1, 4), ledges=rng.randint(1, 3),
                time_limit=int(round(cols * rows * 3.2 / 30.0) * 30), seed=0)


def write(root_dir=".", params=None, rng=random) -> str:
    """Generate a maze into :data:`RANDOM_FILE` and return that path
    (relative to *root_dir*, with forward slashes), for the launcher."""
    data = generate(params if params is not None else surprise(rng), rng)
    path = os.path.join(root_dir, RANDOM_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)
    return RANDOM_FILE.replace(os.sep, "/")
