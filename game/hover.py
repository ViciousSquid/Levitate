"""Hovercraft handling on top of Fio's Quake-style player physics.

The stock player stops almost at once (ground friction 6) and turns on a dime.
A hovercraft should glide: friction and acceleration are scaled down on the
live player instance (the class is untouched, so other players and the editor
are not affected), steering keys turn the craft, and hitting a wall at speed
bounces it back instead of sliding along.
"""

from __future__ import annotations

import math

#: Top speed relative to Fio's walking pace.
TOP_SPEED_SCALE = 1.5
#: Below this speed (units/s) a wall stops the craft rather than bouncing it.
BOUNCE_FROM = 150.0


class HoverHandling:
    def __init__(self, player, friction=0.14, accel=0.35, turn_rate=150.0, bounce=0.55):
        self.player = player                 # the engine's own Player object
        self.friction = float(friction)
        self.accel = float(accel)
        self.turn_rate = math.radians(float(turn_rate))
        self.bounce = float(bounce)
        self._prev = (0.0, 0.0)
        self._installed = False
        self.boost_until = 0.0
        self.bonk = 0.0                      # seconds of the last-bounce flash

    # -- install / remove --------------------------------------------------
    def install(self):
        p = self.player
        if p is None or self._installed:
            return
        friction_orig = type(p)._apply_move_friction.__get__(p)
        accel_orig = type(p)._accelerate.__get__(p)
        handling = self

        def _apply_move_friction(delta):
            friction_orig(delta * handling.friction)

        def _accelerate(wish_dir, wish_speed, accelerate, delta):
            # The engine clamps a wish to walking pace (300) before this; a
            # hovercraft runs half as fast again, and faster still boosted.
            boost = 1.6 if handling.boosting else 1.0
            accel_orig(wish_dir, wish_speed * TOP_SPEED_SCALE * boost,
                       accelerate * handling.accel, delta)

        p._apply_move_friction = _apply_move_friction
        p._accelerate = _accelerate
        self._installed = True

    def remove(self):
        p = self.player
        if p is None or not self._installed:
            return
        for name in ("_apply_move_friction", "_accelerate"):
            p.__dict__.pop(name, None)
        self._installed = False

    @property
    def boosting(self):
        import time
        return time.monotonic() < self.boost_until

    # -- per tick ------------------------------------------------------------
    def tick(self, state, ctx, delta):
        """Steer with the arrow keys and bounce off walls. *state* is the
        RuntimeAPI's PlayerState."""
        turn = 0.0
        if ctx.key_down("left"):
            turn += 1.0
        if ctx.key_down("right"):
            turn -= 1.0
        if turn:
            state.yaw = state.yaw + turn * self.turn_rate * delta

        vx, vy, vz = state.velocity
        px, pz = self._prev
        prev_speed = math.hypot(px, pz)
        if prev_speed > BOUNCE_FROM:
            hit_x = abs(px) > 120.0 and abs(vx) < abs(px) * 0.2
            hit_z = abs(pz) > 120.0 and abs(vz) < abs(pz) * 0.2
            if hit_x or hit_z:
                nx = -px * self.bounce if hit_x else vx
                nz = -pz * self.bounce if hit_z else vz
                state.velocity = (nx, vy, nz)
                vx, vz = nx, nz
                self.bonk = 0.25
        self.bonk = max(0.0, self.bonk - delta)
        self._prev = (vx, vz)

    def speed(self, state):
        vx, _vy, vz = state.velocity
        return math.hypot(vx, vz)
