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


def model(name):
    """A world model (game/tools/make_models.py)."""
    return f"assets/models/levitate/{name}"


#: A flag's size, ``[width, height]``. The model is centred on its origin, as
#: Fio centres a billboard on its position, so a flag stands on the floor at
#: ``FLAG_SIZE[1] / 2`` above it (:data:`FLAG_RAISE`).
FLAG_SIZE = [96, 144]
FLAG_RAISE = FLAG_SIZE[1] / 2

#: What a flag and a power-up are as Props: scenery the match itself collects
#: (host.py), drawn as a model. Nothing here is solid or simulated.
_MODEL_PROP = dict(render_mode="model", collect_enabled=False, carry_enabled=False,
                   no_collision=True, physics_enabled=False, gravity=False,
                   collision_shape="aabb", topples=False)

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
    """A team's flag. Collect every rival flag to win.

    The model is centred on the flag's position: place it
    :data:`FLAG_RAISE` (72) above the floor for the pole to stand on it."""

    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties["type"] = "levitateflag"
        self.properties.setdefault("team", "blue")
        self.properties.setdefault("rotation", [0.0, 0.0, 0.0])
        self.properties.update(_MODEL_PROP, model_path=self.get_model_path(),
                               sprite_path=self.get_sprite_path(),
                               sprite_size=list(FLAG_SIZE), scale=[1.0, 1.0, 1.0])

    def _team(self):
        return "blue" if self.properties.get("team") == "blue" else "red"

    def get_sprite_path(self):
        return sprite(f"flag_{self._team()}.png")

    def get_model_path(self):
        return model(f"flag_{self._team()}.obj")


class LevitatePickup(Prop):
    """A floating power cell; it goes into the first free dashboard slot."""

    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties["type"] = "levitatepickup"
        self.properties.setdefault("kind", "shield")
        self.properties.setdefault("respawn_time", 20.0)
        self.properties.setdefault("rotation", [0.0, 0.0, 0.0])
        self.properties.update(_MODEL_PROP, model_path=self.get_model_path(),
                               sprite_path=self.get_sprite_path(),
                               sprite_size=[56, 56], scale=[1.0, 1.0, 1.0])

    def _kind(self):
        kind = self.properties.get("kind")
        return kind if kind in POWERUPS else "shield"

    def get_sprite_path(self):
        return sprite(f"pickup_{self._kind()}.png")

    def get_model_path(self):
        return model(f"orb_{self._kind()}.obj")


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


class LevitateNode(Thing):
    """A navigation node: where rival craft can drive (game/bots.py).

    Nodes stand on the floor of the maze; ``links`` names, comma-separated,
    the nodes a craft can drive to from this one in a straight line (a link
    goes both ways when either end names it). The mazes have one per open
    cell, made by game/tools/make_mazes.py; a hand-built maze without any
    still plays, its rivals steering by the walls alone."""
    pixmap_path = "assets/sprites/levitate/nav_node.png"
    editor_sprite_path = pixmap_path

    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties["type"] = "levitatenode"
        self.properties.setdefault("links", "")


class LevitateBarrier(Prop):
    """A barrier a craft has dropped: a wall of force rival craft cannot
    cross (game/bots.py). Made in play from a power cell, never placed in a
    map, so it is not in :data:`ENTITIES`."""

    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties["type"] = "levitatebarrier"
        self.properties.setdefault("rotation", [0.0, 0.0, 0.0])
        self.properties.update(_MODEL_PROP, model_path=model("orb_barrier.obj"),
                               sprite_path=sprite("pickup_barrier.png"),
                               sprite_size=[160, 160], scale=[2.8, 2.8, 2.8])


ENTITIES = (
    (LevitateRules, "Maze Rules"),
    (LevitateFlag, "Flag"),
    (LevitatePickup, "Power-up"),
    (LevitatePad, "Pad"),
    (LevitateNode, "Navigation Node"),
)
