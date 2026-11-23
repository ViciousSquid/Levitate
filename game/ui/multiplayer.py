"""The launcher's MULTIPLAYER window: friend codes and the race lobby.

Laid out as MiniWind's, two pages with one thing to press on each:

* **Play together** -- your pilot name; **Host a race**; paste a friend's
  code into **Join a friend** (a whole, valid code joins by itself), or pick
  a race found on this network.
* **The lobby** -- the race's friend code (Copy, New code), the pilots, the
  maze and how many rival craft (the host chooses), **Ready** for a joiner
  and **Start race** for the host. Letting in a friend whose router keeps
  them out (reply codes) is folded away until it is wanted.

When the race starts the window hands it to the game (game/multiplayer/
lobby.py ``prepare``) and the launcher goes straight into PLAY.
"""

from __future__ import annotations

import configparser
import os
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPushButton,
                             QStackedWidget, QVBoxLayout, QWidget)

from ..multiplayer import MAX_PLAYERS, friend_code
from ..multiplayer.lobby import RANDOM, LobbyController, LobbyError, clean_name, prepare
from ..multiplayer.transport import GAME_PORT

_PRIMARY = ("QPushButton { background-color:#FF2EA0; color:white; border:1px solid #FFE83C;"
            " font-weight:bold; padding:0.5em 1.4em; }"
            "QPushButton:hover { background-color:#FF5CB8; }"
            "QPushButton:disabled { background-color:#3a2466; color:#8d7fb0; border-color:#3a2466; }")
_FOLD = ("QPushButton { border:none; background:transparent; color:#A58BD6; text-align:left;"
         " padding:2px 0; } QPushButton:hover { color:#ffffff; }")


class MultiplayerDialog(QDialog):
    def __init__(self, root, settings_path=None, parent=None, controller=None):
        super().__init__(parent)
        from .launcher import maze_choices
        from ..bots import MAX_BOTS, bots_from
        self.root = str(root)
        self.settings_path = settings_path or os.path.join(self.root, "settings.ini")
        self.config = configparser.ConfigParser(interpolation=None)
        self.config.read(self.settings_path)
        maze = self.config.get("Startup", "last_maze", fallback="") or ""
        self.mazes = maze_choices(self.root)
        if maze not in [rel for rel, _t in self.mazes] and maze != RANDOM:
            maze = self.mazes[0][0] if self.mazes else RANDOM
        self.controller = controller or LobbyController(self.root, maze, bots=bots_from(self.config))
        self.controller.config = self.config
        self.controller.name = clean_name(self.config.get("Multiplayer", "name", fallback="Pilot"))
        try:
            self.port = self.config.getint("Multiplayer", "port", fallback=GAME_PORT)
        except ValueError:
            self.port = GAME_PORT
        self.handed_off = False
        self._revision = None
        self._knock_started = 0.0
        self._joining = ""
        self._loading = False
        self.setWindowTitle("Levitate! — Multiplayer")
        self.setMinimumSize(560, 520)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())

        outer = QVBoxLayout(self)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#FFE83C;")
        outer.addWidget(self.status)
        self.back = QPushButton("Back to launcher")
        self.back.clicked.connect(self.reject)
        outer.addWidget(self.back, 0, Qt.AlignLeft)

        # -- page 1: play together ---------------------------------------------------
        first = QWidget()
        page = QVBoxLayout(first)
        title = QLabel("<b>Race with friends</b>")
        page.addWidget(title)
        form = QFormLayout()
        self.name_edit = QLineEdit(self.controller.name)
        self.name_edit.setMaxLength(16)
        self.name_edit.editingFinished.connect(self._name_changed)
        form.addRow("Your pilot name", self.name_edit)
        page.addLayout(form)
        self.host_button = QPushButton("Host a race")
        self.host_button.setStyleSheet(_PRIMARY)
        self.host_button.setToolTip("Open a lobby and get a friend code to send to your friends.")
        self.host_button.clicked.connect(self._host)
        page.addWidget(self.host_button)
        page.addSpacing(10)
        page.addWidget(QLabel("<b>Join a friend</b> — paste their friend code:"))
        row = QHBoxLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("XXXXX-XXXXX-XXXXX  (or an address: 1.2.3.4)")
        self.code_edit.textChanged.connect(self._code_typed)
        self.code_edit.returnPressed.connect(self._join)
        row.addWidget(self.code_edit, 1)
        self.join_button = QPushButton("Join")
        self.join_button.clicked.connect(self._join)
        row.addWidget(self.join_button)
        page.addLayout(row)
        self.tcp_check = QCheckBox("Join over TCP (the host has forwarded the port)")
        page.addWidget(self.tcp_check)
        self.reply_label = QLabel()
        self.reply_label.setWordWrap(True)
        self.reply_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        page.addWidget(self.reply_label)
        self.found_label = QLabel("<b>Races on this network</b>")
        page.addWidget(self.found_label)
        self.found = QListWidget()
        self.found.itemActivated.connect(self._join_found)
        page.addWidget(self.found, 1)
        self.pages.addWidget(first)

        # -- page 2: the lobby -----------------------------------------------------------
        second = QWidget()
        lobby = QVBoxLayout(second)
        self.lobby_title = QLabel()
        lobby.addWidget(self.lobby_title)
        self.code_row = QWidget()
        code_row = QHBoxLayout(self.code_row)
        code_row.setContentsMargins(0, 0, 0, 0)
        code_row.addWidget(QLabel("Friend code:"))
        self.code_label = QLabel("finding your address…")
        self.code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.code_label.setStyleSheet("font-weight:bold; font-size:1.3em; color:#28F0FF;")
        code_row.addWidget(self.code_label, 1)
        self.copy_button = QPushButton("Copy code")
        self.copy_button.clicked.connect(self._copy)
        code_row.addWidget(self.copy_button)
        self.new_code_button = QPushButton("New code")
        self.new_code_button.setToolTip("The old code stops working; pilots already in stay in.")
        self.new_code_button.clicked.connect(self._new_code)
        code_row.addWidget(self.new_code_button)
        lobby.addWidget(self.code_row)
        self.code_how = QLabel()
        self.code_how.setWordWrap(True)
        self.code_how.setStyleSheet("color:#A58BD6;")
        lobby.addWidget(self.code_how)
        lobby.addWidget(QLabel(f"<b>Pilots</b> (up to {MAX_PLAYERS}; rival craft fill the other seats)"))
        self.members = QListWidget()
        lobby.addWidget(self.members, 1)
        settings = QFormLayout()
        self.maze_combo = QComboBox()
        for rel, title_text in self.mazes:
            self.maze_combo.addItem(title_text, rel)
        self.maze_combo.addItem("Random maze", RANDOM)
        self.maze_combo.currentIndexChanged.connect(self._configure)
        settings.addRow("Maze", self.maze_combo)
        self.bots_combo = QComboBox()
        self.bots_combo.addItem("None", 0)
        for count in range(1, MAX_BOTS + 1):
            self.bots_combo.addItem(str(count), count)
        self.bots_combo.currentIndexChanged.connect(self._configure)
        settings.addRow("Rival craft", self.bots_combo)
        self.late_check = QCheckBox("Let pilots join a race that has started")
        self.late_check.toggled.connect(self._configure)
        settings.addRow("", self.late_check)
        lobby.addLayout(settings)
        self.waiting = QLabel()
        self.waiting.setWordWrap(True)
        lobby.addWidget(self.waiting)
        buttons = QHBoxLayout()
        self.leave_button = QPushButton("Leave")
        self.leave_button.clicked.connect(self.reject)
        buttons.addWidget(self.leave_button)
        buttons.addStretch(1)
        self.ready_button = QPushButton("Ready")
        self.ready_button.setCheckable(True)
        self.ready_button.setStyleSheet(_PRIMARY)
        self.ready_button.toggled.connect(self._ready)
        buttons.addWidget(self.ready_button)
        self.start_button = QPushButton("Start race")
        self.start_button.setStyleSheet(_PRIMARY)
        self.start_button.clicked.connect(self._start)
        buttons.addWidget(self.start_button)
        lobby.addLayout(buttons)
        self.fold = QPushButton("▸ A friend can't get in?")
        self.fold.setStyleSheet(_FOLD)
        self.fold.clicked.connect(self._toggle_fold)
        lobby.addWidget(self.fold)
        self.let_in_box = QWidget()
        let_in = QHBoxLayout(self.let_in_box)
        let_in.setContentsMargins(0, 0, 0, 0)
        self.reply_edit = QLineEdit()
        self.reply_edit.setPlaceholderText("Their reply code")
        let_in.addWidget(self.reply_edit, 1)
        let_button = QPushButton("Let in")
        let_button.clicked.connect(self._let_in)
        let_in.addWidget(let_button)
        self.let_in_box.setVisible(False)
        lobby.addWidget(self.let_in_box)
        self.pages.addWidget(second)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        try:
            self.controller.open()
        except Exception as exc:
            self.status.setText(f"Multiplayer is unavailable: {exc}")
        self.timer.start(50)

    # -- page 1 ---------------------------------------------------------------------------
    def _name_changed(self):
        name = clean_name(self.name_edit.text())
        self.name_edit.setText(name)
        self._remember("name", name)
        try:
            self.controller.set_name(name)
        except LobbyError as exc:
            self.status.setText(str(exc))

    def _remember(self, key, value):
        if not self.config.has_section("Multiplayer"):
            self.config.add_section("Multiplayer")
        self.config.set("Multiplayer", key, str(value))
        try:
            with open(self.settings_path, "w") as f:
                self.config.write(f)
        except OSError:
            pass

    def _host(self):
        self._name_changed()
        try:
            self.controller.host(f"{self.controller.name}'s race", port=self.port)
        except (LobbyError, OSError, ValueError) as exc:
            self.status.setText(f"Could not host: {exc}")
            return
        self.controller.find_code()
        self.status.setText("")
        self._show_lobby()

    def _code_typed(self, text):
        # A whole, valid friend code joins by itself.
        if friend_code.looks_like_code(text):
            try:
                friend_code.decode(text)
            except friend_code.FriendCodeError:
                return
            if text != self._joining:
                self._join()

    def _join(self):
        text = self.code_edit.text().strip()
        if not text or text == self._joining:
            return
        self._name_changed()
        try:
            self.controller.join_code(text, tcp=self.tcp_check.isChecked())
        except (LobbyError, OSError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        self._joining = text
        self._knock_started = time.monotonic()
        self.status.setText("Knocking on the host's door…")

    def _join_found(self, item):
        game = item.data(Qt.UserRole) or {}
        try:
            self._name_changed()
            self.controller.join(game["address"], int(game.get("port", GAME_PORT)))
            self.status.setText(f"Joining {game.get('name', 'the race')}…")
        except (LobbyError, OSError, ValueError, KeyError) as exc:
            self.status.setText(str(exc))

    # -- page 2 ---------------------------------------------------------------------------
    def _show_lobby(self):
        self.pages.setCurrentIndex(1)
        host = self.controller.is_host
        self.code_row.setVisible(host)
        self.code_how.setVisible(host)
        for widget in (self.maze_combo, self.bots_combo, self.late_check):
            widget.setEnabled(host)
        self.start_button.setVisible(host)
        self.ready_button.setVisible(not host)
        self.fold.setVisible(host)
        self.back.setVisible(False)

    def _copy(self):
        if self.controller.code:
            QApplication.clipboard().setText(self.controller.code)
            self.status.setText("Code copied: send it to your friends.")

    def _new_code(self):
        self.controller.new_code()

    def _toggle_fold(self):
        show = not self.let_in_box.isVisible()
        self.let_in_box.setVisible(show)
        self.fold.setText(("▾" if show else "▸") + " A friend can't get in?")
        if show:
            self.status.setText("Ask them for the reply code their Join screen shows, paste it here "
                                "and press Let in.")

    def _let_in(self):
        try:
            self.controller.let_in(self.reply_edit.text().strip())
            self.status.setText("Letting them in: they should join in a moment.")
        except (LobbyError, OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def _configure(self, *_):
        if self._loading or not self.controller.is_host:
            return
        try:
            maze = self.maze_combo.currentData()
            state = self.controller.state or {}
            self.controller.choose(maze=None if maze == state.get("maze") else maze,
                                   bots=self.bots_combo.currentData(),
                                   late_arrival=self.late_check.isChecked())
        except (LobbyError, OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def _ready(self, on):
        if self._loading:
            return
        try:
            self.controller.request("ready", ready=bool(on))
        except LobbyError as exc:
            self.status.setText(str(exc))

    def _start(self):
        try:
            self.controller.request("start")
        except (LobbyError, OSError, ValueError) as exc:
            self.status.setText(str(exc))

    # -- every 50 ms ----------------------------------------------------------------------
    def _tick(self):
        controller = self.controller
        try:
            controller.poll()
        except Exception as exc:  # pragma: no cover - defensive
            self.status.setText(str(exc))
        while controller.errors:
            self.status.setText(controller.errors.pop(0))
            self._joining = ""
        if controller.started:
            self._hand_off()
            return
        if controller.state is not None and self.pages.currentIndex() == 0:
            self._show_lobby()
        if self.pages.currentIndex() == 0:
            self._show_found()
            if self._joining and controller.reply and time.monotonic() - self._knock_started > 4:
                self.reply_label.setText(
                    "Still knocking. If the host's router is keeping you out, send them your "
                    f"reply code: <b>{controller.reply}</b> — they paste it under "
                    "“A friend can't get in?” and press Let in.")
            return
        self._show_state()

    def _show_found(self):
        games = self.controller.network.found_games()
        signature = self.controller.signature
        keys = [(g.get("address"), g.get("port")) for g in games]
        current = [self.found.item(i).data(Qt.UserRole + 1) for i in range(self.found.count())]
        if keys == current:
            return
        self.found.clear()
        for game, key in zip(games, keys):
            same = game.get("signature") == signature
            text = (f"{game.get('name', 'Race')} — {game.get('players', '?')}/"
                    f"{game.get('maximum', MAX_PLAYERS)} pilots"
                    + ("" if same else "  (a different version)"))
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, game)
            item.setData(Qt.UserRole + 1, key)
            if not same:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.found.addItem(item)
        self.found_label.setVisible(bool(games))
        self.found.setVisible(bool(games))

    def _show_state(self):
        controller = self.controller
        state = controller.state or {}
        if controller.is_host:
            code = controller.code
            self.code_label.setText(code or "finding your address…")
            self.copy_button.setEnabled(bool(code))
            self.code_how.setText({
                "router": "Your router opened the way: friends anywhere can join with this code.",
                "stun": "Friends anywhere can join with this code. If one can't get in, "
                        "let them in with their reply code (below).",
                "local": "This code works on your own network (or a VPN): your public "
                         "address could not be found.",
            }.get(controller.code_how, ""))
        if state.get("revision") == self._revision:
            return
        self._revision = state.get("revision")
        self._loading = True
        try:
            self.lobby_title.setText(f"<b>{state.get('name', 'Race')}</b>")
            self.members.clear()
            me = controller.owner
            for member in state.get("members", []):
                if not member.get("connected", True):
                    continue
                tags = []
                if member.get("host"):
                    tags.append("host")
                elif member.get("ready"):
                    tags.append("ready")
                if member.get("owner") == me:
                    tags.append("you")
                self.members.addItem(f"{member.get('name')}" + (f"  ({', '.join(tags)})" if tags else ""))
            humans = sum(1 for m in state.get("members", []) if m.get("connected", True))
            bots = int(state.get("bots", 0))
            seats = min(bots, MAX_PLAYERS - humans)
            self.members.addItem(f"+ {seats} rival craft" if seats else "No rival craft")
            index = self.maze_combo.findData(state.get("maze"))
            if index >= 0:
                self.maze_combo.setCurrentIndex(index)
            self.bots_combo.setCurrentIndex(max(0, self.bots_combo.findData(bots)))
            self.late_check.setChecked(bool(state.get("late_arrival", True)))
            mine = next((m for m in state.get("members", []) if m.get("owner") == me), {})
            self.ready_button.setChecked(bool(mine.get("ready")))
            if controller.is_host:
                why = controller.lobby.blocker()
                self.waiting.setText(why or "Everyone is ready: start when you like.")
                self.start_button.setEnabled(not why)
            else:
                self.waiting.setText("Press Ready, then the host starts the race.")
        finally:
            self._loading = False

    def _hand_off(self):
        self.timer.stop()
        try:
            prepare(self.controller)
        except LobbyError as exc:
            self.status.setText(str(exc))
            return
        self.handed_off = True
        self.accept()

    def race_map(self):
        """The maze file the race is on, relative to the install folder."""
        path = getattr(self.controller, "maze_path", "")
        try:
            return os.path.relpath(path, self.root).replace(os.sep, "/")
        except ValueError:
            return path

    def reject(self):
        self.timer.stop()
        if not self.handed_off:
            self.controller.close()
        super().reject()
