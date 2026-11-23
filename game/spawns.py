"""Spawn points: where every craft in a match starts.

Each maze has :data:`SPAWN_COUNT` of them (``levitatespawn``, placed by
game/tools/make_mazes.py, one per seat in a match), spread over the whole
maze. They belong to nobody: at the start of a match, and again on a retry,
every craft -- the player, player 2 and each rival -- is given one at random,
never one another craft is already on. A maze without any keeps Fio's
PlayerStart for the player, and its rivals start at their flags.
"""

from __future__ import annotations

import math
import random

#: Spawn points in a maze: one per seat (game.bots.MAX_CRAFT).
SPAWN_COUNT = 8
#: A spawn point is taken while a craft is this near it.
TAKEN_WITHIN = 160.0


class SpawnPoints:
    """The maze's spawn points, dealt out at random."""

    def __init__(self, things, rng=None):
        self.rng = rng or random.Random()
        self.points = []                     # [(x, y, z, yaw radians)], feet on the floor
        for thing in things:
            if str(thing.properties.get("type", "")).lower() != "levitatespawn":
                continue
            x, y, z = (float(v) for v in thing.pos)
            try:
                yaw = math.radians(float(thing.properties.get("angle", 0.0)))
            except (TypeError, ValueError):
                yaw = 0.0
            self.points.append((x, y, z, yaw))

    def __len__(self):
        return len(self.points)

    def pick(self, occupied=()):
        """A spawn point at random among those no craft in *occupied*
        (``(x, z)`` or ``(x, y, z)`` positions) is on; any at random when
        every one is taken. None when the maze has none."""
        if not self.points:
            return None
        spots = [(p[0], p[-1]) if len(p) == 2 else (p[0], p[2]) for p in occupied]
        free = [p for p in self.points
                if all(math.hypot(p[0] - x, p[2] - z) > TAKEN_WITHIN for x, z in spots)]
        return self.rng.choice(free or self.points)


def place_player(player, point):
    """Put a human craft (the engine's Player, or the RuntimeAPI's
    PlayerState) at *point*, at rest, facing its way."""
    x, y, z, yaw = point
    centre = (x, y + 80.0, z)
    teleport = getattr(player, "teleport", None)
    if callable(teleport):
        teleport(centre)
        player.yaw = yaw
        return
    import glm
    player.pos = glm.vec3(*centre)
    player.velocity = glm.vec3(0.0)
    player.on_ground = False
    player.angle = yaw
