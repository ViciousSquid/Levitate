"""Levitate's cockpit HUD, painted with the frame's QPainter.

The dashboard (game/assets/hud/dashboard.png) is laid across the bottom of the
screen at the screen's width; its wells -- speedometer, flag tallies, radar,
system slots, clock, shield -- are filled from the live :class:`MatchState`
each frame. Works on the editor's 3D view and on the native kiosk surface
alike: both hand plugins the same painter through ``render.overlay``.
"""

from __future__ import annotations

import math
import os
import time

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QFont, QFontDatabase, QPainter,
                         QPen, QPixmap, QPolygonF)

from .hud_layout import (DASH_H, DASH_W, FLAGS_HOME, FLAGS_RIVAL, GAUGE_SIZE,
                         RADAR, SHIELD, SLOTS, SPEEDO, TIMER)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ART = os.path.join(ROOT, "game", "assets")

AMBER = QColor(255, 176, 48)
AMBER_DIM = QColor(70, 40, 8)
TEAL = QColor(64, 236, 200)
TEAL_DIM = QColor(16, 70, 60)
WALL = QColor(64, 236, 200, 170)
RED = QColor(236, 70, 64)
BLUE = QColor(80, 140, 255)
MAX_SPEED = 800.0           # the gauge's full sweep, units per second
#: HUD sizes, by ``[Display] hud_size`` value: ``(label, share of the screen's
#: width the dashboard spans, cap as a share of the screen's height or None)``.
#: Compact sits centred along the bottom edge; Large is the original
#: full-width cockpit.
HUD_SIZES = {
    "compact": ("Compact", 0.6, 0.2),
    "large": ("Large", 1.0, None),
}
DEFAULT_HUD_SIZE = "compact"


def hud_size_from(config) -> str:
    """The ``[Display] hud_size`` in *config* (a configparser), or the default."""
    try:
        value = str(config.get("Display", "hud_size", fallback=DEFAULT_HUD_SIZE))
    except Exception:
        return DEFAULT_HUD_SIZE
    value = value.strip().lower()
    return value if value in HUD_SIZES else DEFAULT_HUD_SIZE


def _rect(box, k, ox, oy):
    x0, y0, x1, y1 = box
    return QRectF(ox + x0 * k, oy + y0 * k, (x1 - x0) * k, (y1 - y0) * k)


class Hud:
    def __init__(self, size=DEFAULT_HUD_SIZE):
        self.size = size if size in HUD_SIZES else DEFAULT_HUD_SIZE
        self.pix = {}
        for name in ("dashboard", "gauge_face", "radar_glass", "radar_glare", "reticle"):
            self.pix[name] = QPixmap(os.path.join(ART, "hud", f"{name}.png"))
        icons = ("shield", "phantom", "barrier", "jammer", "flag_red_full", "flag_red_empty",
                 "flag_blue_full", "flag_blue_empty")
        for name in icons:
            self.pix[name] = QPixmap(os.path.join(ART, "icons", f"{name}.png"))
        self.led_family = self._font("LCDAT&TPhoneTimeDate.ttf", "Monospace")
        self.label_family = self._font("HornetDisplay-Regular.ttf", "Sans Serif")
        self._scaled = (None, None)

    @staticmethod
    def _font(filename, fallback):
        path = os.path.join(ROOT, "assets", "fonts", filename)
        try:
            fid = QFontDatabase.addApplicationFont(path)
            families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        except Exception:
            families = []
        return families[0] if families else fallback

    def _dashboard(self, width):
        key, pix = self._scaled
        if key != width:
            src = self.pix["dashboard"]
            pix = src.scaledToWidth(width, Qt.SmoothTransformation) if not src.isNull() else src
            self._scaled = (width, pix)
        return pix

    # ------------------------------------------------------------------------
    def draw(self, painter: QPainter, width: int, height: int, match):
        if painter is None:
            return
        now = time.monotonic()
        painter.save()
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            self._effects(painter, width, height, match, now)
            _label, share, height_cap = HUD_SIZES.get(self.size, HUD_SIZES[DEFAULT_HUD_SIZE])
            k = width * share / DASH_W
            if height_cap is not None:
                k = min(k, height * height_cap / DASH_H)
            ox, oy = (width - DASH_W * k) / 2.0, height - DASH_H * k
            # Wells are drawn first so the panel's bevels frame them.
            self._radar(painter, _rect(RADAR, k, ox, oy), match, now)
            self._gauge(painter, _rect(SPEEDO, k, ox, oy), match)
            dash = self._dashboard(int(round(DASH_W * k)))
            if not dash.isNull():
                painter.drawPixmap(QPointF(ox, oy), dash)
            glare = self.pix["radar_glare"]
            if not glare.isNull():
                painter.drawPixmap(_rect(RADAR, k, ox, oy), glare, QRectF(glare.rect()))
            self._needle(painter, _rect(SPEEDO, k, ox, oy), match)
            self._flags(painter, _rect(FLAGS_RIVAL, k, ox, oy), match.rival_team,
                        len(match.rival_flags), len(match.taken), filled_is_taken=True)
            self._flags(painter, _rect(FLAGS_HOME, k, ox, oy), match.player_team,
                        len(match.home_flags), len(match.home_flags) - len(match.lost),
                        filled_is_taken=False)
            self._slots(painter, _rect(SLOTS, k, ox, oy), match, k)
            self._clock(painter, _rect(TIMER, k, ox, oy), match, now)
            self._shield(painter, _rect(SHIELD, k, ox, oy), match, now)
            self._reticle(painter, width, oy)
            self._message(painter, width, oy, match, now, width / DASH_W)
        finally:
            painter.restore()

    # -- full-screen effects -----------------------------------------------------
    def _effects(self, painter, width, height, match, now):
        if match.phantom_until > now:
            painter.fillRect(0, 0, width, height, QColor(140, 90, 255, 38))
        if match.bonk > 0.0:
            alpha = int(160 * min(1.0, match.bonk / 0.25))
            pen = QPen(QColor(255, 60, 40, alpha), max(6, width // 90))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(0, 0, width, height)
        if match.shield_until > now:
            pen = QPen(QColor(64, 236, 200, 70), max(3, width // 240))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(8, 8, width - 16, height - 16), 24, 24)

    # -- speedometer -------------------------------------------------------------
    def _gauge(self, painter, rect, match):
        face = self.pix["gauge_face"]
        if face.isNull():
            return
        c = rect.center()
        side = min(rect.width(), rect.height()) * GAUGE_SIZE / (SPEEDO[2] - SPEEDO[0])
        painter.drawPixmap(QRectF(c.x() - side / 2, c.y() - side / 2, side, side), face,
                           QRectF(face.rect()))

    def _needle(self, painter, rect, match):
        c = rect.center()
        radius = min(rect.width(), rect.height()) * 0.40
        frac = max(0.0, min(1.0, match.speed / MAX_SPEED))
        angle = math.radians(225 - frac * 270)
        tip = QPointF(c.x() + math.cos(angle) * radius, c.y() - math.sin(angle) * radius)
        painter.setPen(QPen(QColor(255, 90, 60), max(2.0, radius * 0.05), Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(c, tip)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(200, 204, 214))
        painter.drawEllipse(c, radius * 0.09, radius * 0.09)

    # -- radar ---------------------------------------------------------------------
    def _radar(self, painter, rect, match, now):
        glass = self.pix["radar_glass"]
        if not glass.isNull():
            painter.drawPixmap(rect, glass, QRectF(glass.rect()))
        x0, z0, x1, z1 = match.bounds
        span_x, span_z = max(1.0, x1 - x0), max(1.0, z1 - z0)
        pad = rect.width() * 0.06
        scale = min((rect.width() - 2 * pad) / span_x, (rect.height() - 2 * pad) / span_z)
        cx = rect.left() + rect.width() / 2
        cy = rect.top() + rect.height() / 2
        mx, mz = (x0 + x1) / 2, (z0 + z1) / 2

        def to_screen(x, z):
            # North (+Z) is up the screen.
            return QPointF(cx + (x - mx) * scale, cy - (z - mz) * scale)

        painter.save()
        painter.setClipRect(rect)
        painter.setPen(Qt.NoPen)
        painter.setBrush(WALL)
        for wx0, wz0, wx1, wz1 in match.walls:
            a, b = to_screen(wx0, wz1), to_screen(wx1, wz0)
            painter.drawRect(QRectF(a, b))
        blink = (now * 2.0) % 1.0 < 0.6
        for team, flags, gone in ((match.rival_team, match.rival_flags, match.taken),
                                  (match.player_team, match.home_flags, match.lost)):
            colour = RED if team == "red" else BLUE
            for flag in flags:
                if id(flag) in gone:
                    continue
                if team == match.rival_team and not blink:
                    continue
                p = to_screen(flag.pos[0], flag.pos[2])
                painter.setBrush(colour)
                painter.drawEllipse(p, 3.5, 3.5)
        # The craft: an arrow along its heading.
        px, _py, pz = match.player_pos
        p = to_screen(px, pz)
        yaw = match.player_yaw
        fx, fz = -math.sin(yaw), -math.cos(yaw)
        size = max(5.0, rect.width() * 0.035)
        def pt(dx, dz):
            return QPointF(p.x() + dx * size, p.y() - dz * size)
        nose = pt(fx, fz)
        left = pt(-fx * 0.7 - fz * 0.6, -fz * 0.7 + fx * 0.6)
        right = pt(-fx * 0.7 + fz * 0.6, -fz * 0.7 - fx * 0.6)
        painter.setBrush(QColor(255, 236, 120))
        painter.drawPolygon(QPolygonF([nose, left, p, right]))
        painter.restore()

    # -- flag tallies --------------------------------------------------------------
    def _flags(self, painter, rect, team, total, filled, filled_is_taken):
        if total <= 0:
            return
        full = self.pix[f"flag_{team}_full"]
        empty = self.pix[f"flag_{team}_empty"]
        size = min(rect.height() * 0.9, rect.width() / max(1, total) * 0.95)
        gap = (rect.width() - size * total) / (total + 1)
        y = rect.top() + (rect.height() - size) / 2
        for i in range(total):
            pix = full if i < filled else empty
            if pix.isNull():
                continue
            x = rect.left() + gap + i * (size + gap)
            painter.drawPixmap(QRectF(x, y, size, size), pix, QRectF(pix.rect()))

    # -- systems slots -------------------------------------------------------------
    def _slots(self, painter, rect, match, k):
        width = rect.width() / len(match.slots)
        font = QFont(self.label_family)
        font.setPixelSize(max(9, int(13 * k)))
        painter.setFont(font)
        for i, kind in enumerate(match.slots):
            cell = QRectF(rect.left() + i * width, rect.top(), width, rect.height())
            size = min(cell.width(), cell.height()) * 0.62
            icon_rect = QRectF(cell.center().x() - size / 2, cell.top() + cell.height() * 0.12, size, size)
            if kind is not None and not self.pix[kind].isNull():
                painter.drawPixmap(icon_rect, self.pix[kind], QRectF(self.pix[kind].rect()))
            painter.setPen(AMBER if kind else QColor(90, 94, 104))
            painter.drawText(QRectF(cell.left(), cell.bottom() - cell.height() * 0.24,
                                    cell.width(), cell.height() * 0.22),
                             Qt.AlignCenter, f"[{i + 1}] {kind.upper()}" if kind else f"[{i + 1}] ----")

    # -- LED clock ---------------------------------------------------------------------
    def _clock(self, painter, rect, match, now):
        remaining = match.remaining(now)
        seconds = match.elapsed(now) if remaining is None else remaining
        text = f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"
        font = QFont(self.led_family)
        font.setPixelSize(int(rect.height() * 0.78))
        painter.setFont(font)
        painter.setPen(AMBER_DIM)
        painter.drawText(rect, Qt.AlignCenter, "88:88")
        low = remaining is not None and remaining < 30 and (now % 1.0) < 0.5
        painter.setPen(QColor(255, 80, 60) if low else AMBER)
        painter.drawText(rect, Qt.AlignCenter, text)

    # -- shield bar ---------------------------------------------------------------------
    def _shield(self, painter, rect, match, now):
        segments = 10
        frac = match.shield_fraction(now)
        lit = int(math.ceil(frac * segments))
        inner = rect.adjusted(rect.width() * 0.05, rect.height() * 0.25,
                              -rect.width() * 0.05, -rect.height() * 0.25)
        w = inner.width() / segments
        painter.setPen(Qt.NoPen)
        for i in range(segments):
            painter.setBrush(TEAL if i < lit else TEAL_DIM)
            painter.drawRect(QRectF(inner.left() + i * w + 1, inner.top(), w - 2, inner.height()))

    # -- centre ------------------------------------------------------------------------
    def _reticle(self, painter, width, dash_top):
        pix = self.pix["reticle"]
        if pix.isNull():
            return
        cx, cy = width / 2, dash_top / 2
        painter.drawPixmap(QPointF(cx - pix.width() / 2, cy - pix.height() / 2), pix)

    def _message(self, painter, width, dash_top, match, now, k):
        if not match.message or now > match.message_until:
            return
        font = QFont(self.label_family)
        font.setPixelSize(max(14, int(30 * k)))
        font.setLetterSpacing(QFont.PercentageSpacing, 110)
        painter.setFont(font)
        rect = QRectF(0, dash_top * 0.16, width, 60 * k)
        painter.setPen(QColor(0, 0, 0, 180))
        painter.drawText(rect.translated(2, 2), Qt.AlignCenter, match.message)
        painter.setPen(AMBER)
        painter.drawText(rect, Qt.AlignCenter, match.message)
