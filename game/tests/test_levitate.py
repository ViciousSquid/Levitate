"""Levitate on the real engine: every maze loads, plays, glides and scores."""

import json
import math
import os

import pytest

pytestmark = pytest.mark.qt

import game
from game.ui import launcher
from plugins.manager import get_manager

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAZES = sorted(f"maps/levitate/{n}" for n in os.listdir(os.path.join(ROOT, "maps", "levitate"))
               if n.endswith(".json") and not n.startswith("_"))
KEY_W = 0x57


def _game():
    game.install()
    return game.GAME


def test_mazes_are_listed_in_order():
    titles = [title for _rel, title in launcher.maze_choices(ROOT)]
    assert titles == ["Breakwater", "Sandglass", "Mossgarden", "Frostline", "Emberworks"]


@pytest.mark.parametrize("maze", MAZES)
def test_maze_data_is_complete(maze):
    data = json.load(open(os.path.join(ROOT, maze)))
    kinds = [t["type"] for t in data["things"]]
    assert kinds.count("levitaterules") == 1
    assert kinds.count("playerstart") == 1
    teams = [t["properties"]["team"] for t in data["things"] if t["type"] == "levitateflag"]
    assert teams.count("red") == 3 and teams.count("blue") == 3
    for brush in data["brushes"]:
        for texture in brush["textures"].values():
            assert os.path.isfile(os.path.join(ROOT, "assets", "textures", texture)), texture


@pytest.mark.parametrize("maze", MAZES)
def test_maze_plays_and_the_craft_glides(fio_session, maze):
    host = _game()
    assert host in get_manager()._builtin_games
    editor = fio_session(maze)
    editor.start_play().step(30)
    match = host.match
    assert match is not None and len(match.rival_flags) == 3
    assert match.walls, "the radar has no walls"
    player = host.api.player
    # Thrust, then let go: a hovercraft keeps gliding where a walker stops.
    editor.step(20, keys={KEY_W})
    moving = math.hypot(player.velocity[0], player.velocity[2])
    assert moving > 150.0
    # Coast for a sixth of a second: a walker would have stopped by now.
    editor.step(10)
    coasting = math.hypot(player.velocity[0], player.velocity[2])
    assert coasting > moving * 0.8, (moving, coasting)
    editor.stop_play()
    assert host.handling is None


def test_wall_hit_at_speed_bounces_back(fio_session):
    host = _game()
    editor = fio_session(MAZES[0])
    editor.start_play().step(10)
    player = host.api.player
    # Fly west at speed into the outer wall from just inside it.
    bounds = host.match.bounds
    x, y, z = player.position
    player.teleport((bounds[0] + 150.0, y, z), velocity=(-420.0, 0.0, 0.0))
    for _ in range(30):
        editor.step(1)
        if player.velocity[0] > 0.0:
            break
    assert player.velocity[0] > 100.0, player.velocity
    editor.stop_play()


def test_taking_every_rival_flag_wins(fio_session):
    host = _game()
    editor = fio_session(MAZES[0])
    editor.start_play().step(10)
    match = host.match
    player = host.api.player
    for flag in match.rival_flags:
        x, y, z = flag.pos
        player.teleport((x, y + 30, z))
        editor.step(3)
        assert flag.properties.get("hidden")
    assert match.finished == "win"
    editor.stop_play()
    # Stopping play puts the flags back as authored.
    assert not any(f.properties.get("hidden") for f in match.rival_flags)


def test_spring_pad_launches_and_orb_fills_a_slot(fio_session):
    host = _game()
    editor = fio_session(MAZES[0])
    editor.start_play().step(10)
    player = host.api.player
    spring = next(p for p in host.api.entities_of_type("levitatepad")
                  if p.properties["kind"] == "spring")
    x, y, z = spring.pos
    player.teleport((x, y + 26, z))
    editor.step(2)
    assert player.velocity[1] > 200.0
    orb = next(iter(host.api.entities_of_type("levitatepickup")))
    x, y, z = orb.pos
    player.teleport((x, y, z))
    editor.step(2)
    assert orb.properties["kind"] in host.match.slots
    editor.stop_play()


def test_hud_sizes_compact_and_the_original_large():
    from PyQt5.QtGui import QImage, QPainter
    from game.host import MatchState
    from game.ui.hud import Hud

    def dashboard_span(size, w=1600, h=900):
        image = QImage(w, h, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        Hud(size).draw(painter, w, h, MatchState(None, "red"))
        painter.end()
        row = h - 4                    # the dashboard's bottom edge
        lit = [x for x in range(w) if image.pixelColor(x, row).alpha() > 0]
        return lit[0], lit[-1]

    assert dashboard_span("large") == (0, 1599)          # the original: edge to edge
    left, right = dashboard_span("compact")
    assert abs((right - left + 1) - 960) <= 2            # 60% of the width, centred
    assert abs(left - (1600 - right - 1)) <= 2


def test_hud_size_setting_in_launcher_and_pause_menu(tmp_path):
    import configparser
    from game.ui.hud import hud_size_from
    settings = tmp_path / "settings.ini"
    settings.write_text("[Display]\nhud_size = compact\n")
    dialog = launcher.Launcher(ROOT, str(settings))
    assert dialog.hud_combo.currentData() == "compact"
    dialog.hud_combo.setCurrentIndex(dialog.hud_combo.findData("large"))
    config = configparser.ConfigParser()
    config.read(settings)
    assert hud_size_from(config) == "large"
    dialog.close()

    host = _game()
    labels = [label for label, _cb, _close in get_manager().pause_menu_items()
              if callable(label)]
    item = next(label for label in labels if "HUD Size" in label())

    class Window:
        def __init__(self):
            self.config = configparser.ConfigParser()
            self.saved = 0

        def save_config(self):
            self.saved += 1

    window = Window()
    host._hud = None
    host._cycle_hud_size(window, None)
    assert item() == "HUD Size: Large"
    assert window.config.get("Display", "hud_size") == "large" and window.saved == 1
    host._cycle_hud_size(window, None)
    assert item() == "HUD Size: Compact"


@pytest.mark.parametrize("maze", MAZES)
def test_geometry_scales_but_pads_and_orbs_do_not(maze):
    from game.tools import make_mazes
    data = json.load(open(os.path.join(ROOT, maze)))
    brushes = {b["name"]: b for b in data["brushes"]}
    assert brushes["Wall_North"]["size"][1] == make_mazes.WALL_H
    for name, brush in brushes.items():
        if name.startswith("Pad_"):
            assert brush["size"] == [112, 4, 112], name


def test_a_ledge_spring_clears_the_scaled_ledge(fio_session):
    from game.tools import make_mazes
    host = _game()
    editor = fio_session(MAZES[0])
    editor.start_play().step(10)
    player = host.api.player
    spring = next(p for p in host.api.entities_of_type("levitatepad")
                  if p.properties["name"].startswith("Spring_L"))
    x, y, z = spring.pos
    player.teleport((x, y + 26, z))
    floor_y = None
    peak = -1e9
    for _ in range(60):
        editor.step(1)
        feet = player.position[1] - player.size[1] / 2
        floor_y = feet if floor_y is None else min(floor_y, feet)
        peak = max(peak, feet)
    assert peak - floor_y > make_mazes.LEDGE_H, (peak, floor_y)
    editor.stop_play()


@pytest.mark.parametrize("maze", MAZES)
def test_flags_and_orbs_stand_above_the_floor(maze):
    """Billboards are centred on their position: none may dip into the floor."""
    from game.entities import FLAG_SIZE
    data = json.load(open(os.path.join(ROOT, maze)))
    floor_top = next(b for b in data["brushes"] if b["name"] == "Floor")
    floor_top = floor_top["pos"][1] + floor_top["size"][1] / 2
    for thing in data["things"]:
        if thing["type"] == "levitateflag":
            half = FLAG_SIZE[1] / 2
        elif thing["type"] == "levitatepickup":
            half = 28
        else:
            continue
        assert thing["pos"][1] - half >= floor_top, thing["properties"]["name"]


def test_hovercraft_monster_has_eight_views_per_team():
    from editor.things import Monster
    from engine import monster_constants as mc
    _game()
    assert "hovercraft" in mc.MONSTER_TYPES and "blue" in mc.MONSTER_VARIANTS["hovercraft"]
    base = os.path.join(ROOT, "assets", "sprites", "monsters", "hovercraft")
    for folder in (base, os.path.join(base, "blue")):
        for state in ("idle", "shoot"):
            for view in range(1, 9):
                assert os.path.isfile(os.path.join(folder, f"{state}_{view}.png"))
        assert os.path.isfile(os.path.join(folder, "dead.png"))
    red = Monster(properties={"monster_type": "hovercraft"})
    blue = Monster(properties={"monster_type": "hovercraft", "variant": "blue"})
    assert red.properties["monster_type"] == "hovercraft"
    assert blue.properties["variant"] == "blue"
    idle, _dead, _shoot = Monster._get_default_paths("hovercraft", "blue")
    assert idle == "assets/sprites/monsters/hovercraft/blue/idle.png"


# -- worlds, lighting and materials ---------------------------------------------
def test_every_world_has_its_own_look_and_materials():
    """Five worlds: each maze's theme has a lighting preset of its own, its
    own walls and floor, and every material comes with the maps a physically
    shaded frame reads."""
    from game import graphics, random_maze
    themes = []
    for maze in MAZES:
        data = json.load(open(os.path.join(ROOT, maze)))
        rules = next(t for t in data["things"] if t["type"] == "levitaterules")
        themes.append(rules["properties"]["theme"])
    assert sorted(themes) == sorted(graphics.THEMES) == sorted(random_maze.WORLDS)
    looks = [tuple(sorted(graphics.THEMES[t].items())) for t in themes]
    assert len(set(looks)) == len(looks)
    folder = os.path.join(ROOT, "assets", "textures", "levitate")
    for theme in themes:
        for name in (f"wall_{theme}", f"floor_{theme}"):
            for suffix in ("", "_n", "_m", "_h"):
                assert os.path.isfile(os.path.join(folder, f"{name}{suffix}.jpg")), name + suffix


def test_a_match_lights_its_world_and_puts_fio_back():
    """The match switches the renderer's environment on with the maze's
    theme; outside play, and at the classic quality, it is Fio's own."""
    from engine.renderer.forward.environment import Environment
    from game import graphics

    class Renderer:
        surface_shading = True

        def __init__(self):
            self.environment = Environment()

    renderer = Renderer()
    assert graphics.apply(renderer, "ember", "high", focus=(-10, -10, 10, 10))
    env = renderer.environment
    assert env.enabled and env.shadow_focus == (-10.0, -10.0, 10.0, 10.0)
    assert env.sky_intensity == graphics.THEMES["ember"]["sky_intensity"]
    low = Renderer()
    graphics.apply(low, "ember", "low")
    assert low.environment.enabled and not low.environment.reflections
    assert low.environment.shadow_size < env.shadow_size
    assert not graphics.apply(renderer, "ember", "classic") and not env.enabled
    graphics.apply(renderer, "slate", "ultra")
    graphics.clear(renderer)
    assert not env.enabled

    host = _game()
    host.match = None
    host._lit = None
    host._light_scene({"renderer": renderer, "play_mode": True})
    assert not env.enabled                      # no match: nothing to light


def test_fill_lights_go_out_in_a_lit_match_and_come_back(fio_session):
    from game import graphics
    host = _game()
    editor = fio_session(MAZES[0])
    fills = [t for t in editor.state.things if t.properties.get(graphics.FILL_LIGHT)]
    assert fills
    editor.start_play().step(3)
    assert host._quality != "classic"
    assert all(t.properties.get("hidden") for t in fills)
    editor.stop_play()
    assert not any(t.properties.get("hidden") for t in fills)


def test_cells_spin_and_their_glow_follows_them(fio_session):
    host = _game()
    editor = fio_session(MAZES[0])
    cell = next(t for t in editor.state.things
                if str(t.properties.get("type")) == "levitatepickup")
    home, yaw = tuple(cell.pos), cell.properties["rotation"][1]
    editor.start_play().step(20)
    assert cell.properties["rotation"][1] != yaw
    glow = host.match.glows[cell.properties["name"]]
    player = host.api.player
    player.teleport(tuple(cell.pos))
    editor.step(3)
    assert cell.properties.get("hidden") and glow.properties.get("hidden")
    editor.stop_play()
    assert tuple(cell.pos) == home and cell.properties["rotation"][1] == yaw
    assert not glow.properties.get("hidden")


def test_scenery_stands_outside_the_maze_and_off_the_radar(fio_session):
    host = _game()
    editor = fio_session(MAZES[0])
    editor.start_play().step(2)
    x0, z0, x1, z1 = host.match.bounds
    scenery = [b for b in editor.state.brushes if str(b.get("name", "")).startswith("Scenery_")]
    assert scenery
    for brush in scenery:
        x, _y, z = brush["pos"]
        assert not (x0 < x < x1 and z0 < z < z1), brush["name"]
    editor.stop_play()


# -- random mazes -----------------------------------------------------------------
def test_random_mazes_are_complete_in_every_world_and_size():
    import random
    from game import random_maze
    rng = random.Random(11)
    for index in range(40):
        params = dict(world=list(random_maze.WORLDS)[index % 5], cols=rng.randint(5, 16),
                      rows=rng.randint(5, 16), loops=rng.randint(0, 40),
                      plazas=rng.randint(0, 6), ledges=rng.randint(0, 5),
                      seed=rng.randint(1, 999999))
        data = random_maze.generate(params)
        kinds = [t["type"] for t in data["things"]]
        assert kinds.count("levitaterules") == 1 and kinds.count("playerstart") == 1
        teams = [t["properties"]["team"] for t in data["things"] if t["type"] == "levitateflag"]
        assert teams.count("red") == 3 and teams.count("blue") == 3, params
        rules = next(t for t in data["things"] if t["type"] == "levitaterules")
        assert rules["properties"]["theme"] == params["world"]
        assert data == random_maze.generate(params), "the same seed is the same maze"


def test_the_editors_generator_makes_levitate_mazes(fio_session):
    """Fio's random level generator, repurposed: its settings are a maze's,
    out-of-range values from map data are brought into range, and what it
    makes plays as a match."""
    import random
    from editor.procedural_generator import PARAM_LIMITS, create_map_data, sanitize_params
    clean = sanitize_params({"cols": 999, "rows": "junk", "world": "nowhere", "loops": -5})
    assert clean["cols"] == PARAM_LIMITS["cols"][1] and clean["loops"] == 0
    assert clean["world"] == "random" and clean["rows"] == 9
    random.seed(5)
    first = create_map_data({"world": "frost", "cols": 6, "rows": 5})
    random.seed(5)
    assert first == create_map_data({"world": "frost", "cols": 6, "rows": 5})
    host = _game()
    editor = fio_session(first)
    editor.start_play().step(5)
    assert host.match is not None and len(host.match.rival_flags) == 3
    assert host.match.theme == "frost"
    editor.stop_play()


def test_the_launcher_offers_a_random_maze_and_a_graphics_setting(tmp_path):
    import configparser
    import shutil
    from game import graphics, random_maze
    root = tmp_path / "install"
    shutil.copytree(os.path.join(ROOT, "maps", "levitate"), root / "maps" / "levitate",
                    ignore=shutil.ignore_patterns("_*"))
    shutil.copytree(os.path.join(ROOT, "assets", "textures", "levitate"),
                    root / "assets" / "textures" / "levitate",
                    ignore=shutil.ignore_patterns("*.jpg", "*.png"))
    settings = tmp_path / "settings.ini"
    settings.write_text("[Display]\nhud_size = compact\n")
    dialog = launcher.Launcher(str(root), str(settings))
    assert dialog.graphics_combo.currentData() == graphics.DEFAULT_QUALITY
    dialog.graphics_combo.setCurrentIndex(dialog.graphics_combo.findData("classic"))
    config = configparser.ConfigParser()
    config.read(settings)
    assert graphics.quality_from(config) == "classic"
    dialog.maze_combo.setCurrentIndex(dialog.maze_combo.findData(launcher.RANDOM_MAZE))
    dialog._finish(launcher.PLAY)
    chosen = launcher.chosen_map()
    assert chosen == random_maze.RANDOM_FILE.replace(os.sep, "/")
    data = json.load(open(root / chosen))
    assert [t["type"] for t in data["things"]].count("levitaterules") == 1
    # The random maze's own file is not one of the mazes to choose from.
    assert len(launcher.maze_choices(str(root))) == 5
