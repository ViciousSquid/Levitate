"""The random level generator: Levitate! mazes.

Fio's generator made rooms-and-corridors levels for its stock shooter. This
is the same tool in the same places -- Tools > Procedural Map Generator, a
LevelChanger with *Generate level* on, and ``tools/procedural_map_gen.py``
on the command line -- making what this game plays: a maze in one of
Levitate!'s worlds, with its flags, pads, power cells, lamps and skyline,
from a seed nobody has seen before.

The mazes themselves are built by ``game/tools/make_mazes.py`` (the builder
of the shipped mazes) through ``game/random_maze.py``, which also holds the
settings and their ranges. This module is the editor's side of it: the
settings a LevelChanger may carry (:func:`sanitize_params`), the map
(:func:`create_map_data`) and the generator panel
(:class:`ProceduralMapWidget`).
"""

import random

from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from game import random_maze

#: Each numeric setting's ``(low, high)``; see game/random_maze.py.
PARAM_LIMITS = dict(random_maze.LIMITS)


def sanitize_params(params):
    """*params* as a complete, in-range set of generator settings. A
    generated level's exit LevelChanger carries them, and those come back
    from map data, so they always pass through here."""
    return random_maze.sanitize(params)


def create_map_data(params, yield_hook=None):
    """A new maze as Fio map data. *params* are the generator's settings
    (any missing take their defaults); a ``seed`` of 0 draws one from the
    ``random`` module, so seeding it first makes the result repeatable.
    *yield_hook*, if given, is called once: a maze is built in a moment."""
    data = random_maze.generate(sanitize_params(params), random)
    if yield_hook is not None:
        yield_hook()
    return data


class ProceduralMapWidget(QWidget):
    """Generator UI that replaces the properties tab widget."""
    map_generated = pyqtSignal(object)  # emits map data dict, or None = close request

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_params = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Random Maze Generator")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(0)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton { background-color: #555; color: #f0f0f0;
                          border: 1px solid #666; padding: 8px 16px; }
            QPushButton:hover { background-color: #F08000; }
            QPushButton:pressed { background-color: #d06000; }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn, 1)
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self.accept_and_load)
        self.generate_btn.setStyleSheet("""
            QPushButton { background-color: #2E7D32; color: white; font-weight: bold;
                          border: none; padding: 8px 16px; }
            QPushButton:hover { background-color: #388E3C; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
        """)
        btn_row.addWidget(self.generate_btn, 1)
        layout.addLayout(btn_row)

        # Timer for button cooldown
        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.setSingleShot(True)
        self._cooldown_timer.timeout.connect(self._enable_generate_button)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        params_widget = QWidget()
        params_layout = QVBoxLayout(params_widget)
        group = QGroupBox("Maze")
        form = QFormLayout(group)
        defaults = random_maze.DEFAULTS

        self.world_combo = QComboBox()
        self.world_combo.addItem("Any world", random_maze.RANDOM_WORLD)
        for theme, name in random_maze.WORLDS.items():
            self.world_combo.addItem(name, theme)
        self.world_combo.setToolTip("The world the maze is built in: its walls, floor, sky and light.")
        form.addRow("World:", self.world_combo)

        def spin(name, tip, suffix=""):
            box = QSpinBox()
            box.setRange(*PARAM_LIMITS[name])
            box.setValue(defaults[name])
            box.setToolTip(tip)
            if suffix:
                box.setSuffix(suffix)
            return box

        self.cols = spin("cols", "Corridors across, west to east.")
        form.addRow("Width (cells):", self.cols)
        self.rows = spin("rows", "Corridors across, south to north.")
        form.addRow("Depth (cells):", self.rows)
        self.loops = spin("loops", "The share of inner walls knocked out: 0 is a pure maze "
                                   "with one way through, more gives loops to race round.", " %")
        form.addRow("Openness:", self.loops)
        self.plazas = spin("plazas", "Open squares, each with a power cell.")
        form.addRow("Plazas:", self.plazas)
        self.ledges = spin("ledges", "Raised ledges in dead ends, reached from a spring pad.")
        form.addRow("Ledges:", self.ledges)
        self.time_limit = spin("time_limit", "The clock the maze is played against.", " s")
        self.time_limit.setSingleStep(30)
        form.addRow("Time limit:", self.time_limit)
        self.seed = spin("seed", "The same seed and settings make the same maze.")
        self.seed.setSpecialValueText("New every time")
        form.addRow("Seed:", self.seed)

        params_layout.addWidget(group)
        params_layout.addStretch()
        scroll.setWidget(params_widget)
        layout.addWidget(scroll)

    def params(self):
        """The panel's settings, as :func:`create_map_data` takes them."""
        return {
            'world': self.world_combo.currentData(),
            'cols': self.cols.value(),
            'rows': self.rows.value(),
            'loops': self.loops.value(),
            'plazas': self.plazas.value(),
            'ledges': self.ledges.value(),
            'time_limit': self.time_limit.value(),
            'seed': self.seed.value(),
        }

    def accept_and_load(self):
        """Generate map data and emit signal, then disable button briefly."""
        if not self.generate_btn.isEnabled():
            return
        self.generate_btn.setEnabled(False)
        self._cooldown_timer.start(1000)   # re-enable after 1 second
        random.seed()
        self.current_params = self.params()
        self.map_generated.emit(create_map_data(self.current_params))

    def _enable_generate_button(self):
        self.generate_btn.setEnabled(True)

    def reject(self):
        """Request to close this widget and restore original content."""
        self.map_generated.emit(None)
