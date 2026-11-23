"""Rival craft on the real engine: how many the launcher asks for, how they
drive the maze, raid the player's flags, answer a ram and the power cells."""

import configparser
import math
import os

import pytest

pytestmark = pytest.mark.qt

import game
from game import bots
from game.ui import launcher

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAZE = "maps/levitate/Breakwater.json"
KEY_1, KEY_R = 0x31, 0x52


def _game():
    game.install()
    return game.GAME


def _play(fio_session, count=None, maze=MAZE):
    host = _game()
    editor = fio_session(maze)
    if count is not None:
        config = editor.window.config
        if not config.has_section("Game"):
            config.add_section("Game")
        config.set("Game", "bots", str(count))
    editor.start_play().step(2)
    return host, editor


def _rivals(editor):
    return [t for t in editor.state.things if t.properties.get("levitate_bot")]


def test_the_rival_count_setting():
    def config(text):
        parser = configparser.ConfigParser()
        parser.read_string(text)
        return parser
    assert bots.bots_from(config("")) == bots.DEFAULT_BOTS == 3
    assert bots.bots_from(config("[Game]\nbots = 5\n")) == 5
    assert bots.bots_from(config("[Game]\nbots = 0\n")) == 0
    assert bots.bots_from(config("[Game]\nbots = 99\n")) == bots.MAX_BOTS
    assert bots.bots_from(config("[Game]\nbots = -4\n")) == 0
    assert bots.bots_from(config("[Game]\nbots = lots\n")) == bots.DEFAULT_BOTS


def test_the_launcher_sets_how_many_rivals(tmp_path):
    settings = tmp_path / "settings.ini"
    settings.write_text("[Display]\nhud_size = compact\n")
    dialog = launcher.Launcher(ROOT, str(settings))
    assert dialog.bots_combo.currentData() == 3            # the default
    assert dialog.bots_combo.itemData(0) == 0              # none: a time trial
    assert dialog.bots_combo.itemData(dialog.bots_combo.count() - 1) == bots.MAX_BOTS
    dialog.bots_combo.setCurrentIndex(dialog.bots_combo.findData(6))

    def saved():
        parser = configparser.ConfigParser()
        parser.read(settings)
        return bots.bots_from(parser)

    assert saved() == 6
    dialog._reset()
    assert saved() == 3 and dialog.bots_combo.currentData() == 3
    dialog.close()
    # The next launch shows what was chosen last.
    settings.write_text("[Game]\nbots = 1\n")
    dialog = launcher.Launcher(ROOT, str(settings))
    assert dialog.bots_combo.currentData() == 1
    dialog.close()


def test_a_match_starts_with_three_rivals_by_default(fio_session):
    host, editor = _play(fio_session)
    rivals = _rivals(editor)
    assert len(rivals) == 3 and len(host.squad.bots) == 3
    for craft in rivals:
        props = craft.properties
        assert props["monster_type"] == "hovercraft" and props["variant"] == "blue"
        assert props["disabled"], "stock monster AI must leave the rivals alone"
    # They start in the rival half, at the rival flags, not on the player.
    px, _py, pz = host.api.player.position
    for bot in host.squad.bots:
        x, _y, z = bot.feet()
        assert math.hypot(x - px, z - pz) > 1500.0
    assert len(host.match.rivals) == 3
    editor.stop_play()
    assert not _rivals(editor) and host.squad is None


@pytest.mark.parametrize("count", [0, 1, 5])
def test_a_match_starts_with_the_launchers_number_of_rivals(fio_session, count):
    host, editor = _play(fio_session, count)
    assert len(_rivals(editor)) == count
    assert (host.squad is None) if count == 0 else (len(host.squad.bots) == count)
    editor.stop_play()
    assert not _rivals(editor)


def test_rivals_drive_the_maze_without_leaving_it(fio_session):
    host, editor = _play(fio_session, 4)
    squad = host.squad
    assert isinstance(squad.routes, bots.NodeGraph), "the maze's nodes are not used"
    starts = [bot.feet() for bot in squad.bots]
    travelled = [0.0] * len(starts)
    last = [s for s in starts]
    for _ in range(12):
        editor.step(30)
        for i, bot in enumerate(squad.bots):
            here = bot.feet()
            travelled[i] += math.hypot(here[0] - last[i][0], here[2] - last[i][2])
            last[i] = here
    # Six seconds of cruising, not sitting at a wall.
    assert min(travelled) > 600.0, travelled
    x0, z0, x1, z1 = host.match.bounds
    for bot, start in zip(squad.bots, starts):
        x, y, z = bot.feet()
        assert x0 < x < x1 and z0 < z < z1 and abs(y - start[1]) < 40.0
        assert not squad.nav.solid[squad.nav.cell(x, z)], "a rival is inside a wall"
        # The billboard follows the craft.
        assert math.hypot(bot.entity.pos[0] - x, bot.entity.pos[2] - z) < 1.0
    editor.stop_play()


def test_a_raider_takes_a_flag_and_a_ram_wins_it_back(fio_session, monkeypatch):
    monkeypatch.setattr(bots, "RAID_START", 0.0)
    host, editor = _play(fio_session, 1)
    match, bot = host.match, host.squad.bots[0]
    player = host.api.player
    for _ in range(60 * 60):
        editor.step(1)
        if bot.carrying is not None:
            break
    flag = bot.carrying
    assert flag is not None, (bot.state, bot.feet())
    home = match.homes[id(flag)][0]
    editor.step(90)
    assert math.hypot(flag.pos[0] - home[0], flag.pos[2] - home[2]) > 150.0, \
        "the flag rides on the raider"
    # Ram the carrier.
    x, y, z = bot.feet()
    player.teleport((x - 60.0, y + 50.0, z), velocity=(400.0, 0.0, 0.0))
    editor.step(2)
    assert bot.carrying is None
    assert tuple(flag.pos) == tuple(home) and not flag.properties.get("hidden")
    assert not match.lost and match.finished is None
    editor.stop_play()


def test_rivals_delivering_every_flag_lose_the_match_and_r_restarts(fio_session):
    host, editor = _play(fio_session, 1)
    match, squad = host.match, host.squad
    bot = squad.bots[0]
    for flag in match.home_flags:
        bot.target = flag
        squad._flags(match, _At(bot, flag.pos))
        assert bot.carrying is flag
        squad._flags(match, _At(bot, bot.spawn))
        assert bot.carrying is None and id(flag) in match.lost
        assert flag.properties.get("hidden")
    assert match.finished == "lost"
    editor.step(5, keys={KEY_R})
    assert host.match is not match and host.match.finished is None
    assert not any(f.properties.get("hidden") for f in host.match.home_flags)
    x, _y, z = bot.feet()
    assert math.hypot(x - bot.spawn[0], z - bot.spawn[2]) < 60.0
    editor.stop_play()


class _At:
    """A bot as seen from *pos*: for driving the flag rules directly."""

    def __init__(self, bot, pos):
        self._bot, self._pos = bot, pos

    def __getattr__(self, name):
        return getattr(self._bot, name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._bot, name, value)

    def feet(self):
        x, y, z = self._pos
        return (x, self._bot.feet()[1], z)


def test_a_jammer_stalls_the_rivals(fio_session):
    host, editor = _play(fio_session, 3)
    match = host.match
    editor.step(60)
    bot = host.squad.bots[0]
    # Bring the player near the rivals and fire the jammer.
    x, y, z = bot.feet()
    host.api.player.teleport((x + 300.0, y + 60.0, z))
    match.slots[0] = "jammer"
    editor.step(1, keys={KEY_1})
    assert match.slots[0] is None and "STALLED" in match.message
    editor.step(1)
    jammed = [b for b in host.squad.bots if b.state == "jammed"]
    assert bot in jammed
    speed = math.hypot(bot.actor.velocity.x, bot.actor.velocity.z)
    editor.step(60)
    assert bot.state == "jammed"
    assert math.hypot(bot.actor.velocity.x, bot.actor.velocity.z) <= max(speed, 5.0)
    editor.step(int(bots.JAM_SECONDS * 60))
    assert bot.state != "jammed"
    editor.stop_play()


def test_a_phantom_hides_the_player_from_a_defender(fio_session):
    host, editor = _play(fio_session, 2)
    match, squad = host.match, host.squad
    defender = next(b for b in squad.bots if b.role == "defender")
    x, y, z = defender.feet()
    # Somewhere in the defender's open sight, a little way off.
    spot = next(p for p in ((x + d * dx, z + d * dz) for d in (260.0, 200.0, 150.0)
                            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                if squad.nav.clear((x, z), p))
    host.api.player.teleport((spot[0], y + 60.0, spot[1]))
    editor.step(2)
    assert defender.state == "chasing"
    match.phantom_until = 1e12
    editor.step(2)
    assert defender.state != "chasing"
    editor.stop_play()


def test_a_barrier_turns_rivals_back_and_goes_away(fio_session):
    host, editor = _play(fio_session, 1)
    squad, match = host.squad, host.match
    bot = squad.bots[0]
    x, y, z = bot.feet()
    host.api.player.teleport((x, y + 60.0, z))
    match.slots[0] = "barrier"
    editor.step(1, keys={KEY_1})
    assert len(squad.barriers) == 1
    prop = squad.barriers[0][3]
    assert prop is not None and prop in editor.state.things
    # Move the player away; the craft is pushed out of the barrier (as far as
    # the walls of its corner let it) and never back in.
    host.api.player.teleport((x + 900.0, y + 60.0, z))
    bx, bz = squad.barriers[0][0], squad.barriers[0][1]
    closest = 1e9
    for _ in range(120):
        editor.step(1)
        fx, _fy, fz = bot.feet()
        if _ >= 60:
            closest = min(closest, math.hypot(fx - bx, fz - bz))
    assert closest > 80.0, closest
    editor.step(int(bots.BARRIER_SECONDS * 60))
    assert not squad.barriers and prop not in editor.state.things
    editor.stop_play()


def test_nav_grid_finds_a_way_round_walls():
    # A wall across the middle with a gap at the top.
    walls = [(-24.0, -1000.0, 24.0, 600.0)]
    nav = bots.NavGrid(walls, (-1000.0, -1000.0, 1000.0, 1000.0))
    field = nav.field(600.0, 0.0)
    assert nav.distance(field, -600.0, 0.0) is not None
    assert not nav.clear((-600.0, 0.0), (600.0, 0.0))
    point = nav.steer(field, -600.0, 0.0)
    # The first leg heads up towards the gap, not into the wall.
    assert point[1] > 0.0 and point[0] < -24.0
    assert nav.sees((-600.0, 900.0), (600.0, 900.0))
    assert not nav.sees((-600.0, 0.0), (600.0, 0.0))


# -- navigation nodes in the mazes ------------------------------------------------
MAZES = sorted(f"maps/levitate/{n}" for n in os.listdir(os.path.join(ROOT, "maps", "levitate"))
               if n.endswith(".json") and not n.startswith("_"))


def _graph_of(data):
    """The maze's node graph and wall grid, as a match builds them."""
    import json
    from types import SimpleNamespace
    from game.entities import LevitateNode
    from game.host import LevitateGame
    if isinstance(data, str):
        data = json.load(open(os.path.join(ROOT, data)))
    logic = SimpleNamespace(editor_state=SimpleNamespace(brushes=data["brushes"]))
    walls, bounds = LevitateGame._radar_walls(logic)
    grid = bots.NavGrid(walls, bounds)
    nodes = [LevitateNode(t["pos"], t["properties"]) for t in data["things"]
             if t["type"] == "levitatenode"]
    return data, nodes, bots.NodeGraph.of(nodes, grid), grid


@pytest.mark.parametrize("maze", MAZES)
def test_every_maze_has_navigation_nodes(maze):
    data, nodes, graph, grid = _graph_of(maze)
    assert graph is not None and len(graph) == len(nodes) >= 50
    names = {n.properties["name"] for n in nodes}
    for node in nodes:
        x, y, z = node.pos
        assert grid.free(x, z), f"{node.properties['name']} is in a wall's margin"
        for other in filter(None, node.properties["links"].split(",")):
            assert other in names
    # Every link is a straight, clear run, and both ends know it.
    for i, links in enumerate(graph.links):
        for j in links:
            assert i in graph.links[j]
            assert grid.clear(graph.points[i], graph.points[j]), (i, j)
    # One connected network: every node can be reached from every other.
    assert all(d < math.inf for d in graph._to(0))
    # Every flag can be reached along it, and every flag cell has a node.
    for thing in data["things"]:
        if thing["type"] != "levitateflag":
            continue
        fx, _fy, fz = thing["pos"]
        assert graph.distance(fx, fz, *graph.points[0]) is not None
        assert min(math.hypot(px - fx, pz - fz) for px, pz in graph.points) < 1.0


def test_random_mazes_have_navigation_nodes_too():
    from game import random_maze
    for world in random_maze.WORLDS:
        data = random_maze.generate(dict(world=world, cols=6, rows=7, ledges=2, seed=77))
        _data, nodes, graph, _grid = _graph_of(data)
        ledges = sum(1 for b in data["brushes"] if b["name"].startswith("Ledge_"))
        assert len(nodes) == 6 * 7 - ledges and graph is not None
        assert all(d < math.inf for d in graph._to(0))


def test_a_maze_without_nodes_still_has_rivals_that_drive(fio_session):
    """Nodes are how the shipped mazes are driven; a hand-built maze without
    any falls back to steering by its walls."""
    import json
    data = json.load(open(os.path.join(ROOT, MAZE)))
    data["things"] = [t for t in data["things"] if t["type"] != "levitatenode"]
    host = _game()
    editor = fio_session(data)
    editor.start_play().step(2)
    squad = host.squad
    assert isinstance(squad.routes, bots.GridRoutes) and len(squad.bots) == 3
    starts = [bot.feet() for bot in squad.bots]
    editor.step(240)
    assert max(math.hypot(b.feet()[0] - s[0], b.feet()[2] - s[2])
               for b, s in zip(squad.bots, starts)) > 300.0
    editor.stop_play()
