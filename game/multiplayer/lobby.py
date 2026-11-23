"""The multiplayer lobby, and handing a started race to the game.

Ported from MiniWind's lobby (game/multiplayer/lobby.py there), with
Levitate's own party: no characters to make, just pilots.

* :class:`Lobby` -- the rules, as plain data the host owns and every
  computer is shown (:meth:`Lobby.snapshot`): who is in, who is ready, the
  maze and how many rival craft. Only the host changes the race; everyone
  changes their own name and readiness.
* :class:`LobbyController` -- one computer's side: host a race (and find its
  friend code), join one by code, typed address or from the LAN list, let in
  a friend whose router keeps them out, and the handshake that checks
  everyone has the same game and the same maze.
* :func:`prepare` / :func:`active` / :func:`finish` -- the launcher hands a
  started race to the game, which keeps its connections for the race.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import MAX_PLAYERS, PROTOCOL_VERSION
from . import friend_code
from .transport import GAME_PORT, NetworkService

#: What a joiner who arrives after the start is told when the host has
#: closed the race to late arrivals.
LATE_ARRIVAL_CLOSED = "The race has already started and is not taking late arrivals."
#: The longest pilot name.
NAME_LENGTH = 16
#: The maze value meaning "a random maze" (its settings travel in the lobby).
RANDOM = "random"
#: The files whose contents decide how a race plays: every computer in a race
#: must have the same ones (:func:`content_signature`).
GAMEPLAY_FILES = ("game/host.py", "game/hover.py", "game/bots.py", "game/spawns.py",
                  "game/entities.py", "game/random_maze.py", "game/tools/make_mazes.py",
                  "game/multiplayer/session.py", "game/multiplayer/lobby.py")


class LobbyError(ValueError):
    """Something the lobby will not do; the message is fit to show."""


def clean_name(name, fallback="Pilot"):
    """A pilot name: printable, trimmed, at most :data:`NAME_LENGTH`."""
    text = re.sub(r"\s+", " ", "".join(ch for ch in str(name or "") if ch.isprintable()))
    text = text.strip()[:NAME_LENGTH].strip()
    return text or fallback


def content_signature(root) -> str:
    """A fingerprint of the gameplay code, so two different builds never race
    each other (the handshake compares them)."""
    digest = hashlib.sha256(f"levitate-{PROTOCOL_VERSION}".encode())
    for name in GAMEPLAY_FILES:
        try:
            digest.update((Path(root) / name).read_bytes().replace(b"\r\n", b"\n"))
        except OSError:
            digest.update(b"-")
    return digest.hexdigest()


def map_hash(path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def local_identity(root):
    """This computer's opaque reconnect proof: a pilot who drops out and
    comes back is the same pilot. Kept with the user's own files."""
    try:
        from editor.user_paths import writable_dir
        folder = Path(writable_dir(str(root)))
    except Exception:
        folder = Path(root)
    path = folder / ".levitate-identity"
    try:
        value = path.read_text().strip()
        if len(value) == 64 and all(c in "0123456789abcdef" for c in value):
            return value
    except OSError:
        pass
    value = secrets.token_hex(32)
    try:
        path.write_text(value)
    except OSError:
        pass                            # a fresh identity each time, then
    return value


def maze_file(root, maze, random_params=None) -> Path:
    """The maze file a race is on; a random maze is (re)built from its
    settings first, the same on every computer."""
    from .. import random_maze
    if maze == RANDOM:
        rel = random_maze.write(str(root), dict(random_params or {}))
        return Path(root) / rel
    rel = Path(str(maze))
    if rel.is_absolute() or ".." in rel.parts or rel.suffix.lower() != ".json":
        raise LobbyError("That is not a maze.")
    return Path(root) / rel


@dataclass
class Member:
    owner: str
    name: str
    host: bool = False
    ready: bool = False
    connected: bool = True


class Lobby:
    """One race's lobby, as the host keeps it."""

    def __init__(self, signature, name, maze, bots, random_params=None):
        self.signature = signature
        self.name = clean_name(name, "Levitate! race")[:32]
        self.maze = maze
        self.random = random_params
        self.map_hash = ""
        self.bots = int(bots)
        self.members = []
        self.present = set()
        self.started = False
        self.late_arrival = True
        self.revision = 0

    # -- who is in -----------------------------------------------------------
    def member(self, owner):
        return next((m for m in self.members if m.owner == owner), None)

    def humans(self):
        return sum(1 for m in self.members if m.connected)

    def join(self, owner, name, host=False):
        member = self.member(owner)
        if member is not None:
            member.connected = True
        else:
            if self.humans() >= MAX_PLAYERS:
                raise LobbyError(f"The race is full ({MAX_PLAYERS} pilots).")
            member = Member(owner, self._free_name(clean_name(name)), host=host)
            self.members.append(member)
        self.revision += 1
        return member

    def _free_name(self, name, owner=None):
        taken = {m.name.casefold() for m in self.members if m.owner != owner}
        if name.casefold() not in taken:
            return name
        for n in range(2, 99):
            candidate = f"{name[:NAME_LENGTH - 3]} {n}"
            if candidate.casefold() not in taken:
                return candidate
        return name

    def leave(self, owner):
        member = self.member(owner)
        if member is None:
            return
        if self.started:
            member.connected, member.ready = False, False
        else:
            self.members.remove(member)
        self.revision += 1

    # -- what they change --------------------------------------------------------
    def rename(self, owner, name):
        member = self._own(owner)
        member.name = self._free_name(clean_name(name), owner)
        self.revision += 1

    def ready(self, owner, value):
        member = self._own(owner)
        member.ready = bool(value)
        self.revision += 1

    def configure(self, owner, maze=None, random_params=None, bots=None, late_arrival=None):
        """The host sets the race up; a change clears everyone's readiness."""
        self._host(owner)
        if self.started:
            raise LobbyError("The race has started.")
        if maze is not None:
            self.maze, self.random = str(maze), (dict(random_params) if maze == RANDOM else None)
        if bots is not None:
            from ..bots import MAX_BOTS
            self.bots = max(0, min(MAX_BOTS, int(bots)))
        if late_arrival is not None:
            self.late_arrival = bool(late_arrival)
        for member in self.members:
            if not member.host:
                member.ready = False
        self.revision += 1

    def blocker(self) -> str:
        """Why the host cannot start yet ('' when it can)."""
        waiting = [m.name for m in self.members if not m.host and m.connected and not m.ready]
        if waiting:
            return "Waiting for " + ", ".join(waiting) + " to be ready."
        return ""

    def start(self, owner):
        self._host(owner)
        why = self.blocker()
        if why:
            raise LobbyError(why)
        self.started = True
        self.revision += 1

    def _own(self, owner):
        member = self.member(owner)
        if member is None:
            raise LobbyError("You are not in this race.")
        return member

    def _host(self, owner):
        if not self._own(owner).host:
            raise LobbyError("Only the host can do that.")

    def snapshot(self) -> dict:
        return {
            "protocol": PROTOCOL_VERSION, "signature": self.signature,
            "name": self.name, "maze": self.maze, "random": self.random,
            "map_hash": self.map_hash, "bots": self.bots,
            "started": self.started, "late_arrival": self.late_arrival,
            "revision": self.revision,
            "members": [dict(owner=m.owner, name=m.name, host=m.host, ready=m.ready,
                             connected=m.connected) for m in self.members],
        }


class LobbyController:
    """This computer's side of a race's lobby."""

    def __init__(self, root, maze, network=None, identity=None, bots=None):
        from ..bots import DEFAULT_BOTS
        self.root = Path(root)
        self.maze = maze
        self.bots = DEFAULT_BOTS if bots is None else int(bots)
        self.network = network or NetworkService()
        self.identity = identity         # disk and hashing wait for open()
        self.signature = ""
        self.owner = "host"
        self.name = "Pilot"
        self.lobby = None                # the host's
        self.state = None                # the lobby as last seen
        self.peers = {}                  # peer -> owner
        self.errors = []
        self.started = False
        self.opened = False
        self.disconnected = False
        self._pending_peers = {}
        self._requests = {}
        self._verified = set()
        #: settings.ini, for [Multiplayer] stun_server / upnp (set by the UI).
        self.config = None
        self.invitation = 0
        self.code = ""
        self.code_how = ""               # "router" | "stun" | "local" | "" while finding
        self.public_ip = ""
        self.public_port = 0
        self.mapping = None
        self.join_invitation = 0
        self.reply = ""
        self._wrong_invitations = []
        self._code_thread = None

    @property
    def is_host(self):
        return self.lobby is not None

    def open(self):
        if self.opened:
            return
        self.identity = self.identity or local_identity(self.root)
        self.signature = content_signature(self.root)
        try:
            self.network.start_browser()
        except OSError as exc:
            self.network.stop_browser()
            self.errors.append(f"Games on this network cannot be listed ({exc}). "
                               "Hosting and friend codes still work.")
        self.opened = True

    # -- hosting -------------------------------------------------------------------
    def host(self, name="Levitate! race", *, port=GAME_PORT):
        if not self.opened:
            raise LobbyError("Open Multiplayer before hosting.")
        if self.lobby is not None:
            raise LobbyError("A race is already open.")
        self.network.host(port)
        self.invitation = friend_code.new_invitation()
        self.owner = "host"
        self.lobby = Lobby(self.signature, name, self.maze, self.bots)
        self.lobby.join(self.owner, self.name, host=True)
        self.lobby.present.add(self.owner)
        self.network.stop_browser()
        self._publish()

    def find_code(self, finder=None, wait=False):
        """Work out where friends can reach this race, and its code, on a
        thread of its own (it asks the router, then a STUN server)."""
        if self.lobby is None or not self.invitation:
            return
        port = int(getattr(self.network, "port", None) or GAME_PORT)
        finder = finder or (lambda: friend_code.find_public_address(
            port, self.config, stun=self._stun_from_game_socket))
        self.code, self.code_how = "", ""

        def work():
            try:
                ip, code_port, how, mapping = finder()
            except Exception:
                ip, code_port, how, mapping = friend_code.local_address(), port, "local", None
            if self.lobby is None:
                if mapping is not None:
                    mapping.close()
                return
            if self.mapping is not None and self.mapping is not mapping:
                self.mapping.close()
            self.mapping = mapping
            self.public_ip, self.public_port = ip, int(code_port)
            self.code = friend_code.encode(ip, self.public_port, self.invitation)
            self.code_how = how

        self._code_thread = threading.Thread(target=work, name="Levitate friend code", daemon=True)
        self._code_thread.start()
        if wait:
            self._code_thread.join(10)

    def new_code(self):
        """A fresh invitation: the old code stops working; pilots already in
        stay in."""
        if self.lobby is None:
            return
        self.invitation = friend_code.new_invitation()
        self._wrong_invitations.clear()
        if self.public_ip:
            self.code = friend_code.encode(self.public_ip, self.public_port, self.invitation)

    def _stun_from_game_socket(self, server):
        udp = getattr(self.network, "udp", None)
        return udp.stun(server) if udp is not None else friend_code.stun_lookup(server)

    def let_in(self, text):
        """The host lets in a friend whose router -- or this one -- keeps
        them out: *text* is the friend's reply code."""
        if self.lobby is None:
            raise LobbyError("Host a race first.")
        try:
            address, port, invitation = friend_code.decode(text)
        except friend_code.FriendCodeError as exc:
            raise LobbyError(str(exc)) from exc
        if invitation:
            raise LobbyError("That is a friend code for joining a race, not a reply code.")
        self.network.let_in(address, port)

    def _admit(self, peer, owner, invitation):
        """Anyone on the host's own network, a pilot already in the race
        (coming back), or anyone with this race's invitation -- but not
        while someone is guessing codes."""
        if not self.invitation:
            return
        address = self.network.peer_address(peer)
        if friend_code.trusted_address(address) or self.lobby.member(owner) is not None:
            return
        now = time.monotonic()
        self._wrong_invitations = [(t, i) for t, i in self._wrong_invitations
                                   if now - t < friend_code.WRONG_WINDOW]
        if len({i for _t, i in self._wrong_invitations}) >= friend_code.WRONG_ALLOWED:
            raise LobbyError("The race is not taking new pilots for a minute. Try again shortly.")
        if not invitation:
            raise LobbyError("From outside the host's network, join with the host's friend code.")
        if invitation != self.invitation:
            self._wrong_invitations.append((now, invitation))
            raise LobbyError("That friend code is out of date: ask the host for the new one.")

    # -- joining ---------------------------------------------------------------------
    def join_code(self, text, tcp=False):
        """Join the race a friend code points at -- over UDP, which gets
        through home routers, or TCP with *tcp* -- or a typed address (TCP)."""
        try:
            address, port, invitation = friend_code.parse(text)
        except friend_code.FriendCodeError as exc:
            raise LobbyError(str(exc)) from exc
        typed = not friend_code.looks_like_code(text)
        if not typed and not invitation:
            raise LobbyError("That is a reply code: give it to your host, who lets you in with it.")
        self.join_invitation = invitation
        if typed or tcp:
            self.join(address, port)
            return
        if not self.opened:
            raise LobbyError("Open Multiplayer before joining.")
        self.owner = hashlib.sha256(self.identity.encode()).hexdigest()
        self.network.join_udp(address, port)
        self.find_reply_code()

    def join(self, address, port=GAME_PORT):
        if not self.opened:
            raise LobbyError("Open Multiplayer before joining.")
        self.owner = hashlib.sha256(self.identity.encode()).hexdigest()
        self.network.join(address, port)

    def find_reply_code(self, finder=None):
        """While knocking, this computer's reply code, in case the host's
        router keeps it out (the host lets it in with :meth:`let_in`)."""
        self.reply = ""
        server = friend_code.stun_server(self.config)
        if finder is None and server is None:
            return

        def work():
            try:
                found = finder() if finder is not None else self._stun_from_game_socket(server)
            except Exception:
                found = None
            if found and found[1]:
                self.reply = friend_code.reply_code(found[0], int(found[1]))

        threading.Thread(target=work, name="Levitate reply code", daemon=True).start()

    # -- requests ----------------------------------------------------------------------
    def request(self, op, **args):
        """Ask for a change: made at once on the host, sent to it elsewhere."""
        message = dict(type="lobby_request", op=op, **args)
        if self.lobby is not None:
            self._request(self.owner, message)
            self._publish()
        elif not self.network.send("host", message):
            raise LobbyError("The host is not connected.")

    def set_name(self, name):
        self.name = clean_name(name)
        if self.lobby is not None or self.state is not None:
            self.request("rename", name=self.name)

    def choose(self, maze=None, bots=None, late_arrival=None):
        """The host's race settings. A random maze gets its settings, seed
        and all, here: every computer builds the same one from them."""
        params = None
        if maze == RANDOM:
            from .. import random_maze
            params = random_maze.surprise()
            params["seed"] = random.randint(1, random_maze.LIMITS["seed"][1])
        self.request("configure", maze=maze, random=params, bots=bots, late_arrival=late_arrival)

    def _request(self, owner, message):
        op = message.get("op")
        lobby = self.lobby
        if op == "rename":
            lobby.rename(owner, message.get("name"))
        elif op == "ready":
            lobby.ready(owner, message.get("ready"))
        elif op == "configure":
            maze = message.get("maze")
            if maze is not None and maze != RANDOM:
                maze_file(self.root, maze)               # a real maze path
            lobby.configure(owner, maze=maze, random_params=message.get("random"),
                            bots=message.get("bots"), late_arrival=message.get("late_arrival"))
        elif op == "start":
            path = maze_file(self.root, lobby.maze, lobby.random)
            if not path.is_file():
                raise LobbyError("The maze is missing.")
            lobby.map_hash = map_hash(path)
            lobby.start(owner)
            self.started = True
            self.maze_path = str(path)
            self.network.advertisement = None
            self.network.broadcast({"type": "start", "state": lobby.snapshot()},
                                   peers=list(self.peers))
        else:
            raise LobbyError("Unknown lobby action.")

    def _publish(self):
        lobby = self.lobby
        self.state = lobby.snapshot()
        self.network.advertisement = None if lobby.started else {
            "name": lobby.name, "players": lobby.humans(), "maximum": MAX_PLAYERS,
            "signature": self.signature, "map": lobby.maze}
        self.network.broadcast({"type": "lobby", "state": self.state}, peers=list(self.peers))

    # -- messages ------------------------------------------------------------------------
    def handle(self, peer, message):
        """Deal with a lobby or connection message; False for gameplay ones."""
        kind = message.get("type")
        try:
            if kind == "connected":
                if self.lobby is None:
                    self.network.send("host", {
                        "type": "hello", "protocol": PROTOCOL_VERSION,
                        "signature": self.signature, "identity": self.identity,
                        "invite": int(self.join_invitation or 0), "name": self.name})
                else:
                    self._pending_peers[peer] = time.monotonic()
                return True
            if kind == "hello" and self.lobby is not None:
                if peer not in self._pending_peers:
                    raise LobbyError("Handshake already completed.")
                if (message.get("protocol") != PROTOCOL_VERSION
                        or message.get("signature") != self.signature):
                    raise LobbyError("Your game is a different version from the host's.")
                identity = message.get("identity")
                if (not isinstance(identity, str) or len(identity) != 64
                        or any(c not in "0123456789abcdef" for c in identity)):
                    raise LobbyError("Invalid reconnect identity.")
                owner = hashlib.sha256(identity.encode()).hexdigest()
                if owner in self.peers.values() or owner == self.owner:
                    raise LobbyError("This pilot is already connected.")
                invite = message.get("invite", 0)
                self._admit(peer, owner, invite if isinstance(invite, int) else -1)
                if self.lobby.started and self.lobby.member(owner) is None \
                        and not self.lobby.late_arrival:
                    raise LobbyError(LATE_ARRIVAL_CLOSED)
                self.lobby.join(owner, message.get("name"))
                self.peers[peer] = owner
                self.lobby.present.add(owner)
                self._pending_peers.pop(peer, None)
                self._publish()
                if self.lobby.started:
                    # A late arrival goes straight into the race.
                    self.network.send(peer, {"type": "start", "state": self.lobby.snapshot()})
                return True
            if kind == "lobby_request" and self.lobby is not None:
                owner = self.peers.get(peer)
                if owner is None:
                    raise LobbyError("Complete the connection handshake first.")
                self._rate_limit(peer, 30)
                self._request(owner, message)
                self._publish()
                return True
            if kind in ("lobby", "start") and self.lobby is None and peer == "host":
                state = message.get("state")
                if not isinstance(state, dict) or state.get("protocol") != PROTOCOL_VERSION:
                    raise LobbyError("Invalid lobby state.")
                if state.get("signature") != self.signature:
                    raise LobbyError("Your game is a different version from the host's.")
                self.state = state
                self.network.stop_browser()
                if kind == "start":
                    path = maze_file(self.root, state.get("maze"), state.get("random"))
                    expected = state.get("map_hash", "")
                    if expected and map_hash(path) != expected:
                        raise LobbyError("Your copy of the maze differs from the host's.")
                    self.maze_path = str(path)
                    self.started = True
                return True
            if kind in ("error", "connection_error"):
                self.errors.append(str(message.get("message", "Connection failed.")))
                return True
            if kind == "disconnected":
                self._pending_peers.pop(peer, None)
                self._requests.pop(peer, None)
                if self.lobby is None:
                    self.disconnected = True
                    self.errors.append("The host disconnected.")
                else:
                    owner = self.peers.pop(peer, None)
                    self.lobby.present.discard(owner)
                    if owner is not None:
                        self.lobby.leave(owner)
                    self._publish()
                return True
            if kind == "closed":
                self.disconnected = True
                self.errors.append("The host closed the race.")
                return True
        except (LobbyError, ValueError, TypeError, KeyError) as exc:
            if self.lobby is not None:
                self.network.send(peer, {"type": "error", "message": str(exc)})
                if kind == "hello":
                    self.network.disconnect(peer)
                    self._pending_peers.pop(peer, None)
            else:
                self.errors.append(str(exc))
            return True
        return False

    def _rate_limit(self, peer, maximum=120):
        now = time.monotonic()
        start, count = self._requests.get(peer, (now, 0))
        if now - start >= 1:
            start, count = now, 0
        count += 1
        self._requests[peer] = start, count
        if count > maximum:
            raise LobbyError("Too many lobby actions.")

    def poll(self):
        for peer, message in self.network.poll():
            self.handle(peer, message)
        self.maintenance()

    def maintenance(self):
        """Also run during the race, when the game reads the network."""
        for peer, started in list(self._pending_peers.items()):
            if time.monotonic() - started > 5:
                self.network.disconnect(peer)
                self._pending_peers.pop(peer, None)

    def owner_of(self, peer):
        return self.peers.get(peer)

    def close(self):
        if self.lobby is not None:
            self.network.broadcast({"type": "closed"}, peers=list(self.peers))
        self.network.close()
        self.opened = False
        if self.mapping is not None:
            mapping, self.mapping = self.mapping, None
            threading.Thread(target=mapping.close, name="Levitate unmap", daemon=True).start()


_active = None


def prepare(controller):
    """Hand a started race to the game (the launcher's last word)."""
    global _active
    if not controller.started:
        raise LobbyError("The race has not started.")
    if _active is not None and _active is not controller:
        _active.close()
    controller.network.stop_browser()
    _active = controller


def active():
    """The race the launcher started, or None."""
    return _active


def finish():
    """Close the race: its connections and sockets."""
    global _active
    if _active is not None:
        _active.close()
    _active = None
