"""A multiplayer race, once the lobby has started it.

Everyone flies their own craft on their own computer, as in a solo race:
the glide, the walls, springs and boosts are theirs and answer at once. The
host runs everything else -- the clock, the flags, the power cells, the
rival craft -- and is told where every craft is:

* each player sends the host its craft (position, velocity, heading, shield
  and phantom, free system slots) twenty times a second;
* the host sends every player the world twenty times a second
  (:meth:`HostSession.world`): the clock, the flags taken, lost and carried,
  the cells on their stands, every rival and every other craft, and the
  latest announcement;
* and, one at a time and reliably, what is for one player alone: where to
  start (``spawn``), a power cell it flew through (``give``), a rival's
  ram (``bump``); and from a player, a cell it fires (``use``) and asking
  for a retry (``restart``).

The pilots are all on the home team; the rivals are game/bots.py's, and a
pilot who joins takes a rival's seat (:meth:`game.bots.Squad.seat`).
"""

from __future__ import annotations

import math
import time

#: World frames and craft reports a second.
SEND_RATE = 20.0
#: How far ahead a remote craft is extrapolated from its last report, at most.
EXTRAPOLATE = 0.2
#: The billboard of another pilot's craft.
CRAFT_SPRITE = 144.0
CRAFT_DROP = 0.2


def _feet_of_centre(pos):
    """A craft's feet from the centre of its hull (the Player's)."""
    return (pos[0], pos[1] - 50.0, pos[2])


class _Billboards:
    """The hovercraft drawn for craft this computer does not fly itself:
    Fio Monsters, kept off stock AI, created and removed as craft come and
    go."""

    def __init__(self, logic):
        self.logic = logic
        self.entities = {}

    def place(self, key, feet, yaw, team, name):
        entity = self.entities.get(key)
        if entity is None:
            entity = self._make(key, team, name)
        x, y, z = feet
        entity.pos = [x, y + CRAFT_SPRITE * (0.5 - CRAFT_DROP), z]
        from engine.change_journal import moved
        from engine.monster_facing import face_direction
        moved(entity)
        face_direction(entity, (math.sin(yaw), 0.0, math.cos(yaw)))
        return entity

    def _make(self, key, team, name):
        try:
            from editor.things import Monster
        except ImportError:  # pragma: no cover - the Qt-free player
            from plugins.entitybase import Thing as Monster
        entity = Monster(pos=[0.0, 0.0, 0.0], properties={
            "name": str(name), "monster_type": "hovercraft",
            "variant": "blue" if team == "blue" else "<None>",
            "sprite_width": CRAFT_SPRITE, "sprite_height": CRAFT_SPRITE,
            "health": 100, "damage": 0, "awake": False, "wake_on_sight": False,
            "disabled": True, "levitate_net": True})
        self.entities[key] = entity
        self.logic.editor_state.things.append(entity)
        self._changed()
        return entity

    def keep(self, keys):
        """Remove every billboard not in *keys*."""
        gone = [k for k in self.entities if k not in keys]
        things = self.logic.editor_state.things
        for key in gone:
            entity = self.entities.pop(key)
            if entity in things:
                things.remove(entity)
        if gone:
            self._changed()

    def clear(self):
        self.keep(())

    def _changed(self):
        runtime = getattr(self.logic, "world_runtime", None)
        session = getattr(self.logic, "session_runtime", None)
        if runtime is not None and getattr(session, "play_mode", True):
            try:
                runtime.build_entity_caches()
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[Levitate] craft not indexed: {exc}")


class RemoteCraft:
    """Another pilot's craft, as the host knows it."""

    def __init__(self, session, peer, owner, name):
        self.session = session
        self.peer, self.owner, self.name = peer, owner, name
        self.pos = (0.0, 0.0, 0.0)          # hull centre
        self.vel = (0.0, 0.0, 0.0)
        self.yaw = 0.0
        self.shield = False
        self.phantom = False
        self.free_slots = 0
        self.seen = time.monotonic()
        self.placed = False

    # What the rival craft read and ram (game.bots.Pilot's craft).
    @property
    def position(self):
        return self.pos

    @property
    def velocity(self):
        return self.vel

    @velocity.setter
    def velocity(self, value):
        self.vel = tuple(float(v) for v in value)
        self.session.send(self.peer, {"type": "bump", "v": list(self.vel)})

    def give(self, kind):
        """A power cell it flew through, if it has a slot free."""
        if self.free_slots <= 0:
            return False
        self.free_slots -= 1
        self.session.send(self.peer, {"type": "give", "kind": kind})
        return True

    def report(self, message):
        try:
            pos = tuple(float(v) for v in message["p"][:3])
            vel = tuple(float(v) for v in message["v"][:3])
            yaw = float(message.get("yaw", 0.0))
        except (KeyError, TypeError, ValueError, IndexError):
            return
        if not all(math.isfinite(v) for v in pos + vel + (yaw,)):
            return
        self.pos, self.vel, self.yaw = pos, vel, yaw
        self.shield = bool(message.get("shield"))
        self.phantom = bool(message.get("phantom"))
        try:
            self.free_slots = max(0, min(3, int(message.get("free", 0))))
        except (TypeError, ValueError):
            self.free_slots = 0
        self.seen = time.monotonic()


class HostSession:
    """The host's side of a race: it runs the match for everyone."""

    is_host = True

    def __init__(self, game, logic, controller):
        self.game, self.logic, self.controller = game, logic, controller
        self.network = controller.network
        self.crafts = {}                    # peer -> RemoteCraft
        self.billboards = _Billboards(logic)
        self._sent = 0.0

    def send(self, peer, message):
        self.network.send(peer, message)

    # -- what the rest of the game asks --------------------------------------------
    def pilots(self):
        """The remote craft as the rivals see them (game.bots.Pilot)."""
        from ..bots import Pilot
        return [Pilot(c, shielded=c.shield, hidden=c.phantom)
                for c in self.crafts.values() if c.placed]

    def positions(self):
        return [c.pos for c in self.crafts.values() if c.placed]

    # -- per tick ----------------------------------------------------------------------
    def poll(self, match, state, now):
        """Read the network: lobby business (late arrivals, leavers) and the
        pilots' reports and requests."""
        controller = self.controller
        for peer, message in self.network.poll():
            kind = message.get("type")
            if controller.handle(peer, message):
                if kind == "disconnected":
                    self._drop(peer, match)
                continue
            owner = controller.owner_of(peer)
            if owner is None:
                continue
            craft = self.crafts.get(peer)
            if kind == "craft":
                if craft is None:
                    member = controller.lobby.member(owner)
                    craft = self.crafts[peer] = RemoteCraft(
                        self, peer, owner, member.name if member else "Pilot")
                craft.report(message)
                if not craft.placed:
                    craft.placed = True
                    self.spawn(craft, state)
            elif kind == "use" and craft is not None:
                self.game.remote_use(message.get("kind"), craft.pos)
            elif kind == "restart" and match.finished is not None:
                self.game.request_restart()
        controller.maintenance()

    def _drop(self, peer, match):
        craft = self.crafts.pop(peer, None)
        if craft is not None and match is not None and match.finished is None:
            match.announce(f"{craft.name.upper()} LEFT THE RACE", 2.5)

    def spawn(self, craft, state, restart=False):
        """Send *craft* to a free spawn point (or the maze's start)."""
        spawns = self.game.spawns
        taken = [tuple(state.position)] + [c.pos for c in self.crafts.values()
                                           if c is not craft and c.placed]
        if self.game.squad is not None:
            taken = self.game.squad.occupied(taken)
        point = spawns.pick(taken) if spawns else None
        message = {"type": "spawn", "restart": bool(restart)}
        if point is not None:
            message["at"] = list(point)
            craft.pos = (point[0], point[1] + 80.0, point[2])
            craft.vel = (0.0, 0.0, 0.0)
        self.send(craft.peer, message)

    def restart(self, state):
        for craft in self.crafts.values():
            if craft.placed:
                self.spawn(craft, state, restart=True)

    def tick(self, match, state, now):
        """After the match has run: the other pilots' billboards, and the
        world to everyone."""
        keys = set()
        for craft in self.crafts.values():
            if not craft.placed:
                continue
            key = "pilot:" + craft.owner
            keys.add(key)
            self.billboards.place(key, _feet_of_centre(craft.pos), craft.yaw,
                                  match.player_team, craft.name)
        self.billboards.keep(keys)
        if now - self._sent >= 1.0 / SEND_RATE and self.controller.peers:
            self._sent = now
            self.network.broadcast(self.world(match, state, now), replace=True,
                                   peers=list(self.controller.peers))

    def world(self, match, state, now):
        """The world, as every pilot is shown it."""
        def name(thing):
            return str(thing.properties.get("name", ""))

        squad = self.game.squad
        carried = {}
        bots = []
        if squad is not None:
            for bot in squad.bots:
                p, v = bot.actor.pos, bot.actor.velocity
                bots.append([round(float(p.x), 1), round(float(p.y) - bot.actor.height / 2, 1),
                             round(float(p.z), 1), round(float(v.x), 1), round(float(v.z), 1),
                             round(float(bot.actor.angle), 3), bot.carrying is not None])
                if bot.carrying is not None:
                    carried[name(bot.carrying)] = [round(float(c), 1) for c in bot.carrying.pos]
        crafts = []
        host_name = self.controller.name
        x, y, z = state.position
        vx, _vy, vz = state.velocity
        crafts.append(["host", host_name, round(x, 1), round(y - 50.0, 1), round(z, 1),
                       round(vx, 1), round(vz, 1), round(float(state.yaw), 3)])
        for craft in self.crafts.values():
            if craft.placed:
                cx, cy, cz = craft.pos
                crafts.append([craft.owner, craft.name, round(cx, 1), round(cy - 50.0, 1),
                               round(cz, 1), round(craft.vel[0], 1), round(craft.vel[2], 1),
                               round(craft.yaw, 3)])
        flags = list(match.rival_flags) + list(match.home_flags)
        pickups = self.game.api.entities_of_type("levitatepickup") if self.game.api else []
        serial, text, seconds = match.announcement
        return {
            "type": "world",
            "elapsed": round(match.elapsed(now), 2),
            "finished": match.finished,
            "taken": [name(f) for f in flags if id(f) in match.taken],
            "lost": [name(f) for f in flags if id(f) in match.lost],
            "carried": carried,
            "pickups": [name(p) for p in pickups if p.properties.get("hidden")],
            "bots": bots,
            "crafts": crafts,
            "barriers": [[round(b[0], 1), round(b[1], 1)] for b in (squad.barriers if squad else [])],
            "announce": [serial, text, seconds],
        }

    def stop(self):
        self.billboards.clear()


class ClientSession:
    """A joiner's side of a race: it flies its own craft and shows the
    world the host sends."""

    is_host = False

    def __init__(self, game, logic, controller):
        self.game, self.logic, self.controller = game, logic, controller
        self.network = controller.network
        self.billboards = _Billboards(logic)
        self.world_at = 0.0
        self.world = None
        self.announced = 0
        self.gone = False
        self._sent = 0.0
        self._barriers = {}

    def send(self, message, replace=False):
        self.network.send("host", message, replace=replace)

    def use(self, kind, pos):
        self.send({"type": "use", "kind": kind, "p": [float(v) for v in pos]})

    def request_restart(self):
        self.send({"type": "restart"})

    # -- per tick ----------------------------------------------------------------------
    def poll(self, match, state, now):
        controller = self.controller
        for peer, message in self.network.poll():
            kind = message.get("type")
            if controller.handle(peer, message):
                if kind in ("disconnected", "closed") and not self.gone:
                    self.gone = True
                    if match.finished is None:
                        match.finished, match.finished_at = "disconnected", now
                    match.say("THE HOST HAS LEFT THE RACE  —  ESC FOR THE MENU", 999)
                continue
            if peer != "host":
                continue
            if kind == "world":
                self.world, self.world_at = message, now
            elif kind == "spawn":
                self.game.remote_spawn(message.get("at"), bool(message.get("restart")))
            elif kind == "give":
                self.game.give(message.get("kind"))
            elif kind == "bump":
                try:
                    v = tuple(float(c) for c in message["v"][:3])
                except (KeyError, TypeError, ValueError):
                    continue
                if all(math.isfinite(c) for c in v):
                    state.velocity = v
                    if self.game.handling is not None:
                        self.game.handling.bonk = 0.25

    def tick(self, match, state, now):
        """Show the world the host last sent, and send it this craft."""
        if self.world is not None and not self.gone:
            self._apply(match, self.world, now)
        if now - self._sent >= 1.0 / SEND_RATE and not self.gone:
            self._sent = now
            free = sum(1 for slot in match.slots if slot is None)
            self.send({"type": "craft",
                       "p": [round(v, 2) for v in state.position],
                       "v": [round(v, 2) for v in state.velocity],
                       "yaw": round(float(state.yaw), 4),
                       "shield": match.shield_until > now,
                       "phantom": match.phantom_until > now,
                       "free": free}, replace=True)

    def _apply(self, match, world, now):
        from plugins.api import clear_flag, set_flag
        from engine.change_journal import moved
        game = self.game
        # The clock and the end of the race.
        try:
            elapsed = float(world.get("elapsed", 0.0))
        except (TypeError, ValueError):
            elapsed = 0.0
        finished = world.get("finished")
        match.finished = finished if finished in ("win", "timeout", "lost") else None
        match.started = now - elapsed
        match.finished_at = now if match.finished else None
        # What the host announces.
        announce = world.get("announce") or [0, "", 0.0]
        try:
            serial = int(announce[0])
        except (TypeError, ValueError, IndexError):
            serial = 0
        if serial != self.announced:
            self.announced = serial
            try:
                if announce[1]:
                    match.say(str(announce[1])[:80], float(announce[2]))
            except (TypeError, ValueError, IndexError):
                pass
        # The flags.
        taken, lost = set(world.get("taken") or ()), set(world.get("lost") or ())
        carried = world.get("carried") or {}
        for flag in list(match.rival_flags) + list(match.home_flags):
            name = str(flag.properties.get("name", ""))
            gone = name in taken or name in lost
            (match.taken.add if name in taken else match.taken.discard)(id(flag))
            (match.lost.add if name in lost else match.lost.discard)(id(flag))
            if gone != bool(flag.properties.get("hidden")):
                (set_flag(flag, "hidden", True) if gone else clear_flag(flag, "hidden"))
            home = match.homes.get(id(flag))
            if name in carried:
                try:
                    flag.pos = tuple(float(v) for v in carried[name][:3])
                    moved(flag)
                except (TypeError, ValueError):
                    pass
                game._glow(match, flag, False)
            elif home is not None and tuple(flag.pos) != tuple(home[0]):
                flag.pos = home[0]
                moved(flag)
                game._glow(match, flag, not gone)
            elif not gone:
                game._glow(match, flag, True)
            else:
                game._glow(match, flag, False)
        # The power cells on their stands.
        hidden = set(world.get("pickups") or ())
        for pickup in game.api.entities_of_type("levitatepickup"):
            gone = str(pickup.properties.get("name", "")) in hidden
            if gone != bool(pickup.properties.get("hidden")):
                (set_flag(pickup, "hidden", True) if gone else clear_flag(pickup, "hidden"))
                game._glow(match, pickup, not gone)
        # The rivals and the other pilots, carried on from the last report.
        age = min(EXTRAPOLATE, max(0.0, now - self.world_at))
        keys, rivals = set(), []
        for i, row in enumerate(world.get("bots") or ()):
            try:
                x, y, z, vx, vz, yaw, carrying = row[:7]
                x, z = float(x) + float(vx) * age, float(z) + float(vz) * age
            except (TypeError, ValueError):
                continue
            key = f"rival:{i}"
            keys.add(key)
            self.billboards.place(key, (x, float(y), z), float(yaw), match.rival_team, f"Rival_{i + 1}")
            rivals.append((x, z, bool(carrying)))
        match.rivals = rivals
        me = self.controller.owner
        for row in world.get("crafts") or ():
            try:
                owner, name, x, y, z, vx, vz, yaw = row[:8]
                x, z = float(x) + float(vx) * age, float(z) + float(vz) * age
            except (TypeError, ValueError):
                continue
            if owner == me:
                continue
            key = f"pilot:{owner}"
            keys.add(key)
            self.billboards.place(key, (x, float(y), z), float(yaw), match.player_team, str(name)[:16])
        self.billboards.keep(keys)
        self._show_barriers(world.get("barriers") or ())

    def _show_barriers(self, barriers):
        from ..entities import LevitateBarrier
        want = {}
        for row in barriers:
            try:
                want[(round(float(row[0])), round(float(row[1])))] = row
            except (TypeError, ValueError, IndexError):
                continue
        api = self.game.api
        for key in [k for k in self._barriers if k not in want]:
            api.despawn(self._barriers.pop(key))
        for key in want:
            if key not in self._barriers:
                prop = api.spawn(LevitateBarrier, (key[0], 20.0, key[1]))
                if prop is not None:
                    self._barriers[key] = prop

    def stop(self):
        self.billboards.clear()
        api = self.game.api
        for prop in self._barriers.values():
            api.despawn(prop)
        self._barriers = {}


def start(game, logic):
    """The session for the race the launcher started, or None (a solo
    race, or nothing started)."""
    from .lobby import active
    controller = active()
    if controller is None or not controller.started:
        return None
    if controller.is_host:
        return HostSession(game, logic, controller)
    return ClientSession(game, logic, controller)
