"""
Levitate! -- the built-in game layer of this Fio branch.

A hovercraft capture-the-flag game in walled mazes, made as a homage to the
1990s desktop maze-racers. Levitate is **not** a plugin: like MiniWind it is
loaded by name from ``[Startup] game_module`` in ``settings.ini`` and is always
active. Fio's engine and editor never import it.

* :func:`install` registers :data:`GAME` (the native game host) with Fio's
  plugin manager as a *built-in game*.
* :func:`show_launcher` is the first window after the splash: PLAY (straight
  into the game, fullscreen through kiosk mode), EDIT (the full Fio editor) or
  QUIT.
* :func:`launched_map` is the level the launcher's level select chose.
"""

from __future__ import annotations

import threading

_host_lock = threading.RLock()
_installed = False


def _game_host():
    """Load desktop wiring only when the application asks for its host."""
    with _host_lock:
        if "GAME" not in globals():
            from .host import LevitateGame
            globals()["LevitateGame"] = LevitateGame
            globals()["GAME"] = LevitateGame()
        return globals()["GAME"]


def __getattr__(name):
    if name in ("GAME", "LevitateGame"):
        _game_host()
        return globals()[name]
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def install() -> None:
    """Wire the built-in Levitate game into Fio's editor and engine.

    Idempotent and guarded: a failure here must never stop the editor from
    starting.
    """
    global _installed
    try:
        from plugins.manager import get_manager
        get_manager().register_builtin_game(_game_host())
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[Levitate] game host registration skipped: {exc}")
        return
    _installed = True


def show_launcher(root_directory, settings_path) -> str:
    """Levitate's startup launcher: ``"play"``, ``"edit"`` or ``"quit"``.

    Called by the application bootstrap (main.py) before the main window is
    built, when ``[Startup] show_launcher`` is on.
    """
    from .ui.launcher import launch
    return launch(root_directory, settings_path)


def launched_map():
    """The map (relative to the install folder) the launcher chose, or None."""
    from .ui.launcher import chosen_map
    return chosen_map()
