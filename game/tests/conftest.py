"""Levitate's tests register the built-in game with Fio's process-wide plugin
manager; each test puts the manager back as it found it, so Fio's own tests
that run after them see a stock engine (no Levitate pause-menu item)."""

import pytest


@pytest.fixture(autouse=True)
def _builtin_game_registration_undone():
    from plugins.manager import get_manager
    manager = get_manager()
    games = list(manager._builtin_games)
    items = list(manager._pause_menu_items)
    yield
    manager._builtin_games[:] = games
    manager._pause_menu_items[:] = items
