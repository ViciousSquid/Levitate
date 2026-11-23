"""Levitate's map entities.

Serialised type tokens are the class names lowercased (``LevitateFlag`` ->
``levitateflag``), Fio's own convention.
"""

from __future__ import annotations

import os

try:
    from editor.things import Thing
except ImportError:  # the Qt-free player
    from plugins.entitybase import Thing
from engine.prop_entity import Prop

HERE = os.path.dirname(os.path.abspath(__file__))


def sprite(name):
    """A world sprite, under assets/ where Fio's renderer resolves them."""
    return f"assets/sprites/levitate/{name}"


#: The power-ups a pickup can hold, in the HUD's slot order.
POWERUPS = ("shield", "phantom", "barrier", "jammer")
#: The floor pads, by kind.
PADS = ("spring", "boost", "barrier")


class LevitateRules(Thing):
    """One per maze: the match rules. Without it a map is inert."""
    pixmap_path = "assets/sprites/logic_timer.png"

    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties["type"] = "levitaterules"
        for key, value in dict(time_limit=300.0, player_team="red",
                               theme="slate", title="Untitled Maze",
                               hover_friction=0.14, hover_accel=0.35,
                               turn_rate=150.0, wall_bounce=0.55).items():
            self.properties.setdefault(key, value)


class LevitateFlag(Prop):
    """A team's flag, placed at floor height. Collect every rival flag to win."""

    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties["type"] = "levitateflag"
        self.properties.setdefault("team", "blue")
        self.properties.update(render_mode="billboard", sprite_path=self.get_sprite_path(),
                               sprite_size=[96, 144], collect_enabled=False,
                               carry_enabled=False, no_collision=True)

    def get_sprite_path(self):
        team = "blue" if self.properties.get("team") == "blue" else "red"
        return sprite(f"flag_{team}.png")


class LevitatePickup(Prop):
    """A floating power-up orb; it goes into the first free dashboard slot."""

    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties["type"] = "levitatepickup"
        self.properties.setdefault("kind", "shield")
        self.properties.setdefault("respawn_time", 20.0)
        self.properties.update(render_mode="billboard", sprite_path=self.get_sprite_path(),
                               sprite_size=[56, 56], collect_enabled=False,
                               carry_enabled=False, no_collision=True)

    def get_sprite_path(self):
        kind = self.properties.get("kind")
        kind = kind if kind in POWERUPS else "shield"
        return sprite(f"pickup_{kind}.png")


class LevitatePad(Thing):
    """The logic of a floor pad. The visible plate is a thin brush beneath
    it, textured ``levitate/pad_<kind>.png``; this marker sits on top."""
    pixmap_path = "assets/sprites/logic_relay.png"

    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties["type"] = "levitatepad"
        self.properties.setdefault("kind", "spring")
        self.properties.setdefault("radius", 56.0)
        self.properties.setdefault("strength", 520.0)


ENTITIES = (
    (LevitateRules, "Maze Rules"),
    (LevitateFlag, "Flag"),
    (LevitatePickup, "Power-up"),
    (LevitatePad, "Pad"),
)
