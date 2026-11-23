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
               if n.endswith(".json"))
KEY_W = 0x57


def _game():
    game.install()
    return game.GAME


def test_mazes_are_listed_in_order():
    titles = [title for _rel, title in launcher.maze_choices(ROOT)]
    assert titles == ["Breakwater", "Sandglass", "Mossgarden"]


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
