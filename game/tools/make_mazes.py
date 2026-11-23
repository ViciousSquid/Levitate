"""Generate Levitate's block-out mazes (original layouts, from fixed seeds).

    python -m game.tools.make_mazes          # -> maps/levitate/*.json

Each maze is a grid carved by a randomised depth-first search, then opened up
for racing: a share of interior walls is knocked out to make loops, and a few
2x2 plazas are cleared. Walls are merged into long brushes so a maze stays at
a few dozen brushes. On top of the layout go:

* the player's start and three home flags in the near half,
* three rival flags in far dead ends,
* spring, boost and barrier pads, power-up orbs,
* raised ledges reached by a spring pad, some holding a flag or an orb,
* a grid of lights.

The maze definitions in :data:`MAZES` are the whole of the level design; tune
them and re-run.
"""

from __future__ import annotations

import json
import os
import random
import uuid

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
]


def tex(name):
    return f"levitate/{name}.png"


def faces(side, top=None, bottom=None):
    return {"north": side, "south": side, "east": side, "west": side,
            "top": top or side, "down": bottom or side}


class Builder:
    def __init__(self, spec):
        self.spec = spec
        self.rng = random.Random(spec["seed"])
        self.brushes = []
        self.things = []
        self.n = 0

    def uid(self, name):
        return str(uuid.uuid5(NAMESPACE, f"{self.spec['file']}/{name}/{self.n}"))

    def brush(self, name, pos, size, textures, trigger=False):
        self.n += 1
        self.brushes.append({"name": name, "id": self.uid(name),
                             "pos": [round(v, 2) for v in pos],
                             "size": [round(v, 2) for v in size],
                             "textures": textures, "is_trigger": trigger})

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
        r = rng.randrange(cols // 3 if rows > 4 else 1, rows - 2)
        east.discard((c, r)); east.discard((c, r + 1))
        north.discard((c, r)); north.discard((c + 1, r))
        plazas.append((c, r))

    width, depth = cols * CELL, rows * CELL
    x0, z0 = -width / 2, -depth / 2

    def centre(c, r):
        return (x0 + (c + 0.5) * CELL, z0 + (r + 0.5) * CELL)

    wall_tex = faces(tex(f"wall_{spec['theme']}"), top=tex("trim_dark"))
    floor_tex = faces(tex("trim_dark"), top=tex("floor_deck"))
    b.brush("Floor", (0, -32, 0), (width + WALL_T, 64, depth + WALL_T), floor_tex)
    # Outer walls.
    y = WALL_H / 2
    b.brush("Wall_North", (0, y, depth / 2), (width + WALL_T, WALL_H, WALL_T), wall_tex)
    b.brush("Wall_South", (0, y, -depth / 2), (width + WALL_T, WALL_H, WALL_T), wall_tex)
    b.brush("Wall_East", (width / 2, y, 0), (WALL_T, WALL_H, depth + WALL_T), wall_tex)
    b.brush("Wall_West", (-width / 2, y, 0), (WALL_T, WALL_H, depth + WALL_T), wall_tex)
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
                b.brush(f"Wall_E{c}_{start}", (x, y, (za + zb) / 2),
                        (WALL_T, WALL_H, zb - za + WALL_T), wall_tex)
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
                b.brush(f"Wall_N{start}_{r}", ((xa + xb) / 2, y, z),
                        (xb - xa + WALL_T, WALL_H, WALL_T), wall_tex)
            else:
                c += 1

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

    # Rival flags: the farthest dead ends (then far cells), spread out.
    rival = pick(dead_ends, key=lambda cell: -dist[cell], count=3)
    if len(rival) < 3:
        rival += pick(dist, key=lambda cell: -dist[cell], count=3 - len(rival))
    for i, cell in enumerate(rival):
        x, z = centre(*cell)
        b.thing("levitateflag", f"Flag_Blue_{i + 1}", (x, 0, z), team="blue")
    # Home flags: dead ends in the near half.
    near = [cell for cell in dist if dist[cell] <= far * 0.5]
    home = pick([c for c in dead_ends if c in near], key=lambda cell: dist[cell], count=3)
    if len(home) < 3:
        home += pick([c for c in near if c != start], key=lambda cell: -dist[cell], count=3 - len(home))
    for i, cell in enumerate(home):
        x, z = centre(*cell)
        b.thing("levitateflag", f"Flag_Red_{i + 1}", (x, 0, z), team="red")

    # Ledges: a raised block in a dead end, a spring pad in the cell before it.
    pad_tex = {k: faces(tex("trim_dark"), top=tex(f"pad_{k}")) for k in ("spring", "boost", "barrier")}
    ledge_tex = faces(tex(f"wall_{spec['theme']}"), top=tex("floor_deck"))
    ledges = pick(dead_ends, key=lambda cell: rng.random(), count=spec["ledges"])
    rewards = ["shield", "phantom", "jammer"]
    for i, cell in enumerate(ledges):
        x, z = centre(*cell)
        size = CELL - WALL_T - round(24 * GEOMETRY_SCALE)
        b.brush(f"Ledge_{i + 1}", (x, LEDGE_H / 2, z), (size, LEDGE_H, size), ledge_tex)
        b.thing("levitatepickup", f"Ledge_Orb_{i + 1}", (x, LEDGE_H + 40, z),
                kind=rewards[i % len(rewards)], respawn_time=25.0)
        before = open_cells(cell, east, north, cols, rows)[0]
        used.add(before)
        bx, bz = centre(*before)
        # The pad sits on the side of the 'before' cell nearest the ledge.
        px, pz = bx + (x - bx) * 0.25, bz + (z - bz) * 0.25
        b.brush(f"Pad_Spring_L{i + 1}", (px, 2, pz), (112, 4, 112), pad_tex["spring"])
        b.thing("levitatepad", f"Spring_L{i + 1}", (px, 4, pz), kind="spring",
                radius=56.0, strength=620.0)

    # Boost pads on long straights: cells with exactly two opposite openings.
    def straight(cell):
        n = open_cells(cell, east, north, cols, rows)
        return len(n) == 2 and (n[0][0] == n[1][0] or n[0][1] == n[1][1])
    boosts = pick([c for c in dist if straight(c)], key=lambda c: rng.random(), count=2 + spec["order"])
    for i, cell in enumerate(boosts):
        x, z = centre(*cell)
        b.brush(f"Pad_Boost_{i + 1}", (x, 2, z), (112, 4, 112), pad_tex["boost"])
        b.thing("levitatepad", f"Boost_{i + 1}", (x, 4, z), kind="boost", radius=56.0, strength=760.0)
    # Free-standing springs and barrier pads.
    for i, cell in enumerate(pick(dist, key=lambda c: rng.random(), count=2)):
        x, z = centre(*cell)
        b.brush(f"Pad_Spring_{i + 1}", (x, 2, z), (112, 4, 112), pad_tex["spring"])
        b.thing("levitatepad", f"Spring_{i + 1}", (x, 4, z), kind="spring", radius=56.0, strength=520.0)
    for i, cell in enumerate(pick(dist, key=lambda c: rng.random(), count=2)):
        x, z = centre(*cell)
        b.brush(f"Pad_Barrier_{i + 1}", (x, 2, z), (112, 4, 112), pad_tex["barrier"])
        b.thing("levitatepad", f"Barrier_{i + 1}", (x, 4, z), kind="barrier", radius=56.0)
    # Orbs: plazas get one each, plus a few in corridors.
    orb_kinds = ["shield", "phantom", "jammer", "barrier"]
    for i, (c, r) in enumerate(plazas):
        x, z = x0 + (c + 1) * CELL, z0 + (r + 1) * CELL
        b.thing("levitatepickup", f"Plaza_Orb_{i + 1}", (x, 40, z), kind=orb_kinds[i % 4], respawn_time=20.0)
    for i, cell in enumerate(pick(dist, key=lambda c: rng.random(), count=3)):
        x, z = centre(*cell)
        b.thing("levitatepickup", f"Orb_{i + 1}", (x, 40, z), kind=orb_kinds[(i + 1) % 4], respawn_time=20.0)

    # Lights: one per 2x2 block of cells, high above the walls.
    for c in range(0, cols, 2):
        for r in range(0, rows, 2):
            x, z = x0 + (c + 1) * CELL, z0 + (r + 1) * CELL
            b.thing("light", f"Light_{c}_{r}", (x, WALL_H + 120, z), intensity=1.5,
                    radius=CELL * 2.6, colour=[220, 230, 255], state="on", casts_shadows=False)

    return {"version": 3, "brushes": b.brushes, "things": b.things}


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
