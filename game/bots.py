"""Rival hovercraft: the bots a match starts with.

Every match fills the maze with rival craft on the other team -- how many is
the launcher's **Rival craft** setting (``[Game] bots`` in ``settings.ini``,
:data:`DEFAULT_BOTS` when unset, 0 for a solo time trial). Like the player,
each starts on one of the maze's spawn points at random (game/spawns.py),
and they play the match against you:

* **raiders** go for your home flags. A raider that reaches one picks it up
  and carries it to the nearest of its own team's flags; a flag delivered
  there is lost. Ram a
  carrier to knock the flag loose: it goes straight back to its pole. Lose all
  three and the match is over.
* **defenders** patrol their own flags and ram you when they see you.

A match has :data:`MAX_CRAFT` seats. When it is full and another human
craft joins (Fio's split-screen player 2, F9), a rival gives up its seat --
one not carrying a flag, a defender before a raider -- and comes back when
the seat is free again (:meth:`Squad.seat`).

They answer the power cells: a **phantom** hides you from them, a **jammer**
stalls every rival craft near you, and a **barrier** dropped behind you is a
wall of force they cannot cross for a while.

Each craft is Fio's own Monster (the ``hovercraft`` type, blue for the rival
team) so it is drawn as an eight-view billboard, driven by an engine
:class:`~engine.player.Player` for gravity, steps and walls, with stock
Monster AI kept off it (``disabled``).

Craft find their way over the maze's **navigation nodes**
(:class:`~game.entities.LevitateNode`, one per open cell in every shipped and
random maze; :class:`NodeGraph`), cutting corners wherever the way ahead is
clear. A grid of the maze's wall footprints (:class:`NavGrid`) answers what is
clear and what can be seen; a maze with no nodes at all is steered over that
grid instead (:class:`GridRoutes`).
"""

from __future__ import annotations

import math
import random
from collections import deque

#: How many rival craft a match starts with when the launcher has not said.
DEFAULT_BOTS = 3
#: The most the launcher offers.
MAX_BOTS = 7
#: Seats in a match: human craft and rival craft together. When it is full a
#: human joining takes a rival's seat.
MAX_CRAFT = MAX_BOTS + 1
#: Where the count lives in settings.ini.
SETTINGS_SECTION, SETTINGS_KEY = "Game", "bots"

#: Cruising speed (units/s). The player's craft runs 300 straight ahead.
BOT_SPEED = 255.0
#: How hard a bot's thrusters change its velocity (units/s²).
BOT_THRUST = 720.0
#: A wall hit faster than this bounces the craft back, as the player's does.
BOUNCE_FROM = 150.0
WALL_BOUNCE = 0.55

#: The billboard (world units). The craft sits in the lower part of its
#: 256-pixel frame, so the frame is lowered to put its skirt near the floor.
SPRITE_SIZE = 144.0
SPRITE_DROP = 0.2
#: Contact distance between two craft, centre to centre, and between a craft
#: and the player.
CRAFT_RADIUS = 46.0
PLAYER_RADIUS = 28.0
#: How far a bot keeps its centre from any wall when planning.
CLEARANCE = 64.0
#: A bump leaves the two craft parting at least this fast, and stuns a bot's
#: thrusters for a moment.
BUMP_SEPARATION = 160.0
BUMP_RESTITUTION = 0.9
BUMP_STUN = 0.6

#: When raiders set out: the first after RAID_START seconds, each next one
#: RAID_STAGGER later; after delivering a flag a raider rests RAID_REST.
RAID_START = 10.0
RAID_STAGGER = 9.0
RAID_REST = 18.0
#: How close a raider must come to a flag, or its base, to take or deliver.
FLAG_REACH = 72.0
BASE_REACH = 110.0
#: A defender sees the player within this range when nothing is in between.
SIGHT_RANGE = 1500.0

#: Power cells against rival craft.
JAM_SECONDS = 6.0
JAM_RANGE = 2200.0
BARRIER_SECONDS = 15.0
BARRIER_RADIUS = 120.0

#: The rival craft's look (registered by game.install).
MONSTER_TYPE = "hovercraft"


class Pilot:
    """A human craft as the rivals see it: where it is, how it moves, whether
    a shield makes it heavy or a phantom hides it. *craft* has ``position``
    and a settable ``velocity`` (the RuntimeAPI's PlayerState, or a remote
    player's craft in a multiplayer race); *bonk* is called when a rival
    rams it."""

    def __init__(self, craft, shielded=False, hidden=False, bonk=None):
        self.craft = craft
        self.shielded = bool(shielded)
        self.hidden = bool(hidden)
        self.bonk = bonk

    @property
    def position(self):
        return tuple(self.craft.position)

    @property
    def velocity(self):
        return tuple(self.craft.velocity)

    @velocity.setter
    def velocity(self, value):
        self.craft.velocity = value


def bots_from(config) -> int:
    """The number of rival craft ``[Game] bots`` asks for, in 0..MAX_BOTS."""
    try:
        value = int(float(config.get(SETTINGS_SECTION, SETTINGS_KEY,
                                     fallback=str(DEFAULT_BOTS))))
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_BOTS
    return max(0, min(MAX_BOTS, value))


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
class NavGrid:
    """Where a craft can go, on a grid over the maze.

    *walls* are the solid footprints ``(x0, z0, x1, z1)`` the radar draws
    (game.host's ``_radar_walls``); a cell is blocked when it lies within
    *clearance* of one. :meth:`field` is a breadth-first distance field to a
    goal, cached per goal; :meth:`steer` reads one to say where to head next.
    """

    #: Grid cells along the maze's longer side at most (a cap on the cost of a
    #: field, for the largest random mazes).
    MAX_SPAN = 170

    def __init__(self, walls, bounds, clearance=CLEARANCE, resolution=40.0):
        x0, z0, x1, z1 = bounds
        extent = max(x1 - x0, z1 - z0, 1.0)
        self.res = res = max(float(resolution), extent / self.MAX_SPAN)
        self.x0, self.z0 = float(x0), float(z0)
        self.cols = max(1, int(math.ceil((x1 - x0) / res)))
        self.rows = max(1, int(math.ceil((z1 - z0) / res)))
        size = self.cols * self.rows
        self.blocked = bytearray(size)
        self.solid = bytearray(size)
        for wx0, wz0, wx1, wz1 in walls:
            self._mark(self.solid, wx0, wz0, wx1, wz1)
            self._mark(self.blocked, wx0 - clearance, wz0 - clearance,
                       wx1 + clearance, wz1 + clearance)
        self._fields = {}

    def _mark(self, grid, x0, z0, x1, z1):
        c0, r0 = self._cell_xz(x0, z0)
        c1, r1 = self._cell_xz(x1, z1)
        cols = self.cols
        for r in range(r0, r1 + 1):
            row = r * cols
            for c in range(c0, c1 + 1):
                grid[row + c] = 1

    # -- cells ---------------------------------------------------------------
    def _cell_xz(self, x, z):
        c = int((x - self.x0) // self.res)
        r = int((z - self.z0) // self.res)
        return min(self.cols - 1, max(0, c)), min(self.rows - 1, max(0, r))

    def cell(self, x, z):
        c, r = self._cell_xz(x, z)
        return r * self.cols + c

    def centre(self, index):
        r, c = divmod(index, self.cols)
        return (self.x0 + (c + 0.5) * self.res, self.z0 + (r + 0.5) * self.res)

    def free(self, x, z):
        return not self.blocked[self.cell(x, z)]

    def nearest_free(self, x, z, reach=8):
        """The free cell nearest to ``(x, z)`` within *reach* cells, or None."""
        c0, r0 = self._cell_xz(x, z)
        best = None
        for radius in range(reach + 1):
            for r in range(r0 - radius, r0 + radius + 1):
                if not 0 <= r < self.rows:
                    continue
                for c in range(c0 - radius, c0 + radius + 1):
                    if not 0 <= c < self.cols or max(abs(c - c0), abs(r - r0)) != radius:
                        continue
                    index = r * self.cols + c
                    if self.blocked[index]:
                        continue
                    cx, cz = self.centre(index)
                    d = (cx - x) ** 2 + (cz - z) ** 2
                    if best is None or d < best[0]:
                        best = (d, index)
            if best is not None:
                return best[1]
        return None

    def clear(self, a, b, grid=None, leave=False):
        """Whether the straight line from *a* to *b* (``(x, z)``) stays off
        *grid* (default: the blocked cells). With *leave*, a start that is
        already too near a wall may first move out of its margin."""
        grid = self.blocked if grid is None else grid
        ax, az = a
        bx, bz = b
        length = math.hypot(bx - ax, bz - az)
        steps = max(1, int(length / (self.res * 0.5)))
        leaving = leave and grid[self.cell(ax, az)]
        for i in range(steps + 1):
            t = i / steps
            if grid[self.cell(ax + (bx - ax) * t, az + (bz - az) * t)]:
                if leaving and t * length <= CLEARANCE + self.res:
                    continue
                return False
            leaving = False
        return True

    def sees(self, a, b):
        """A line of sight: nothing solid between *a* and *b*."""
        return self.clear(a, b, self.solid)

    # -- distance fields -----------------------------------------------------
    def field(self, x, z):
        """Steps from every cell to the free cell nearest ``(x, z)``
        (``-1``: unreachable); None when there is no free cell near it."""
        goal = self.nearest_free(x, z)
        if goal is None:
            return None
        cached = self._fields.get(goal)
        if cached is not None:
            return cached
        cols, rows, blocked = self.cols, self.rows, self.blocked
        dist = [-1] * (cols * rows)
        dist[goal] = 0
        queue = deque([goal])
        pop, push = queue.popleft, queue.append
        while queue:
            index = pop()
            step = dist[index] + 1
            r, c = divmod(index, cols)
            if c > 0 and dist[index - 1] < 0 and not blocked[index - 1]:
                dist[index - 1] = step
                push(index - 1)
            if c < cols - 1 and dist[index + 1] < 0 and not blocked[index + 1]:
                dist[index + 1] = step
                push(index + 1)
            if r > 0 and dist[index - cols] < 0 and not blocked[index - cols]:
                dist[index - cols] = step
                push(index - cols)
            if r < rows - 1 and dist[index + cols] < 0 and not blocked[index + cols]:
                dist[index + cols] = step
                push(index + cols)
        self._fields[goal] = dist
        return dist

    def reachable(self, x, z, reach):
        """Whether a craft on the floor can come within *reach* of ``(x, z)``
        (a flag on a ledge cannot be reached from the floor)."""
        goal = self.nearest_free(x, z)
        if goal is None:
            return False
        gx, gz = self.centre(goal)
        return math.hypot(gx - x, gz - z) <= reach

    def distance(self, field, x, z):
        """Steps to the field's goal from ``(x, z)``, or None."""
        if field is None:
            return None
        index = self.cell(x, z)
        if field[index] < 0:
            index = self.nearest_free(x, z, reach=3)
            if index is None or field[index] < 0:
                return None
        return field[index]

    def steer(self, field, x, z, lookahead=14):
        """Where to head from ``(x, z)`` to follow *field* downhill: the
        farthest of the next *lookahead* steps in a clear straight line."""
        cols, rows = self.cols, self.rows
        here = self.cell(x, z)
        if field is None:
            return None
        if self.blocked[here] or field[here] < 0:
            # Against a wall, or somewhere the field does not reach (a ledge):
            # back to the nearest cell that is on it.
            index = self.nearest_free(x, z)
            return self.centre(index) if index is not None else None
        path = [here]
        current = here
        for _ in range(lookahead):
            best, best_d = None, field[current]
            r, c = divmod(current, cols)
            for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nc, nr = c + dc, r + dr
                if not (0 <= nc < cols and 0 <= nr < rows):
                    continue
                index = nr * cols + nc
                d = field[index]
                if d < 0 or self.blocked[index]:
                    continue
                if dc and dr and (self.blocked[r * cols + nc] or self.blocked[nr * cols + c]):
                    continue           # no cutting a corner
                if d < best_d:
                    best, best_d = index, d
            if best is None:
                break
            path.append(best)
            current = best
        if len(path) == 1:
            return self.centre(here)
        for index in reversed(path[1:]):
            point = self.centre(index)
            if self.clear((x, z), point):
                return point
        return self.centre(path[1])


class GridRoutes:
    """Routes over a :class:`NavGrid`'s distance fields: for a maze that has
    no navigation nodes."""

    def __init__(self, grid):
        self.grid = grid

    def prepare(self, x, z):
        self.grid.field(x, z)

    def steer(self, gx, gz, x, z):
        return self.grid.steer(self.grid.field(gx, gz), x, z)

    def distance(self, gx, gz, x, z):
        steps = self.grid.distance(self.grid.field(gx, gz), x, z)
        return None if steps is None else steps * self.grid.res


class NodeGraph:
    """Routes over the maze's navigation nodes.

    A route runs from the nodes in clear sight of the craft, along the
    links, to the node in clear sight of the goal; the craft heads for the
    farthest point of it in a clear straight line, so it takes the racing
    line through open ground and only follows the nodes round corners.
    Shortest distances to each goal are worked out once and kept."""

    #: Nodes looked at round a position for one in clear sight.
    NEAR = 6
    #: How far along a route a craft looks for the point to head for.
    LOOKAHEAD = 6

    def __init__(self, nodes, grid):
        self.grid = grid
        self.points = []
        index = {}
        for node in nodes:
            name = str(node.properties.get("name", "")).strip()
            if not name or name in index:
                continue
            index[name] = len(self.points)
            self.points.append((float(node.pos[0]), float(node.pos[2])))
        self.links = [set() for _ in self.points]
        for node in nodes:
            here = index.get(str(node.properties.get("name", "")).strip())
            if here is None:
                continue
            for name in str(node.properties.get("links", "") or "").split(","):
                there = index.get(name.strip())
                if there is not None and there != here:
                    self.links[here].add(there)
                    self.links[there].add(here)
        self._distances = {}

    @classmethod
    def of(cls, things, grid):
        """The graph of the ``levitatenode`` things among *things*, or None
        when there are too few to route over."""
        nodes = [t for t in things
                 if str(t.properties.get("type", "")).lower() == "levitatenode"]
        graph = cls(nodes, grid) if len(nodes) >= 2 else None
        return graph if graph is not None and any(graph.links) else None

    def __len__(self):
        return len(self.points)

    # -- nodes near a place ----------------------------------------------------
    def _near(self, x, z, leave=False):
        """``[(distance, node)]`` of the nodes in a clear line from ``(x, z)``,
        nearest first; the nearest node at all when none is."""
        points = self.points
        ranked = sorted((math.hypot(px - x, pz - z), i) for i, (px, pz) in enumerate(points))
        seen = [(d, i) for d, i in ranked[:self.NEAR]
                if self.grid.clear((x, z), points[i], leave=leave)]
        return seen or ranked[:1]

    def _goal(self, x, z):
        return self._near(x, z)[0][1]

    def _to(self, goal):
        """Shortest distance from every node to node *goal* (Dijkstra)."""
        known = self._distances.get(goal)
        if known is not None:
            return known
        import heapq
        points, links = self.points, self.links
        dist = [math.inf] * len(points)
        dist[goal] = 0.0
        queue = [(0.0, goal)]
        while queue:
            d, i = heapq.heappop(queue)
            if d > dist[i]:
                continue
            ix, iz = points[i]
            for j in links[i]:
                jx, jz = points[j]
                nd = d + math.hypot(jx - ix, jz - iz)
                if nd < dist[j]:
                    dist[j] = nd
                    heapq.heappush(queue, (nd, j))
        self._distances[goal] = dist
        return dist

    # -- routing -----------------------------------------------------------------
    def prepare(self, x, z):
        self._to(self._goal(x, z))

    def distance(self, gx, gz, x, z):
        goal = self._goal(gx, gz)
        dist = self._to(goal)
        gpx, gpz = self.points[goal]
        best = min((d + dist[i] for d, i in self._near(x, z, leave=True)), default=math.inf)
        return None if best == math.inf else best + math.hypot(gpx - gx, gpz - gz)

    def steer(self, gx, gz, x, z):
        grid = self.grid
        if grid.clear((x, z), (gx, gz), leave=True):
            return (gx, gz)
        goal = self._goal(gx, gz)
        dist = self._to(goal)
        points, links = self.points, self.links
        start = min(self._near(x, z, leave=True), key=lambda pair: pair[0] + dist[pair[1]])[1]
        if dist[start] == math.inf:
            return points[start]
        route = [start]
        current = start
        for _ in range(self.LOOKAHEAD):
            if current == goal:
                break
            cx, cz = points[current]
            current = min(links[current], key=lambda j: dist[j] + math.hypot(
                points[j][0] - cx, points[j][1] - cz))
            route.append(current)
        ahead = [points[i] for i in route]
        if current == goal:
            ahead.append((gx, gz))
        for point in reversed(ahead[1:]):
            if grid.clear((x, z), point, leave=True):
                return point
        return ahead[0]


# ---------------------------------------------------------------------------
# The rival craft
# ---------------------------------------------------------------------------
class Bot:
    """One rival craft: its Monster (what is drawn), its Player (what moves)
    and what it is doing."""

    def __init__(self, index, entity, actor, role, spawn):
        self.index = index
        self.entity = entity
        self.actor = actor
        self.role = role                   # "raider" / "defender"
        self.spawn = spawn                 # (x, y, z) feet: where it starts
        self.fallback = spawn              # its start in a maze without spawn points
        self.base = None                   # (x, z) where it takes a flag it holds
        self.carrying = None               # a home flag it holds
        self.target = None                 # the flag it is after
        self.patrol = None                 # (x, z) a defender is heading for
        self.raid_at = 0.0                 # when a raider may next set out
        self.stun_until = 0.0
        self.jammed_until = 0.0
        self.prev = (0.0, 0.0)
        self.state = "waiting"

    @property
    def name(self):
        return str(self.entity.properties.get("name", f"Rival {self.index + 1}"))

    def feet(self):
        p = self.actor.pos
        return (float(p[0]), float(p[1]) - self.actor.height / 2, float(p[2]))


class Squad:
    """The match's rival craft. Owned by the game host for one play session.

    :meth:`start` spawns them, :meth:`tick` runs them, :meth:`reset` puts them
    back at the start (R), and :meth:`stop` removes them from the scene.
    """

    def __init__(self, logic, count, seed=None):
        self.logic = logic
        self.count = max(0, min(MAX_BOTS, int(count)))
        self.rng = random.Random(seed)
        self.bots = []
        self.spawns = None
        #: Human craft playing from other computers (a multiplayer race):
        #: they take seats as this computer's own players do.
        self.remote_humans = 0
        self._pilots = []
        self.benched = []                  # rivals that gave a human their seat
        self.nav = None
        self.routes = None                 # NodeGraph, or GridRoutes without nodes
        self.barriers = []                 # [(x, z, until, prop or None)]
        self.clock = 0.0

    # -- life cycle ------------------------------------------------------------
    def start(self, match, spawns=None, occupied=()):
        """Put the rival craft in the maze, each on a spawn point of
        *spawns* (a :class:`game.spawns.SpawnPoints`) no craft at *occupied*
        is on, or round their flags in a maze without any. Returns how many
        came."""
        self.spawns = spawns if spawns else None
        if self.count <= 0 or not match.rival_flags:
            return 0
        logic = self.logic
        if getattr(getattr(logic, "player_runtime", None), "player", None) is None:
            return 0
        import glm
        from engine.player import Player
        try:
            from editor.things import Monster
        except ImportError:  # pragma: no cover - the Qt-free player
            from plugins.entitybase import Thing as Monster

        things = logic.editor_state.things
        self.nav = NavGrid(match.walls, match.bounds)
        self.routes = NodeGraph.of(things, self.nav) or GridRoutes(self.nav)
        starts = self._spawn_points(match)
        for i in range(self.count):
            x, y, z = starts[i]
            entity = Monster(pos=[x, y + SPRITE_SIZE / 2, z], properties={
                "name": f"Rival_{i + 1}", "monster_type": MONSTER_TYPE,
                "variant": "blue" if match.rival_team == "blue" else "<None>",
                "sprite_width": SPRITE_SIZE, "sprite_height": SPRITE_SIZE,
                "health": 100, "damage": 0, "awake": False, "wake_on_sight": False,
                # Stock Monster AI must not drive these craft as well.
                "disabled": True, "levitate_bot": True})
            actor = Player(x, z)
            actor.pos = glm.vec3(x, y + actor.height / 2 + 2.0, z)
            self._hover(actor)
            role = "defender" if i % 2 else "raider"
            bot = Bot(i, entity, actor, role, (x, y, z))
            self.bots.append(bot)
            things.append(entity)
        self._entities_changed()
        self.reset(match, occupied)
        # Humans already playing come first.
        self.seat(match, self.humans(), announce=False)
        # Fields for every place a craft heads for, while the maze loads
        # rather than in the middle of play.
        for flag in list(match.home_flags) + list(match.rival_flags):
            self.routes.prepare(flag.pos[0], flag.pos[2])
        return len(self.bots)

    def _spawn_points(self, match):
        """Feet positions round the rival flags, one per craft: where they
        start in a maze without spawn points."""
        points = []
        flags = list(match.rival_flags)
        for i in range(self.count):
            flag = flags[i % len(flags)]
            fx, fy, fz = flag.pos
            from .entities import FLAG_RAISE
            floor = fy - FLAG_RAISE
            ring = i // len(flags)
            angle = ring * 2.4 + i * 0.7
            reach = 0.0 if ring == 0 else 70.0 + 50.0 * ring
            x, z = fx + math.sin(angle) * reach, fz + math.cos(angle) * reach
            index = self.nav.nearest_free(x, z, reach=12)
            if index is not None:
                x, z = self.nav.centre(index)
            points.append((x, floor, z))
        return points

    @staticmethod
    def _hover(actor):
        """A craft glides: the engine's ground friction, scaled down as the
        player's is (game/hover.py). Thrust is set directly by the bot."""
        friction = type(actor)._apply_move_friction.__get__(actor)
        actor._apply_move_friction = lambda delta: friction(delta * 0.14)

    def reset(self, match, occupied=()):
        """Every craft to a spawn point no craft at *occupied* (the human
        craft) is on, flags it carried back home, raids timed from now."""
        self.clock = 0.0
        self._clear_barriers()
        raiders = 0
        taken = list(occupied)
        for bot in self.bots:
            if bot.carrying is not None:
                self._return_flag(match, bot, announce=False)
            self._deal(bot, taken)
            taken.append(bot.spawn)
            self._home(bot)
            if bot.role == "raider":
                bot.raid_at = RAID_START + RAID_STAGGER * raiders
                raiders += 1
            self._place(bot)

    def _deal(self, bot, occupied):
        """A start for *bot*: a spawn point nobody at *occupied* is on."""
        point = self.spawns.pick(occupied) if self.spawns else None
        bot.spawn = point[:3] if point is not None else bot.fallback

    def occupied(self, humans=()):
        """Where every craft is: *humans* and the rivals in play."""
        return list(humans) + [bot.feet() for bot in self.bots]

    def _home(self, bot):
        """*bot* at rest at its start, doing nothing yet."""
        import glm
        x, y, z = bot.spawn
        bot.actor.pos = glm.vec3(x, y + bot.actor.height / 2 + 2.0, z)
        bot.actor.velocity = glm.vec3(0.0)
        bot.actor.on_ground = False
        bot.actor.angle = math.atan2(-x, -z)          # towards the middle
        bot.prev = (0.0, 0.0)
        bot.target = bot.patrol = None
        bot.stun_until = bot.jammed_until = 0.0
        bot.state = "waiting"

    # -- seats -------------------------------------------------------------------
    def _human_positions(self):
        runtime = getattr(self.logic, "player_runtime", None)
        local = [tuple(float(v) for v in p.pos)
                 for p in (getattr(runtime, "player", None), getattr(runtime, "player2", None))
                 if p is not None]
        return local + [p.position for p in self._pilots[1:]]

    def humans(self):
        """How many human craft are playing: the player, and player 2 when
        split-screen is on."""
        runtime = getattr(self.logic, "player_runtime", None)
        local = (int(getattr(runtime, "player", None) is not None)
                 + int(getattr(runtime, "player2", None) is not None)) or 1
        return local + int(self.remote_humans)

    def seat(self, match, humans, announce=True):
        """Make the rivals fit beside *humans* human craft in
        :data:`MAX_CRAFT` seats: in a full match a rival leaves for each human
        that joins, and comes back when a human leaves. Returns how many
        rivals left (negative: came back)."""
        room = max(0, MAX_CRAFT - int(humans))
        change = 0
        while len(self.bots) > room:
            self._bench(match, self._leaver())
            change += 1
        while len(self.bots) < room and self.benched:
            self._unbench(min(self.benched, key=lambda b: b.index))
            change -= 1
        if change:
            self._entities_changed()
            if announce and match is not None and match.finished is None:
                _announce(match, "A PLAYER JOINED  —  A RIVAL MAKES ROOM" if change > 0
                          else "A RIVAL RETURNS TO THE MAZE", 2.5)
        return change

    def _leaver(self):
        """The rival that gives up its seat: one not holding a flag, a
        defender before a raider, the last to come first."""
        return max(self.bots, key=lambda b: (b.carrying is None, b.role == "defender", b.index))

    def _bench(self, match, bot):
        if bot.carrying is not None and match is not None:
            self._return_flag(match, bot, announce=False)
        self.bots.remove(bot)
        self.benched.append(bot)
        things = self.logic.editor_state.things
        if bot.entity in things:
            things.remove(bot.entity)

    def _unbench(self, bot):
        self.benched.remove(bot)
        self._deal(bot, self.occupied(self._human_positions()))
        self._home(bot)
        bot.raid_at = self.clock + RAID_REST
        self.bots.append(bot)
        self.bots.sort(key=lambda b: b.index)
        self.logic.editor_state.things.append(bot.entity)
        self._place(bot)

    def stop(self, match=None):
        """Take the rival craft out of the scene (and any flag they hold back
        to its pole)."""
        if match is not None:
            for bot in self.bots:
                if bot.carrying is not None:
                    self._return_flag(match, bot, announce=False)
        self._clear_barriers()
        things = getattr(getattr(self.logic, "editor_state", None), "things", None)
        if things is not None:
            for bot in self.bots + self.benched:
                if bot.entity in things:
                    things.remove(bot.entity)
        if self.bots:
            self._entities_changed()
        self.bots = []
        self.benched = []

    def _entities_changed(self):
        session = getattr(self.logic, "session_runtime", None)
        runtime = getattr(self.logic, "world_runtime", None)
        if runtime is None or not getattr(session, "play_mode", True):
            return
        try:
            runtime.build_entity_caches()
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[Levitate] rival craft not indexed: {exc}")

    # -- per tick ----------------------------------------------------------------
    def tick(self, match, pilots, dt, now, handling=None):
        """Run every craft for *dt* seconds against *pilots*, the human
        craft (:class:`Pilot`; the first is this computer's player). A bare
        PlayerState is taken as that player, with *handling* (its
        HoverHandling) for the bump flash."""
        if not isinstance(pilots, (list, tuple)):
            pilots = [self.local_pilot(match, pilots, now, handling)]
        player, handling = pilots, None
        if not self.bots and not self.benched:
            return
        dt = max(0.0, min(float(dt), 0.1))
        self.clock += dt
        self._expire_barriers(match)
        lock = getattr(getattr(self.logic, "session_runtime", None), "monster_lock", None)
        if lock is None:
            self._step(match, player, dt, now, handling)
        else:
            with lock:
                self._step(match, player, dt, now, handling)

    @staticmethod
    def local_pilot(match, player, now, handling=None):
        """This computer's player as a :class:`Pilot`."""
        def bonk():
            if handling is not None:
                handling.bonk = 0.25
        return Pilot(player, shielded=match.shield_until > now,
                     hidden=match.phantom_until > now, bonk=bonk)

    def _step(self, match, pilots, dt, now, handling):
        self._pilots = list(pilots)
        self.seat(match, self.humans())
        live = match.finished is None
        seen = [p.position for p in pilots if not p.hidden]
        for bot in self.bots:
            if live:
                goal = self._think(match, bot, seen)
            else:
                goal, bot.state = None, "idle"
            self._drive(bot, goal, dt)
        self._bump_craft()
        if live:
            for pilot in pilots:
                self._bump_player(match, pilot)
            for bot in self.bots:
                self._flags(match, bot)
        for bot in self.bots:
            self._place(bot)
            if bot.carrying is not None:
                self._carry(bot)

    # -- deciding --------------------------------------------------------------
    def _think(self, match, bot, seen):
        """Where *bot* is heading this tick, as ``(x, z, speed)``, or None."""
        if self.clock < bot.jammed_until:
            bot.state = "jammed"
            return None
        if self.clock < bot.stun_until:
            bot.state = "bumped"
            return None
        x, _y, z = bot.feet()
        nav = self.nav
        if bot.carrying is not None:
            bot.state = "carrying"
            return self._follow(bot.base[0], bot.base[1], x, z)
        if bot.role == "raider" and self.clock >= bot.raid_at:
            flag = self._raid_target(match, bot)
            if flag is not None:
                bot.target, bot.state = flag, "raiding"
                return self._follow(flag.pos[0], flag.pos[2], x, z)
        bot.target = None
        # Defend: ram the nearest pilot in sight (a phantom is not seen),
        # else patrol our own flags.
        for px, _py, pz in sorted(seen, key=lambda p: math.hypot(p[0] - x, p[2] - z)):
            if math.hypot(px - x, pz - z) >= SIGHT_RANGE:
                break
            if nav.sees((x, z), (px, pz)) and nav.clear((x, z), (px, pz)):
                bot.state = "chasing"
                return (px, pz, BOT_SPEED * 1.08)
        bot.state = "patrolling"
        if bot.patrol is None or math.hypot(bot.patrol[0] - x, bot.patrol[1] - z) < 120:
            bot.patrol = self._patrol_point(match, bot)
        if bot.patrol is None:
            return None
        goal = self._follow(bot.patrol[0], bot.patrol[1], x, z)
        if goal is not None:
            goal = (goal[0], goal[1], BOT_SPEED * 0.8)
        return goal

    def _follow(self, gx, gz, x, z):
        point = self.routes.steer(gx, gz, x, z)
        if point is None:
            return None
        return (point[0], point[1], BOT_SPEED)

    def _raid_target(self, match, bot):
        """The home flag *bot* should go for: its current one while it is
        still there, else the nearest no other raider is after."""
        standing = [f for f in match.home_flags
                    if id(f) not in match.lost and not any(b.carrying is f for b in self.bots)]
        if bot.target in standing:
            return bot.target
        taken = {id(b.target) for b in self.bots if b is not bot and b.target is not None}
        x, _y, z = bot.feet()
        best = None
        for flag in standing:
            fx, _fy, fz = flag.pos
            if not self.nav.reachable(fx, fz, FLAG_REACH):
                continue
            far = self.routes.distance(fx, fz, x, z)
            if far is None:
                continue
            score = far + (1e6 if id(flag) in taken else 0)
            if best is None or score < best[0]:
                best = (score, flag)
        return best[1] if best else None

    def _patrol_point(self, match, bot):
        flags = [f for f in match.rival_flags if id(f) not in match.taken]
        if not flags:
            flags = list(match.rival_flags)
        if not flags:
            return None
        flag = self.rng.choice(flags)
        angle = self.rng.uniform(0.0, math.tau)
        reach = self.rng.uniform(120.0, 420.0)
        x, z = flag.pos[0] + math.sin(angle) * reach, flag.pos[2] + math.cos(angle) * reach
        index = self.nav.nearest_free(x, z)
        return self.nav.centre(index) if index is not None else (flag.pos[0], flag.pos[2])

    # -- moving ------------------------------------------------------------------
    def _drive(self, bot, goal, dt):
        import glm
        actor = bot.actor
        vx, vz = float(actor.velocity.x), float(actor.velocity.z)
        if goal is not None and actor.on_ground:
            gx, gz, speed = goal
            x, _y, z = bot.feet()
            dx, dz = gx - x, gz - z
            reach = math.hypot(dx, dz)
            if reach > 1.0:
                dx, dz = dx / reach, dz / reach
                # Ease off for a sharp turn, and when arriving.
                current = math.hypot(vx, vz)
                if current > 1.0:
                    turn = (vx * dx + vz * dz) / current
                    speed *= 0.55 + 0.45 * max(0.0, turn)
                speed = min(speed, max(60.0, reach * 2.5))
                # Thrust against the error, so drift sideways is cancelled
                # as well as speed gained: the craft still glides, but where
                # it means to.
                ex, ez = dx * speed - vx, dz * speed - vz
                error = math.hypot(ex, ez)
                push = min(error, BOT_THRUST * dt)
                if error > 1e-6:
                    vx += ex / error * push
                    vz += ez / error * push
                actor.velocity.x, actor.velocity.z = vx, vz
        logic = self.logic
        actor.update(dt, glm.vec3(0.0), False, False,
                     logic.collision_runtime._collision_brushes_cache,
                     logic.mover_runtime._mover_brush_list,
                     logic.mover_runtime._door_brush_list,
                     logic.world_runtime.terrain,
                     spatial_grid=logic.session_runtime.spatial_grid)
        # The wall bounce the player's craft has (game/hover.py).
        nx, nz = float(actor.velocity.x), float(actor.velocity.z)
        px, pz = bot.prev
        if math.hypot(px, pz) > BOUNCE_FROM:
            hit_x = abs(px) > 120.0 and abs(nx) < abs(px) * 0.2
            hit_z = abs(pz) > 120.0 and abs(nz) < abs(pz) * 0.2
            if hit_x or hit_z:
                nx = -px * WALL_BOUNCE if hit_x else nx
                nz = -pz * WALL_BOUNCE if hit_z else nz
                actor.velocity.x, actor.velocity.z = nx, nz
        self._barrier_push(bot)
        bot.prev = (float(actor.velocity.x), float(actor.velocity.z))
        speed = math.hypot(bot.prev[0], bot.prev[1])
        if speed > 20.0:
            actor.angle = math.atan2(bot.prev[0], bot.prev[1])

    def _place(self, bot):
        """The billboard over the craft, facing where it is going."""
        from engine.change_journal import moved
        from engine.monster_facing import face_direction
        x, y, z = bot.feet()
        bot.entity.pos = [x, y + SPRITE_SIZE * (0.5 - SPRITE_DROP), z]
        moved(bot.entity)
        yaw = bot.actor.angle
        face_direction(bot.entity, (math.sin(yaw), 0.0, math.cos(yaw)))

    # -- contact -------------------------------------------------------------------
    @staticmethod
    def _collide(a_pos, a_vel, b_pos, b_vel, reach, a_heavy=False):
        """Elastic contact between two craft in the floor plane. Returns the
        new velocities ``(a, b)`` or None when they are not touching or are
        already parting."""
        dx, dz = a_pos[0] - b_pos[0], a_pos[2] - b_pos[2]
        d = math.hypot(dx, dz)
        if d >= reach:
            return None
        nx, nz = (dx / d, dz / d) if d > 1e-6 else (1.0, 0.0)
        closing = (a_vel[0] - b_vel[0]) * nx + (a_vel[2] - b_vel[2]) * nz
        if closing >= BUMP_SEPARATION:
            return None
        # Equal craft share the impulse; a shielded player gives nothing.
        want = max(-(1.0 + BUMP_RESTITUTION) * closing, BUMP_SEPARATION - closing)
        share_a = 0.0 if a_heavy else 0.5
        share_b = 1.0 - share_a
        a = (a_vel[0] + nx * want * share_a, a_vel[1], a_vel[2] + nz * want * share_a)
        b = (b_vel[0] - nx * want * share_b, b_vel[1], b_vel[2] - nz * want * share_b)
        return a, b

    def _bump_craft(self):
        bots = self.bots
        for i, a in enumerate(bots):
            for b in bots[i + 1:]:
                hit = self._collide(tuple(a.actor.pos), tuple(a.actor.velocity),
                                    tuple(b.actor.pos), tuple(b.actor.velocity),
                                    CRAFT_RADIUS * 2)
                if hit is not None:
                    a.actor.velocity.x, a.actor.velocity.z = hit[0][0], hit[0][2]
                    b.actor.velocity.x, b.actor.velocity.z = hit[1][0], hit[1][2]

    def _bump_player(self, match, pilot):
        for bot in self.bots:
            hit = self._collide(pilot.position, pilot.velocity,
                                tuple(bot.actor.pos), tuple(bot.actor.velocity),
                                CRAFT_RADIUS + PLAYER_RADIUS, a_heavy=pilot.shielded)
            if hit is None:
                continue
            pilot.velocity = hit[0]
            bot.actor.velocity.x, bot.actor.velocity.z = hit[1][0], hit[1][2]
            bot.stun_until = self.clock + BUMP_STUN
            if pilot.bonk is not None and not pilot.shielded:
                pilot.bonk()
            if bot.carrying is not None:
                self._return_flag(match, bot)

    # -- flags ---------------------------------------------------------------------
    def _flags(self, match, bot):
        x, y, z = bot.feet()
        if bot.carrying is not None:
            bx, bz = bot.base
            if math.hypot(bx - x, bz - z) <= BASE_REACH:
                self._deliver(match, bot)
            return
        flag = bot.target
        if flag is None or id(flag) in match.lost:
            return
        fx, fy, fz = flag.pos
        if math.hypot(fx - x, fz - z) <= FLAG_REACH and abs(fy - y) < 200:
            bot.carrying, bot.target = flag, None
            bot.base = self._base(match, bot)
            _glow(match, flag, False)
            _announce(match, "A RIVAL HAS YOUR FLAG  —  RAM IT TO WIN IT BACK", 3.0)

    def _base(self, match, bot):
        """Where *bot* takes a flag it has picked up: the nearest pole of its
        own team's flags, along the maze."""
        x, _y, z = bot.feet()
        best = None
        for flag in match.rival_flags:
            fx, _fy, fz = match.homes.get(id(flag), (tuple(flag.pos),))[0]
            far = self.routes.distance(fx, fz, x, z)
            if far is not None and (best is None or far < best[0]):
                best = (far, (fx, fz))
        return best[1] if best else (bot.spawn[0], bot.spawn[2])

    def _carry(self, bot):
        """A held flag rides above its craft."""
        from engine.change_journal import moved
        x, y, z = bot.feet()
        bot.carrying.pos = (x, y + SPRITE_SIZE * 0.55 + 60.0, z)
        moved(bot.carrying)

    def _return_flag(self, match, bot, announce=True):
        from engine.change_journal import moved
        flag, bot.carrying, bot.base = bot.carrying, None, None
        home = match.homes.get(id(flag))
        if home is not None:
            flag.pos = home[0]
            moved(flag)
        _glow(match, flag, True)
        if announce:
            _announce(match, "FLAG RECOVERED  —  IT IS BACK ON ITS POLE", 2.5)

    def _deliver(self, match, bot):
        from plugins.api import set_flag
        flag, bot.carrying, bot.base = bot.carrying, None, None
        match.lost.add(id(flag))
        set_flag(flag, "hidden", True)
        _glow(match, flag, False)
        bot.raid_at = self.clock + RAID_REST
        left = len(match.home_flags) - len(match.lost)
        if left:
            _announce(match, f"A {match.player_team.upper()} FLAG IS LOST  —  {left} LEFT", 3.0)
        else:
            match.finished, match.finished_at = "lost", _now()
            _announce(match, "THE RIVALS TOOK EVERY FLAG  —  PRESS R TO RETRY", 999)

    # -- power cells against rival craft -------------------------------------------
    def jam(self, pos):
        """A jammer goes off at *pos*: every rival craft within range drifts,
        engines dead, for a while. Returns how many were caught."""
        caught = 0
        for bot in self.bots:
            x, _y, z = bot.feet()
            if math.hypot(x - pos[0], z - pos[2]) <= JAM_RANGE:
                bot.jammed_until = self.clock + JAM_SECONDS
                caught += 1
        return caught

    def drop_barrier(self, pos, prop=None):
        """A barrier at *pos*: rival craft cannot cross it for a while."""
        self.barriers.append((float(pos[0]), float(pos[2]), self.clock + BARRIER_SECONDS, prop))

    def _barrier_push(self, bot):
        actor = bot.actor
        for bx, bz, _until, _prop in self.barriers:
            dx, dz = float(actor.pos.x) - bx, float(actor.pos.z) - bz
            d = math.hypot(dx, dz)
            reach = BARRIER_RADIUS + CRAFT_RADIUS
            if d >= reach:
                continue
            nx, nz = (dx / d, dz / d) if d > 1e-6 else (1.0, 0.0)
            inward = actor.velocity.x * nx + actor.velocity.z * nz
            if inward < 120.0:
                push = 120.0 - inward if inward >= 0 else 120.0 - (1.0 + WALL_BOUNCE) * inward
                actor.velocity.x += nx * push
                actor.velocity.z += nz * push

    def _expire_barriers(self, match):
        keep = []
        for barrier in self.barriers:
            if self.clock < barrier[2]:
                keep.append(barrier)
            else:
                self._remove_prop(barrier[3])
        self.barriers = keep

    def _clear_barriers(self):
        for barrier in self.barriers:
            self._remove_prop(barrier[3])
        self.barriers = []

    def _remove_prop(self, prop):
        if prop is None:
            return
        things = getattr(getattr(self.logic, "editor_state", None), "things", None)
        if things is not None and prop in things:
            things.remove(prop)
            self._entities_changed()

    # -- for the HUD -----------------------------------------------------------------
    def radar(self):
        """``[(x, z, carrying)]`` for every craft."""
        return [(float(b.actor.pos.x), float(b.actor.pos.z), b.carrying is not None)
                for b in self.bots]


def _announce(match, text, seconds=2.5):
    """Tell every pilot in the race (just :meth:`say` outside multiplayer)."""
    announce = getattr(match, "announce", None)
    (announce or match.say)(text, seconds)


def _now():
    import time
    return time.monotonic()


def _glow(match, flag, on):
    """A flag's light follows it: out while it is carried or lost."""
    from plugins.api import clear_flag, set_flag
    light = match.glows.get(str(flag.properties.get("name", "")))
    if light is None:
        return
    if on:
        clear_flag(light, "hidden")
    else:
        set_flag(light, "hidden", True)
