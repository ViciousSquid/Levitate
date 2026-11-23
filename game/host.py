"""Levitate's native game host: the play lifecycle Fio drives every tick.

Registered with Fio's plugin manager as a *built-in game* (``game.install``),
so it has a plugin's lifecycle -- register, register_runtime, connect,
on_play_start, on_tick, on_play_stop -- without appearing in the Plugins menu.

The match: every maze has a :class:`~game.entities.LevitateRules`. The player
races to collect every rival-team flag before the clock runs out, while rival
craft (game/bots.py; how many is the launcher's choice) try to carry off the
player's own. Floor pads launch (spring), boost or load a barrier; power-up
orbs fill the dashboard's three system slots (1/2/3 to use).
"""

from __future__ import annotations

import math
import time

from . import bots, graphics
from .entities import ENTITIES, POWERUPS, LevitateBarrier
from .hover import HoverHandling

FLAG_REACH = 72.0          # how close the craft must come to take a flag
PICKUP_REACH = 64.0
SLOT_COUNT = 3
SHIELD_SECONDS = 12.0
PHANTOM_SECONDS = 10.0
BOOST_SECONDS = 2.5
PAD_COOLDOWN = 0.6


class MatchState:
    """One play session's match: plain data, read by the HUD each frame."""

    def __init__(self, rules, player_team):
        props = rules.properties if rules is not None else {}
        self.title = str(props.get("title", "Maze"))
        self.time_limit = float(props.get("time_limit", 300.0) or 0.0)
        self.player_team = "blue" if player_team == "blue" else "red"
        self.rival_team = "red" if self.player_team == "blue" else "blue"
        self.started = time.monotonic()
        self.finished = None           # "win" / "timeout" / "lost"
        self.finished_at = None
        self.rival_flags = []          # [entity]
        self.home_flags = []
        self.taken = set()             # ids of rival flags collected
        self.lost = set()              # ids of home flags the rivals delivered
        self.slots = [None] * SLOT_COUNT
        self.shield_until = 0.0
        self.phantom_until = 0.0
        self.message = ""
        self.message_until = 0.0
        self.pad_ready = {}            # pad id -> monotonic time
        self.pickup_back = {}          # pickup id -> monotonic time it returns
        self.walls = []                # [(x0, z0, x1, z1)] for the radar
        self.bounds = (-1000.0, -1000.0, 1000.0, 1000.0)
        self.player_pos = (0.0, 0.0, 0.0)
        self.player_yaw = 0.0
        self.speed = 0.0
        self.bonk = 0.0
        self.theme = str(props.get("theme", graphics.DEFAULT_THEME))
        self.glows = {}                # entity name -> its glow light
        self.homes = {}                # id(entity) -> (authored pos, yaw, phase)
        self.rivals = []               # [(x, z, carrying a flag)] for the radar

    # -- derived -------------------------------------------------------------
    def elapsed(self, now=None):
        end = self.finished_at if self.finished_at else (now or time.monotonic())
        return end - self.started

    def remaining(self, now=None):
        if not self.time_limit:
            return None
        return max(0.0, self.time_limit - self.elapsed(now))

    def shield_fraction(self, now=None):
        now = now or time.monotonic()
        return max(0.0, min(1.0, (self.shield_until - now) / SHIELD_SECONDS))

    def say(self, text, seconds=2.5):
        self.message = text
        self.message_until = time.monotonic() + seconds


class LevitateGame:
    """The built-in Levitate layer (see :meth:`PluginManager.register_builtin_game`)."""

    name = "levitate"
    version = "0.1.0"
    category = "Levitate!"
    description = "Hovercraft capture-the-flag in walled mazes."

    def __init__(self):
        self.api = None
        self.host = None
        self.match = None
        self.handling = None
        self.squad = None              # the rival craft (game/bots.py)
        self._hud = None
        self._view = None              # the 3D view whose stock HUD we hide
        self._quality = graphics.DEFAULT_QUALITY
        self._lit = None               # (renderer, theme, quality) now lit
        self._dimmed = []              # fill lights a lit match hid

    # -- registration ----------------------------------------------------------
    def register(self, api):
        try:
            api.register_pause_menu_item(self._hud_size_label, self._cycle_hud_size,
                                         close_menu=False)
        except Exception as exc:  # pragma: no cover - hosts without a pause menu
            print(f"[Levitate] no pause-menu HUD size item: {exc}")
        for cls, label in ENTITIES:
            try:
                api.register_entity(cls, category=self.category, menu_label=label)
            except Exception as exc:  # pragma: no cover - editor-less hosts
                print(f"[Levitate] could not register {cls.__name__}: {exc}")

    def register_runtime(self, api):
        self.api = api

    def connect(self, host):
        self.host = host
        host.on("render.overlay", self._draw_overlay)
        host.on("render.pre_scene", self._light_scene)

    # -- play lifecycle ----------------------------------------------------------
    def _rules(self, logic):
        for thing in getattr(getattr(logic, "editor_state", None), "things", []) or []:
            if str(thing.properties.get("type", "")).lower() == "levitaterules":
                return thing
        return None

    def on_play_start(self, logic):
        rules = self._rules(logic)
        if rules is None:
            self.match = None
            return
        props = rules.properties
        self.match = match = MatchState(rules, props.get("player_team", "red"))
        things = logic.editor_state.things
        for thing in things:
            kind = str(thing.properties.get("type", "")).lower()
            if kind == "levitateflag":
                team = thing.properties.get("team", "blue")
                (match.rival_flags if team == match.rival_team else match.home_flags).append(thing)
        match.walls, match.bounds = self._radar_walls(logic)
        self._dress(logic, match, things)
        player = self._player_object(logic)
        if player is not None:
            self.handling = HoverHandling(
                player, props.get("hover_friction", 0.14), props.get("hover_accel", 0.35),
                props.get("turn_rate", 150.0), props.get("wall_bounce", 0.55))
            self.handling.install()
        self.squad = self._start_rivals(logic, match)
        match.say(f"{match.title.upper()}  —  TAKE ALL {len(match.rival_flags)} "
                  f"{match.rival_team.upper()} FLAGS", 4.0)

    def bot_count(self, logic=None):
        """How many rival craft a match starts with: the launcher's
        ``[Game] bots``, or :data:`game.bots.DEFAULT_BOTS`."""
        config = self._config(logic)
        return bots.bots_from(config) if config is not None else bots.DEFAULT_BOTS

    def _start_rivals(self, logic, match):
        """Put the rival craft into the maze. A failure here costs the match
        its rivals, never the match."""
        count = self.bot_count(logic)
        if count <= 0:
            return None
        squad = bots.Squad(logic, count)
        try:
            if squad.start(match):
                match.rivals = squad.radar()
                return squad
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[Levitate] no rival craft: {exc}")
            try:
                squad.stop(match)
            except Exception:
                pass
        return None

    def on_play_stop(self, logic):
        if self._view is not None:
            # Fio's own health/ammo HUD comes back for whatever plays next.
            self._view._hud_runtime_visible = None
            self._view = None
        if self.handling is not None:
            self.handling.remove()
        self.handling = None
        if self.squad is not None:
            self.squad.stop(self.match)
        self.squad = None
        # Restore everything the match hid or moved, so the edited map is
        # unchanged.
        if self.match is not None:
            from plugins.api import clear_flag
            for thing in getattr(logic.editor_state, "things", []):
                kind = str(thing.properties.get("type", "")).lower()
                if kind in ("levitateflag", "levitatepickup") and thing.properties.get("hidden"):
                    clear_flag(thing, "hidden")
            for light in list(self.match.glows.values()) + self._dimmed:
                if light.properties.get("hidden"):
                    clear_flag(light, "hidden")
            self._settle(logic, self.match)
        self._dimmed = []
        self.match = None

    # -- the look of a match ----------------------------------------------------
    def _config(self, logic=None):
        """The editor window's settings (settings.ini as the launcher left
        it). The plugin host knows no window during play, so the window
        showing *logic*'s scene is looked for among the application's."""
        window = getattr(self.host, "editor", None) or self._window_for(logic)
        return getattr(window, "config", None)

    @staticmethod
    def _window_for(logic):
        state = getattr(logic, "editor_state", None)
        if state is None:
            return None
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            widgets = app.topLevelWidgets() if app is not None else []
        except Exception:  # pragma: no cover - the Qt-free player
            return None
        for widget in widgets:
            if getattr(widget, "state", None) is state and hasattr(widget, "config"):
                return widget
        return None

    def _dress(self, logic, match, things):
        """What a match changes about how the maze looks: its fill lights go
        out when the sun and sky light it (game/graphics.py), each cell and
        flag is paired with its glow, and their resting places are noted for
        the bob and spin."""
        from plugins.api import set_flag
        config = self._config(logic)
        self._quality = graphics.quality_from(config) if config is not None else graphics.DEFAULT_QUALITY
        renderer = getattr(getattr(getattr(self.host, "editor", None), "view_3d", None),
                           "renderer", None)
        lit = graphics.lit(self._quality) and getattr(renderer, "surface_shading", True)
        self._dimmed = []
        named = {}
        for thing in things:
            props = thing.properties
            kind = str(props.get("type", "")).lower()
            if kind == "light":
                if props.get(graphics.FILL_LIGHT) and lit:
                    set_flag(thing, "hidden", True)
                    self._dimmed.append(thing)
                if props.get("levitate_for"):
                    match.glows[str(props["levitate_for"])] = thing
            elif kind in ("levitateflag", "levitatepickup"):
                named[id(thing)] = thing
                rotation = props.get("rotation") or [0.0, 0.0, 0.0]
                match.homes[id(thing)] = (tuple(thing.pos), float(rotation[1]),
                                          (len(match.homes) * 1.7) % 6.283)

    @staticmethod
    def _glow(match, thing, on):
        """A cell's or flag's light goes out with it and comes back with it."""
        from plugins.api import clear_flag, set_flag
        light = match.glows.get(str(thing.properties.get("name", "")))
        if light is None:
            return
        if on:
            clear_flag(light, "hidden")
        else:
            set_flag(light, "hidden", True)

    def _animate(self, logic, match, now):
        """Cells turn and bob; a flag stirs on its pole."""
        from engine.change_journal import touch
        t = now - match.started
        for thing in logic.editor_state.things:
            home = match.homes.get(id(thing))
            if home is None or thing.properties.get("hidden"):
                continue
            (x, y, z), yaw, phase = home
            if str(thing.properties.get("type", "")).lower() == "levitatepickup":
                thing.pos = (x, y + math.sin(t * 2.1 + phase) * 5.0, z)
                thing.properties["rotation"] = [0.0, (yaw + t * 70.0) % 360.0, 0.0]
            else:
                thing.properties["rotation"] = [0.0, yaw + math.sin(t * 0.9 + phase) * 7.0, 0.0]
            touch(thing)

    @staticmethod
    def _settle(logic, match):
        """Put every animated cell and flag back where the map has it."""
        from engine.change_journal import touch
        for thing in getattr(logic.editor_state, "things", []):
            home = match.homes.get(id(thing))
            if home is None:
                continue
            thing.pos = home[0]
            thing.properties["rotation"] = [0.0, home[1], 0.0]
            touch(thing)

    def _light_scene(self, event):
        """Before each frame: light the match's world (the theme's sun, sky
        and finish, at the chosen quality), and anything else as Fio does."""
        renderer = event.get("renderer")
        if renderer is None:
            return
        match = self.match
        want = None
        if event.get("play_mode", False) and match is not None:
            want = (match.theme, self._quality)
        lit = self._lit
        if lit is not None and lit[0]() is renderer and lit[1] == want:
            return
        import weakref
        if want is None:
            graphics.clear(renderer)
        else:
            # The sun's shadow map is spent on the maze, not on its scenery.
            graphics.apply(renderer, *want, focus=match.bounds)
        try:
            self._lit = (weakref.ref(renderer), want)
        except TypeError:
            self._lit = None

    @staticmethod
    def _player_object(logic):
        runtime = getattr(logic, "player_runtime", None)
        return getattr(runtime, "player", None)

    @staticmethod
    def _radar_walls(logic):
        """Footprints of the solid wall brushes (taller than a step), for the
        radar, and the maze's bounds."""
        walls = []
        xs, zs = [], []
        for brush in getattr(logic.editor_state, "brushes", []) or []:
            try:
                # Not triggers, and not the scenery beyond the walls.
                if brush.get("is_trigger") or str(brush.get("name", "")).startswith("Scenery_"):
                    continue
                (x, y, z), (w, h, d) = brush["pos"], brush["size"]
            except (KeyError, TypeError, ValueError):
                continue
            x0, x1, z0, z1 = x - w / 2, x + w / 2, z - d / 2, z + d / 2
            xs += [x0, x1]
            zs += [z0, z1]
            if h >= 48 and y + h / 2 > 24:
                walls.append((x0, z0, x1, z1))
        bounds = (min(xs), min(zs), max(xs), max(zs)) if xs else (-1000, -1000, 1000, 1000)
        return walls, bounds

    # -- per tick ---------------------------------------------------------------
    def on_tick(self, logic, ctx):
        match = self.match
        api = self.api
        if match is None or api is None:
            return
        state = api.player
        if not getattr(state, "exists", False):
            return
        now = time.monotonic()
        delta = float(getattr(ctx, "delta", 1 / 60) or 1 / 60)
        live = getattr(state, "object", None)
        if self.handling is not None and live is not None and live is not self.handling.player:
            # Play (re)spawned the player as a new object: the handling moves
            # onto it.
            self.handling.remove()
            self.handling.player = live
            self.handling.install()
        if self.handling is not None and match.finished is None:
            self.handling.tick(state, ctx, delta)
            match.bonk = self.handling.bonk
        if self.squad is not None:
            self.squad.tick(match, state, delta, now, self.handling)
            match.rivals = self.squad.radar()
            if self.handling is not None:
                match.bonk = max(match.bonk, self.handling.bonk)
        pos = tuple(state.position)
        match.player_pos = pos
        match.player_yaw = float(state.yaw)
        match.speed = self.handling.speed(state) if self.handling else 0.0
        self._animate(logic, match, now)
        if match.finished is not None:
            if ctx.key_down("r"):
                self._restart(logic, state)
            return
        self._collect_flags(match, pos)
        self._pads(logic, match, state, pos, now)
        self._pickups(logic, match, pos, now)
        self._use_slots(match, ctx, now, pos)
        remaining = match.remaining(now)
        if remaining is not None and remaining <= 0.0:
            match.finished, match.finished_at = "timeout", now
            match.say("TIME UP  —  PRESS R TO RETRY", 999)

    def _collect_flags(self, match, pos):
        from plugins.api import set_flag
        for flag in match.rival_flags:
            if id(flag) in match.taken:
                continue
            fx, fy, fz = flag.pos
            if math.hypot(fx - pos[0], fz - pos[2]) <= FLAG_REACH and abs(fy - pos[1]) < 160:
                match.taken.add(id(flag))
                set_flag(flag, "hidden", True)
                self._glow(match, flag, False)
                left = len(match.rival_flags) - len(match.taken)
                if left:
                    match.say(f"FLAG TAKEN  —  {left} TO GO")
                else:
                    match.finished, match.finished_at = "win", time.monotonic()
                    secs = match.elapsed()
                    match.say(f"MAZE CLEARED IN {int(secs // 60)}:{int(secs % 60):02d}  —  PRESS R", 999)

    def _pads(self, logic, match, state, pos, now):
        for pad in self.api.entities_of_type("levitatepad"):
            px, py, pz = pad.pos
            radius = float(pad.properties.get("radius", 56.0))
            if math.hypot(px - pos[0], pz - pos[2]) > radius or abs(py - (pos[1] - 25)) > 60:
                continue
            if match.pad_ready.get(id(pad), 0.0) > now:
                continue
            match.pad_ready[id(pad)] = now + PAD_COOLDOWN
            kind = pad.properties.get("kind", "spring")
            strength = float(pad.properties.get("strength", 520.0))
            vx, vy, vz = state.velocity
            if kind == "spring":
                state.velocity = (vx, strength, vz)
            elif kind == "boost":
                if self.handling is not None:
                    self.handling.boost_until = now + BOOST_SECONDS
                # Along the way the craft is already going, at least *strength*.
                speed = math.hypot(vx, vz)
                if speed > 1.0:
                    scale = max(speed, strength) / speed
                    state.velocity = (vx * scale, vy, vz * scale)
                match.say("BOOST", 1.0)
            elif kind == "barrier":
                self._give(match, "barrier")

    def _pickups(self, logic, match, pos, now):
        from plugins.api import clear_flag, set_flag
        for pickup in self.api.entities_of_type("levitatepickup"):
            key = id(pickup)
            back = match.pickup_back.get(key)
            if back is not None:
                if now >= back:
                    clear_flag(pickup, "hidden")
                    self._glow(match, pickup, True)
                    match.pickup_back.pop(key, None)
                continue
            px, py, pz = pickup.pos
            if math.hypot(px - pos[0], pz - pos[2]) > PICKUP_REACH or abs(py - pos[1]) > 140:
                continue
            if self._give(match, pickup.properties.get("kind", "shield")):
                set_flag(pickup, "hidden", True)
                self._glow(match, pickup, False)
                match.pickup_back[key] = now + float(pickup.properties.get("respawn_time", 20.0))

    @staticmethod
    def _give(match, kind):
        if kind not in POWERUPS:
            return False
        for i, slot in enumerate(match.slots):
            if slot is None:
                match.slots[i] = kind
                match.say(f"{kind.upper()} READY  —  KEY {i + 1}", 1.6)
                return True
        return False

    def _use_slots(self, match, ctx, now, pos=None):
        for i in range(SLOT_COUNT):
            kind = match.slots[i]
            if kind is None or not ctx.key_down(str(i + 1)):
                continue
            match.slots[i] = None
            message = f"{kind.upper()} ENGAGED"
            if kind == "shield":
                match.shield_until = now + SHIELD_SECONDS
            elif kind == "phantom":
                match.phantom_until = now + PHANTOM_SECONDS
            elif kind == "jammer":
                caught = self.squad.jam(pos or match.player_pos) if self.squad else 0
                message = (f"JAMMER  —  {caught} RIVAL{'S' if caught != 1 else ''} STALLED"
                           if caught else "JAMMER  —  NO RIVALS IN RANGE")
            elif kind == "barrier":
                self._drop_barrier(pos or match.player_pos)
                message = "BARRIER DROPPED"
            match.say(message, 1.4)

    def _drop_barrier(self, pos):
        """A barrier where the craft is: rival craft cannot cross it."""
        if self.squad is None:
            return
        x, y, z = pos
        prop = None
        try:
            prop = self.api.spawn(LevitateBarrier, (x, y + 20.0, z))
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[Levitate] barrier not drawn: {exc}")
        self.squad.drop_barrier(pos, prop)

    def _restart(self, logic, state):
        """Back to the start: flags and orbs return, the clock restarts."""
        from plugins.api import clear_flag
        for thing in logic.editor_state.things:
            kind = str(thing.properties.get("type", "")).lower()
            if kind in ("levitateflag", "levitatepickup") and thing.properties.get("hidden"):
                clear_flag(thing, "hidden")
                self._glow(self.match, thing, True)
        start = None
        for thing in logic.editor_state.things:
            if str(thing.properties.get("type", "")).lower() == "playerstart":
                start = thing
                break
        if start is not None:
            x, y, z = start.pos
            state.teleport((x, y + 30, z))
            state.yaw = math.radians(float(start.properties.get("angle", 0.0)))
        old = self.match
        self.match = MatchState(self._rules(logic), old.player_team)
        self.match.rival_flags, self.match.home_flags = old.rival_flags, old.home_flags
        self.match.walls, self.match.bounds = old.walls, old.bounds
        self.match.glows, self.match.homes = old.glows, old.homes
        if self.squad is not None:
            self.squad.reset(self.match)
            self.match.rivals = self.squad.radar()
        self.match.say("GO!", 1.5)

    # -- HUD ---------------------------------------------------------------------
    def _hud_size_label(self):
        from .ui.hud import DEFAULT_HUD_SIZE, HUD_SIZES
        size = self._hud.size if self._hud is not None else DEFAULT_HUD_SIZE
        return f"HUD Size: {HUD_SIZES[size][0]}"

    def _cycle_hud_size(self, main_window, logic):
        """Pause menu > HUD Size: Compact <-> Large, saved to settings.ini
        (``[Display] hud_size``, which the launcher also sets)."""
        from .ui.hud import HUD_SIZES, Hud, hud_size_from
        config = getattr(main_window, "config", None)
        current = self._hud.size if self._hud is not None else (
            hud_size_from(config) if config is not None else "compact")
        names = list(HUD_SIZES)
        size = names[(names.index(current) + 1) % len(names)]
        if self._hud is None:
            self._hud = Hud(size)
        self._hud.size = size
        if config is not None:
            if not config.has_section("Display"):
                config.add_section("Display")
            config.set("Display", "hud_size", size)
            save = getattr(main_window, "save_config", None)
            if callable(save):
                save()

    def _draw_overlay(self, event):
        if not event.get("play_mode", False) or self.match is None:
            return
        view = event.get("viewport")
        if view is not None and self._view is not view:
            # The cockpit replaces Fio's stock health/ammo HUD for the match.
            view._hud_runtime_visible = False
            self._view = view
        if self._hud is None:
            from .ui.hud import Hud, hud_size_from
            config = getattr(getattr(view, "editor", None), "config", None)
            self._hud = Hud(hud_size_from(config) if config is not None else "compact")
        self._hud.draw(event.get("painter"), int(event.get("width", 1280)),
                       int(event.get("height", 720)), self.match)
