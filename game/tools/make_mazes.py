"""Generate Levitate's mazes (original layouts, from fixed seeds).

    python -m game.tools.make_mazes          # -> maps/levitate/*.json

Each maze is a grid carved by a randomised depth-first search, then opened up
for racing: a share of interior walls is knocked out to make loops, and a few
2x2 plazas are cleared. Walls are merged into long brushes so a maze stays at
a few hundred brushes. On top of the layout go:

* the player's start and three home flags in the near half,
* three rival flags in far dead ends,
* spring, boost and barrier pads, power cells,
* raised ledges reached by a spring pad, some holding a flag or a cell,
* the masonry that makes a wall a wall: a pier wherever walls meet and at
  every corner, and coping stones along the top,
* lights: a glow at every pad, cell and flag, and a grid of fill lights for
  the ``classic`` renderer (a lit match hides them; see game/graphics.py),
* navigation nodes for the rival craft: one in every open cell, linked to
  the cells it opens onto (ledge tops are left out: craft stay on the floor),
* eight spawn points spread over the whole maze, one per seat; every craft
  starts a match on one chosen at random (game/spawns.py).

Every face is mapped at its material's real size (:data:`TILE`). The
materials are photo-scanned surfaces from Poly Haven
(game/tools/fetch_textures.py); the pad plates are drawn by
game/tools/make_pads.py.

The maze definitions in :data:`MAZES` are the whole of the level design; tune
them and re-run.
"""

from __future__ import annotations

import json
import math
import os
import random
import uuid

from game.entities import FLAG_RAISE
from game.graphics import FILL_LIGHT

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "maps", "levitate")

#: How large the mazes' geometry is built: corridors, walls, wall height, the
#: floor and ledges all scale by it. What sits in the maze -- pads, orbs,
#: flags, lights -- keeps its own size and only moves with the layout.
GEOMETRY_SCALE = 1.5

CELL = round(352 * GEOMETRY_SCALE)     # corridor pitch (wall centre to wall centre)
WALL_T = round(32 * GEOMETRY_SCALE)    # wall thickness
WALL_H = round(192 * GEOMETRY_SCALE)   # wall height
LEDGE_H = round(96 * GEOMETRY_SCALE)   # raised ledge top (a ledge spring reaches 240)
NAMESPACE = uuid.UUID("6c1f7f2e-5d0e-4b8e-9a51-1e7a7a1e0001")

MAZES = [
    dict(file="Breakwater", title="Breakwater", order=1, seed=1101, cols=8, rows=8,
         loops=0.22, plazas=1, ledges=1, theme="slate", time_limit=240),
    dict(file="Sandglass", title="Sandglass", order=2, seed=2207, cols=10, rows=10,
         loops=0.12, plazas=2, ledges=2, theme="sand", time_limit=300),
    dict(file="Mossgarden", title="Mossgarden", order=3, seed=3313, cols=11, rows=9,
         loops=0.18, plazas=3, ledges=3, theme="moss", time_limit=330),
    dict(file="Frostline", title="Frostline", order=4, seed=4421, cols=12, rows=10,
         loops=0.16, plazas=3, ledges=3, theme="frost", time_limit=360),
    dict(file="Emberworks", title="Emberworks", order=5, seed=5519, cols=12, rows=11,
         loops=0.14, plazas=4, ledges=3, theme="ember", time_limit=390),
]

#: What each world is built of and stands among. A world has its own walls
#: and floor (``wall_<theme>`` / ``floor_<theme>``); here are the material of
#: its coping, the lamps on its piers (``None``: daylight needs none) and the
#: scenery beyond its walls -- ``(count, tiers, top)`` per kind, each tier a
#: ``(width, height)`` box stacked on the last, *top* an optional glow colour.
WORLDS = {
    # A harbour: a lighthouse and the concrete pylons of the breakwater.
    "slate": dict(cap="cap_stone", lamps=None, scenery=[
        (1, [(300, 520), (250, 460), (200, 420), (230, 26)], [255, 244, 200]),
        (6, [(420, 430), (300, 150)], None)]),
    # Desert ruins: stepped temples and obelisks.
    "sand": dict(cap="cap_stone", lamps=None, scenery=[
        (2, [(980, 400), (740, 190), (500, 190), (280, 170)], None),
        (5, [(150, 760), (110, 420), (60, 130)], None)]),
    # A walled garden: the brick towers of the old house.
    "moss": dict(cap="cap_stone", lamps=None, scenery=[
        (3, [(380, 640), (430, 34), (240, 260), (280, 30)], None),
        (4, [(260, 520), (300, 30)], None)]),
    # High country: crags under snow.
    "frost": dict(cap="floor_frost", lamps=None, scenery=[
        (8, [(620, 420), (460, 330), (300, 300), (150, 230)], None)]),
    # A foundry at night: chimney stacks with warning lights, lamps on
    # every other pier.
    "ember": dict(cap="trim_metal", lamps=[255, 168, 84], scenery=[
        (6, [(240, 560), (200, 520), (165, 480)], [255, 40, 30]),
        (2, [(900, 460), (700, 60)], [255, 150, 70])]),
}
SCENERY = "Scenery_"                   # brushes beyond the walls: not on the radar


#: Wall piers and the coping along the top of the walls.
PIER_T = WALL_T + 20                   # a pier's width and depth
PIER_H = WALL_H + 16
CAP_OVERHANG = 7                       # how far the coping projects each side
CAP_H = 12

def _tiles():
    """The world size one repeat of each material covers, from the record
    game/tools/fetch_textures.py keeps of each texture's real size."""
    with open(os.path.join(ROOT, "assets", "textures", "levitate", "materials.json")) as f:
        return {name: tuple(float(v) for v in entry["size_cm"])
                for name, entry in json.load(f).items()}


#: Material -> ``(width, height)`` of one repeat, world units (1 unit = 1 cm):
#: every face is mapped at the size the surface was photographed at.
TILE = _tiles()

#: The colour each pad, power cell and flag glows with.
GLOW = {
    "spring": [140, 240, 60], "boost": [245, 166, 35], "barrier_pad": [224, 122, 48],
    "shield": [64, 236, 200], "phantom": [170, 120, 255], "barrier": [220, 120, 60],
    "jammer": [230, 52, 52], "red": [255, 70, 60], "blue": [70, 130, 255],
}

SIDES = ("north", "south", "east", "west")


def tex(name):
    """A material's texture file (pads are PNG, everything tiled is JPEG)."""
    return f"levitate/{name}.png" if name.startswith("pad_") else f"levitate/{name}.jpg"


def tile_of(name):
    return TILE[name]


def glow_box(colour, intensity=3.0, radius=0.0):
    """How a brush glows: a lamp's glass, a warning light. With *radius* it
    lights its surroundings too."""
    look = {"shader": "Glow", "colour": list(colour), "glow_intensity": intensity}
    if radius:
        look.update(emissive=True, emissive_intensity=1.4, emissive_radius=radius)
    return look


def material(size, side, top=None, bottom=None, shift=0.0, fit_top=False):
    """Textures and their mapping for a box of *size*: *side* on the four
    walls, *top* and *bottom* (default: *side*) above and below, each at its
    real-world scale. *shift* slides the side faces along the wall, so
    neighbouring walls do not start on the same brick; *fit_top* stretches
    the top texture over the top face once (a pad's emblem)."""
    w, h, d = size
    top, bottom = top or side, bottom or side
    textures = {tag: tex(side) for tag in SIDES}
    textures["top"], textures["down"] = tex(top), tex(bottom)
    tw, th = tile_of(side)
    scale = {"north": [w / tw, h / th], "south": [w / tw, h / th],
             "east": [d / tw, h / th], "west": [d / tw, h / th]}
    shifts = {tag: [shift, 0.0] for tag in SIDES}
    for tag, name in (("top", top), ("down", bottom)):
        if tag == "top" and fit_top:
            continue
        fw, fh = tile_of(name)
        scale[tag] = [w / fw, d / fh]
    # Fio's box maps its east and west faces a quarter turn round from its
    # north and south ones: turned back, so a wall's courses run level on
    # every side.
    return {"textures": textures, "uv_scale": scale, "uv_shift": shifts,
            "uv_angle": {"east": 90.0, "west": 90.0}}


class Builder:
    def __init__(self, spec):
        self.spec = spec
        self.rng = random.Random(spec["seed"])
        self.brushes = []
        self.things = []
        self.n = 0

    def uid(self, name):
        return str(uuid.uuid5(NAMESPACE, f"{self.spec['file']}/{name}/{self.n}"))

    def brush(self, name, pos, size, look, trigger=False):
        """A box brush; *look* is what :func:`material` returns."""
        self.n += 1
        entry = {"name": name, "id": self.uid(name),
                 "pos": [round(v, 2) for v in pos],
                 "size": [round(v, 2) for v in size],
                 "textures": look["textures"], "is_trigger": trigger}
        for key in ("uv_scale", "uv_shift"):
            if look.get(key):
                entry[key] = {tag: [round(v, 4) for v in pair]
                              for tag, pair in look[key].items()}
        if look.get("uv_angle"):
            entry["uv_angle"] = dict(look["uv_angle"])
        for key in ("shader", "colour", "glow_intensity", "emissive",
                    "emissive_intensity", "emissive_radius"):
            if key in look:
                entry[key] = look[key]
        self.brushes.append(entry)

    def light(self, name, pos, colour, intensity, radius, **props):
        self.thing("light", name, pos, intensity=intensity, radius=radius,
                   colour=list(colour), state="on", casts_shadows=False, **props)

    def thing(self, etype, name, pos, **props):
        self.n += 1
        properties = {"type": etype, "name": name, "id": self.uid(name)}
        properties.update(props)
        self.things.append({"type": etype, "pos": [round(v, 2) for v in pos],
                            "properties": properties})


# -- maze carving ------------------------------------------------------------
def carve(cols, rows, rng):
    """Walls between cells, as sets of (col, row) for the east and north
    walls each cell owns. A wall missing from the set is open."""
    east = {(c, r) for c in range(cols - 1) for r in range(rows)}
    north = {(c, r) for c in range(cols) for r in range(rows - 1)}
    seen = {(0, 0)}
    stack = [(0, 0)]
    while stack:
        c, r = stack[-1]
        options = [(dc, dr) for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1))
                   if 0 <= c + dc < cols and 0 <= r + dr < rows and (c + dc, r + dr) not in seen]
        if not options:
            stack.pop()
            continue
        dc, dr = rng.choice(options)
        nc, nr = c + dc, r + dr
        if dc == 1:
            east.discard((c, r))
        elif dc == -1:
            east.discard((nc, nr))
        elif dr == 1:
            north.discard((c, r))
        else:
            north.discard((nc, nr))
        seen.add((nc, nr))
        stack.append((nc, nr))
    return east, north


def open_cells(cell, east, north, cols, rows):
    """The neighbours reachable from *cell*."""
    c, r = cell
    out = []
    if c < cols - 1 and (c, r) not in east:
        out.append((c + 1, r))
    if c > 0 and (c - 1, r) not in east:
        out.append((c - 1, r))
    if r < rows - 1 and (c, r) not in north:
        out.append((c, r + 1))
    if r > 0 and (c, r - 1) not in north:
        out.append((c, r - 1))
    return out


def distances(start, east, north, cols, rows):
    dist = {start: 0}
    queue = [start]
    while queue:
        cell = queue.pop(0)
        for nxt in open_cells(cell, east, north, cols, rows):
            if nxt not in dist:
                dist[nxt] = dist[cell] + 1
                queue.append(nxt)
    return dist


# -- building ------------------------------------------------------------------
def build(spec):
    b = Builder(spec)
    rng = b.rng
    cols, rows = spec["cols"], spec["rows"]
    east, north = carve(cols, rows, rng)
    # Loops: knock out a share of the remaining interior walls.
    for walls in (east, north):
        for wall in sorted(walls):
            if rng.random() < spec["loops"]:
                walls.discard(wall)
    # Plazas: clear 2x2 blocks away from the start corner.
    plazas = []
    for _ in range(spec["plazas"]):
        c = rng.randrange(1, cols - 2)
        r = rng.randrange(min(cols // 3 if rows > 4 else 1, rows - 3), rows - 2)
        east.discard((c, r)); east.discard((c, r + 1))
        north.discard((c, r)); north.discard((c + 1, r))
        plazas.append((c, r))

    width, depth = cols * CELL, rows * CELL
    x0, z0 = -width / 2, -depth / 2

    def centre(c, r):
        return (x0 + (c + 0.5) * CELL, z0 + (r + 0.5) * CELL)

    theme = spec["theme"]
    world = WORLDS[theme]
    wall_name, floor_name, cap_name = f"wall_{theme}", f"floor_{theme}", world["cap"]
    piers = set()                       # lattice points where a wall ends or turns

    def wall(name, pos, size, lattice):
        """A wall run, the coping along its top and the piers it meets."""
        b.brush(name, pos, size, material(size, wall_name, top=cap_name,
                                          shift=round(rng.random(), 3)))
        along_x = size[0] > size[2]
        cap = ((size[0] + 2 * CAP_OVERHANG, CAP_H, WALL_T + 2 * CAP_OVERHANG) if along_x else
               (WALL_T + 2 * CAP_OVERHANG, CAP_H, size[2] + 2 * CAP_OVERHANG))
        b.brush("Cap_" + name[5:], (pos[0], WALL_H + CAP_H / 2, pos[2]), cap,
                material(cap, cap_name, shift=round(rng.random(), 3)))
        piers.update(lattice)

    floor_size = (width + WALL_T, 64, depth + WALL_T)
    b.brush("Floor", (0, -32, 0), floor_size,
            material(floor_size, "trim_metal", top=floor_name))
    # Outer walls.
    y = WALL_H / 2
    wall("Wall_North", (0, y, depth / 2), (width + WALL_T, WALL_H, WALL_T),
         [(c, rows) for c in range(cols + 1)])
    wall("Wall_South", (0, y, -depth / 2), (width + WALL_T, WALL_H, WALL_T),
         [(c, 0) for c in range(cols + 1)])
    wall("Wall_East", (width / 2, y, 0), (WALL_T, WALL_H, depth + WALL_T),
         [(cols, r) for r in range(rows + 1)])
    wall("Wall_West", (-width / 2, y, 0), (WALL_T, WALL_H, depth + WALL_T),
         [(0, r) for r in range(rows + 1)])
    # Interior walls, merged into runs. An east wall of (c, r) sits on the
    # line x = x0 + (c+1)*CELL spanning row r; runs merge along z.
    for c in range(cols - 1):
        r = 0
        while r < rows:
            if (c, r) in east:
                start = r
                while r < rows and (c, r) in east:
                    r += 1
                x = x0 + (c + 1) * CELL
                za, zb = z0 + start * CELL, z0 + r * CELL
                wall(f"Wall_E{c}_{start}", (x, y, (za + zb) / 2),
                     (WALL_T, WALL_H, zb - za + WALL_T),
                     [(c + 1, k) for k in range(start, r + 1)])
            else:
                r += 1
    for r in range(rows - 1):
        c = 0
        while c < cols:
            if (c, r) in north:
                start = c
                while c < cols and (c, r) in north:
                    c += 1
                z = z0 + (r + 1) * CELL
                xa, xb = x0 + start * CELL, x0 + c * CELL
                wall(f"Wall_N{start}_{r}", ((xa + xb) / 2, y, z),
                     (xb - xa + WALL_T, WALL_H, WALL_T),
                     [(k, r + 1) for k in range(start, c + 1)])
            else:
                c += 1
    # A pier at every lattice point a wall touches, a little taller and
    # wider than the walls, with its own capstone.
    for c, r in sorted(piers):
        px, pz = x0 + c * CELL, z0 + r * CELL
        size = (PIER_T, PIER_H, PIER_T)
        b.brush(f"Pier_{c}_{r}", (px, PIER_H / 2, pz), size,
                material(size, wall_name, top=cap_name, shift=round(rng.random(), 3)))
        cap = (PIER_T + 2 * CAP_OVERHANG, CAP_H, PIER_T + 2 * CAP_OVERHANG)
        b.brush(f"PierCap_{c}_{r}", (px, PIER_H + CAP_H / 2, pz), cap,
                material(cap, cap_name))
        if world["lamps"] and (c + r) % 2 == 0:
            # A lamp on the pier: a caged glass over a steel foot, and the
            # light it throws down into the corridors, shadows and all.
            top = PIER_H + CAP_H
            foot, glass = (30, 10, 30), (22, 26, 22)
            b.brush(f"LampFoot_{c}_{r}", (px, top + 5, pz), foot, material(foot, "trim_metal"))
            b.brush(f"Lamp_{c}_{r}", (px, top + 23, pz), glass,
                    dict(material(glass, "trim_metal"), **glow_box(world["lamps"], 3.2)))
            b.thing("light", f"LampLight_{c}_{r}", (px, top + 52, pz), intensity=1.5,
                    radius=CELL * 1.9, colour=list(world["lamps"]), state="on",
                    casts_shadows=True, shadow_softness=2.5)

    # -- placement --------------------------------------------------------------
    start = (0, 0)
    dist = distances(start, east, north, cols, rows)
    far = max(dist.values()) or 1
    used = {start}
    plaza_cells = {(c + dc, r + dr) for c, r in plazas for dc in (0, 1) for dr in (0, 1)}
    dead_ends = [cell for cell in dist if len(open_cells(cell, east, north, cols, rows)) == 1
                 and cell != start]

    def pick(cells, key, count):
        chosen = []
        for cell in sorted(cells, key=key):
            if cell in used or cell in plaza_cells:
                continue
            if any(abs(cell[0] - o[0]) + abs(cell[1] - o[1]) < 3 for o in chosen):
                continue
            chosen.append(cell)
            used.add(cell)
            if len(chosen) == count:
                break
        return chosen

    def spare(count, key):
        """*count* more cells where the rules above found too few (a very
        small maze): any cell not yet taken, however close to the others."""
        chosen = [cell for cell in sorted(dist, key=key) if cell not in used][:max(count, 0)]
        used.update(chosen)
        return chosen

    sx, sz = centre(*start)
    # Face down the open corridor out of the start cell.
    first = open_cells(start, east, north, cols, rows)[0]
    angle = 90 if first[0] > start[0] else 0
    b.thing("playerstart", "PlayerStart_1", (sx, 50, sz), angle=angle, primary=True,
            creation_index=0)
    b.thing("levitaterules", "Maze_Rules", (sx, 0, sz - CELL * 0.3),
            title=spec["title"], order=spec["order"], theme=spec["theme"],
            time_limit=float(spec["time_limit"]), player_team="red",
            hover_friction=0.14, hover_accel=0.35, turn_rate=150.0, wall_bounce=0.55)

    def flag(name, cell, team):
        x, z = centre(*cell)
        b.thing("levitateflag", name, (x, FLAG_RAISE, z), team=team,
                rotation=[0.0, float(rng.randrange(0, 360, 15)), 0.0])
        b.light(name + "_Glow", (x, FLAG_RAISE + 20, z), GLOW[team], 0.9, 300.0,
                levitate_for=name)

    def cell_orb(name, pos, kind, respawn):
        b.thing("levitatepickup", name, pos, kind=kind, respawn_time=respawn)
        b.light(name + "_Glow", pos, GLOW[kind], 1.2, 320.0, levitate_for=name)

    def pad(name, kind, x, z, **props):
        size = (112, 4, 112)
        b.brush("Pad_" + name, (x, 2, z), size,
                material(size, "trim_metal", top=f"pad_{kind}", fit_top=True))
        b.thing("levitatepad", name, (x, 4, z), kind=kind, radius=56.0, **props)
        b.light(name + "_Glow", (x, 46, z), GLOW["barrier_pad" if kind == "barrier" else kind],
                1.0, 260.0)

    # Rival flags: the farthest dead ends (then far cells), spread out.
    rival = pick(dead_ends, key=lambda cell: -dist[cell], count=3)
    if len(rival) < 3:
        rival += pick(dist, key=lambda cell: -dist[cell], count=3 - len(rival))
    rival += spare(3 - len(rival), key=lambda cell: -dist[cell])
    for i, cell in enumerate(rival):
        flag(f"Flag_Blue_{i + 1}", cell, "blue")
    # Home flags: dead ends in the near half.
    near = [cell for cell in dist if dist[cell] <= far * 0.5]
    home = pick([c for c in dead_ends if c in near], key=lambda cell: dist[cell], count=3)
    if len(home) < 3:
        home += pick([c for c in near if c != start], key=lambda cell: -dist[cell], count=3 - len(home))
    home += spare(3 - len(home), key=lambda cell: dist[cell])
    for i, cell in enumerate(home):
        flag(f"Flag_Red_{i + 1}", cell, "red")

    # Ledges: a raised block in a dead end, a spring pad in the cell before it.
    ledges = pick(dead_ends, key=lambda cell: rng.random(), count=spec["ledges"])
    rewards = ["shield", "phantom", "jammer"]
    lip = 10                             # the stone edge round a ledge's top
    for i, cell in enumerate(ledges):
        x, z = centre(*cell)
        size = CELL - WALL_T - round(24 * GEOMETRY_SCALE)
        body = (size, LEDGE_H - lip, size)
        b.brush(f"Ledge_{i + 1}", (x, (LEDGE_H - lip) / 2, z), body,
                material(body, wall_name, top=floor_name))
        edge = (size + 10, lip, size + 10)
        b.brush(f"LedgeEdge_{i + 1}", (x, LEDGE_H - lip / 2, z), edge,
                material(edge, cap_name, top=floor_name))
        cell_orb(f"Ledge_Orb_{i + 1}", (x, LEDGE_H + 40, z), rewards[i % len(rewards)], 25.0)
        before = open_cells(cell, east, north, cols, rows)[0]
        used.add(before)
        bx, bz = centre(*before)
        # The pad sits on the side of the 'before' cell nearest the ledge.
        pad(f"Spring_L{i + 1}", "spring", bx + (x - bx) * 0.25, bz + (z - bz) * 0.25,
            strength=620.0)

    # Boost pads on long straights: cells with exactly two opposite openings.
    def straight(cell):
        n = open_cells(cell, east, north, cols, rows)
        return len(n) == 2 and (n[0][0] == n[1][0] or n[0][1] == n[1][1])
    boosts = pick([c for c in dist if straight(c)], key=lambda c: rng.random(), count=2 + spec["order"])
    for i, cell in enumerate(boosts):
        pad(f"Boost_{i + 1}", "boost", *centre(*cell), strength=760.0)
    # Free-standing springs and barrier pads.
    for i, cell in enumerate(pick(dist, key=lambda c: rng.random(), count=2)):
        pad(f"Spring_{i + 1}", "spring", *centre(*cell), strength=520.0)
    for i, cell in enumerate(pick(dist, key=lambda c: rng.random(), count=2)):
        pad(f"Barrier_{i + 1}", "barrier", *centre(*cell))
    # Power cells: plazas get one each, plus a few in corridors.
    orb_kinds = ["shield", "phantom", "jammer", "barrier"]
    for i, (c, r) in enumerate(plazas):
        cell_orb(f"Plaza_Orb_{i + 1}", (x0 + (c + 1) * CELL, 40, z0 + (r + 1) * CELL),
                 orb_kinds[i % 4], 20.0)
    for i, cell in enumerate(pick(dist, key=lambda c: rng.random(), count=3)):
        x, z = centre(*cell)
        cell_orb(f"Orb_{i + 1}", (x, 40, z), orb_kinds[(i + 1) % 4], 20.0)

    # Fill lights, for the classic renderer: one per 2x2 block of cells, high
    # above the walls. A lit match has the sun and the sky instead.
    for c in range(0, cols, 2):
        for r in range(0, rows, 2):
            x, z = x0 + (c + 1) * CELL, z0 + (r + 1) * CELL
            b.light(f"Light_{c}_{r}", (x, WALL_H + 120, z), [220, 230, 255], 1.5,
                    CELL * 2.6, **{FILL_LIGHT: True})

    scenery(b, world, wall_name, cap_name, width, depth)
    # Last, so everything above keeps the ids and the layout it always had.
    navigation(b, cols, rows, east, north, centre, set(ledges))
    flags = set(rival) | set(home)
    spawn_points(b, cols, rows, east, north, centre, start, used, plaza_cells,
                 blocked=flags | set(ledges))
    return {"version": 3, "brushes": b.brushes, "things": b.things}


#: Spawn points in a maze (game.spawns.SPAWN_COUNT): one per seat.
SPAWNS = 8


def spawn_points(b, cols, rows, east, north, centre, start, used, plaza_cells, blocked):
    """:data:`SPAWNS` spawn points (``levitatespawn``), spread over the maze
    as far from each other as they can be: the start cell first, then each
    next the cell farthest from those already chosen. Empty cells come first;
    in a maze too small for that, a cell holding a pad or a cell goes, off
    to one side of it. Never a flag's cell or a ledge, or the cell before a
    ledge (its spring)."""
    def heading(cell):
        nxt = open_cells(cell, east, north, cols, rows)
        if not nxt:
            return 0.0
        dc, dr = nxt[0][0] - cell[0], nxt[0][1] - cell[1]
        return {(1, 0): 90.0, (-1, 0): 270.0, (0, 1): 0.0, (0, -1): 180.0}[(dc, dr)]

    cells = [(c, r) for r in range(rows) for c in range(cols)
             if (c, r) not in blocked and (c, r) != start]
    clear = {cell for cell in cells if cell not in used or cell in plaza_cells}
    chosen = [start]
    while len(chosen) < min(SPAWNS, len(cells) + 1):
        def score(cell):
            nearest = min(math.hypot(cell[0] - o[0], cell[1] - o[1]) for o in chosen)
            return nearest - (0.0 if cell in clear else 1.5)
        best = max((cell for cell in cells if cell not in chosen), key=score)
        chosen.append(best)
    for i, cell in enumerate(chosen):
        x, z = centre(*cell)
        if cell in used and cell not in plaza_cells and cell != start:
            # Beside what is in the middle of the cell, not on it.
            x, z = x + CELL * 0.27, z + CELL * 0.27
        b.thing("levitatespawn", f"Spawn_{i + 1}", (x, 0, z), angle=heading(cell))


#: How high a navigation node stands: on the floor, under a craft's hull.
NODE_Y = 16


def navigation(b, cols, rows, east, north, centre, ledges=()):
    """The rival craft's navigation nodes (``levitatenode``): one at the
    centre of every cell, linked to each neighbour it opens onto. A ledge's
    top is not on the floor, so it has none and nothing links to it."""
    def name(cell):
        return f"Nav_{cell[0]}_{cell[1]}"

    for r in range(rows):
        for c in range(cols):
            if (c, r) in ledges:
                continue
            links = [name(n) for n in open_cells((c, r), east, north, cols, rows)
                     if n not in ledges]
            x, z = centre(c, r)
            b.thing("levitatenode", name((c, r)), (x, NODE_Y, z), links=",".join(links))


def scenery(b, world, wall_name, cap_name, width, depth):
    """What stands beyond the walls and rises above them: each world's own
    skyline, set round the maze. Nothing here can be reached; it is there to
    be seen over the walls, and to throw long shadows."""
    rng = b.rng
    pieces = [(tiers, glow) for count, tiers, glow in world["scenery"] for _ in range(count)]
    rng.shuffle(pieces)
    # Spread round the perimeter, a jittered share of it each.
    perimeter = 2 * (width + depth)
    for i, (tiers, glow) in enumerate(pieces):
        along = (i + 0.2 + 0.6 * rng.random()) / len(pieces) * perimeter
        out = WALL_T + tiers[0][0] / 2 + rng.uniform(140, 620)
        if along < width:
            x, z = -width / 2 + along, depth / 2 + out
        elif along < width + depth:
            x, z = width / 2 + out, depth / 2 - (along - width)
        elif along < 2 * width + depth:
            x, z = width / 2 - (along - width - depth), -depth / 2 - out
        else:
            x, z = -width / 2 - out, -depth / 2 + (along - 2 * width - depth)
        y = -64.0
        for tier, (wide, high) in enumerate(tiers):
            high = high + (64 if tier == 0 else 0)
            size = (wide, high, wide)
            b.brush(f"{SCENERY}{i}_{tier}", (x, y + high / 2, z), size,
                    material(size, wall_name, top=cap_name, shift=round(rng.random(), 3)))
            y += high
        if glow:
            lamp = (tiers[-1][0] * 0.62, 46, tiers[-1][0] * 0.62)
            b.brush(f"{SCENERY}{i}_light", (x, y + lamp[1] / 2, z), lamp,
                    dict(material(lamp, "trim_metal"), **glow_box(glow, 3.0)))


def main():
    os.makedirs(OUT, exist_ok=True)
    for spec in MAZES:
        data = build(spec)
        path = os.path.join(OUT, spec["file"] + ".json")
        with open(path, "w") as f:
            json.dump(data, f, indent=1)
        print(f"wrote {os.path.relpath(path, ROOT)}: {len(data['brushes'])} brushes, "
              f"{len(data['things'])} things")


if __name__ == "__main__":
    main()
