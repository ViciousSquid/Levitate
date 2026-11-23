"""Draw Levitate's original HUD, icon, sprite and texture art.

Every image is drawn here from primitives (no traced or imported artwork), in a
mid-1990s cockpit style: bevelled gunmetal panels, rivets, amber LED digits and
a teal CRT radar. Run from the repository root:

    python -m game.tools.make_art

Outputs (committed, so a build never needs to run this):

* ``game/assets/hud/``      dashboard, gauge face, radar bezel, LED digits
* ``game/assets/icons/``    power-up / pad / flag icons (64 px)
* ``assets/sprites/levitate/``  world billboards (flags, power-up orbs)
* ``game/assets/ui/``       launcher banner and level thumbnails frame
* ``assets/textures/levitate/``  block-out wall, floor and pad textures
* ``assets/splash.png``, ``assets/icon.png`` / ``icon.ico``  branding
"""

from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME = os.path.join(ROOT, "game", "assets")
FONT_DIR = os.path.join(ROOT, "assets", "fonts")
S = 4  # supersampling factor

# Palette ---------------------------------------------------------------------
GUN_HI = (150, 158, 170)
GUN = (92, 99, 112)
GUN_LO = (46, 50, 60)
GUN_DARK = (24, 26, 32)
AMBER = (255, 176, 48)
AMBER_DIM = (90, 52, 10)
TEAL = (64, 236, 200)
TEAL_DIM = (10, 60, 54)
RED = (230, 52, 52)
RED_HI = (255, 130, 120)
BLUE = (48, 112, 236)
BLUE_HI = (140, 186, 255)
LIME = (150, 240, 70)
WHITE = (240, 244, 250)


def font(name, size):
    for candidate in (os.path.join(FONT_DIR, name),
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def canvas(w, h, fill=(0, 0, 0, 0)):
    img = Image.new("RGBA", (w * S, h * S), fill)
    return img, ImageDraw.Draw(img)


def finish(img, w, h, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.resize((w, h), Image.LANCZOS).save(path)
    print("wrote", os.path.relpath(path, ROOT))


def sc(*values):
    return [v * S for v in values]


def bevel_rect(d, box, radius, base, hi, lo, width=3):
    """A raised panel: light top-left edge, dark bottom-right edge."""
    x0, y0, x1, y1 = box
    d.rounded_rectangle(sc(x0, y0, x1, y1), radius * S, fill=lo)
    d.rounded_rectangle(sc(x0, y0, x1 - width, y1 - width), radius * S, fill=hi)
    d.rounded_rectangle(sc(x0 + width, y0 + width, x1 - width, y1 - width), radius * S, fill=base)


def inset_rect(d, box, radius, base, width=3):
    """A recessed well: dark top-left edge, light bottom-right edge."""
    x0, y0, x1, y1 = box
    d.rounded_rectangle(sc(x0, y0, x1, y1), radius * S, fill=GUN_HI)
    d.rounded_rectangle(sc(x0, y0, x1 - width, y1 - width), radius * S, fill=GUN_DARK)
    d.rounded_rectangle(sc(x0 + width, y0 + width, x1 - width, y1 - width), radius * S, fill=base)


def rivet(d, x, y, r=4):
    d.ellipse(sc(x - r, y - r, x + r, y + r), fill=GUN_LO)
    d.ellipse(sc(x - r + 1, y - r + 1, x + r - 1, y + r - 1), fill=GUN_HI)
    d.ellipse(sc(x - r + 2, y - r + 2, x + r - 1, y + r - 1), fill=GUN)


def brushed(img, strength=10, seed=1):
    """Fine horizontal grain over the opaque pixels of *img*."""
    rnd = random.Random(seed)
    w, h = img.size
    grain = Image.new("L", (w, h), 128)
    gd = ImageDraw.Draw(grain)
    for y in range(0, h, 2):
        v = 128 + rnd.randint(-strength, strength)
        gd.line([(0, y), (w, y)], fill=v, width=2)
    grain = grain.filter(ImageFilter.GaussianBlur(1))
    r, g, b, a = img.split()
    out = Image.merge("RGB", (r, g, b))
    overlay = Image.merge("RGB", (grain, grain, grain))
    out = Image.blend(out, overlay, 0.08)
    out.putalpha(a)
    return out


# HUD -------------------------------------------------------------------------
from game.ui.hud_layout import (DASH_H, DASH_W, FLAGS_HOME, FLAGS_RIVAL,  # noqa: E402
                                RADAR, SHIELD, SLOTS, SPEEDO, TIMER)
FLAGS_RED, FLAGS_BLUE = FLAGS_RIVAL, FLAGS_HOME


def make_dashboard():
    w, h = DASH_W, DASH_H
    img, d = canvas(w, h)
    # Main console shape: a wide slab with a raised centre hood for the radar.
    body = [(0, 54), (470, 54), (510, 8), (770, 8), (810, 54), (1280, 54), (1280, 224), (0, 224)]
    d.polygon([(x * S, y * S) for x, y in body], fill=GUN_LO)
    inner = [(4, 58), (472, 58), (512, 12), (768, 12), (808, 58), (1276, 58), (1276, 224), (4, 224)]
    d.polygon([(x * S, y * S) for x, y in inner], fill=GUN_HI)
    core = [(7, 62), (475, 62), (515, 16), (765, 16), (805, 62), (1273, 62), (1273, 224), (7, 224)]
    d.polygon([(x * S, y * S) for x, y in core], fill=GUN)
    # Hazard stripe along the lip.
    for i in range(0, 470, 28):
        d.polygon(sc(i, 62, i + 14, 62, i + 6, 70, i - 8, 70), fill=(40, 40, 44))
        d.polygon(sc(i + 14, 62, i + 28, 62, i + 20, 70, i + 6, 70), fill=(214, 168, 40))
    for i in range(810, 1280, 28):
        d.polygon(sc(i, 62, i + 14, 62, i + 6, 70, i - 8, 70), fill=(40, 40, 44))
        d.polygon(sc(i + 14, 62, i + 28, 62, i + 20, 70, i + 6, 70), fill=(214, 168, 40))
    # Wells.
    d.ellipse(sc(*SPEEDO), fill=GUN_DARK)
    d.ellipse(sc(SPEEDO[0] + 4, SPEEDO[1] + 4, SPEEDO[2] - 2, SPEEDO[3] - 2), fill=GUN_HI)
    d.ellipse(sc(SPEEDO[0] + 6, SPEEDO[1] + 6, SPEEDO[2] - 4, SPEEDO[3] - 4), fill=(0, 0, 0, 0))
    inset_rect(d, (RADAR[0] - 8, RADAR[1] - 8, RADAR[2] + 8, RADAR[3] + 6), 14, GUN_DARK, 4)
    d.rounded_rectangle(sc(*RADAR), 10 * S, fill=(0, 0, 0, 0))
    for box in (FLAGS_RED, FLAGS_BLUE, SLOTS, TIMER, SHIELD):
        inset_rect(d, (box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4), 6, (12, 14, 18), 3)
    # Slot dividers.
    slot_w = (SLOTS[2] - SLOTS[0]) / 3
    for i in (1, 2):
        x = SLOTS[0] + slot_w * i
        d.line(sc(x, SLOTS[1] + 4, x, SLOTS[3] - 4), fill=GUN_LO, width=2 * S)
    # Rivets.
    for x in (18, 230, 520, 760, 1050, 1262):
        rivet(d, x, 80 if x not in (520, 760) else 30)
        rivet(d, x, 210)
    # Labels, stencilled.
    f = font("HornetDisplay-Regular.ttf", 13 * S)
    def label(text, x, y, fill=(214, 220, 230)):
        d.text(((x + 1) * S, (y + 1) * S), text, font=f, fill=(20, 22, 28))
        d.text((x * S, y * S), text, font=f, fill=fill)
    label("RIVAL FLAGS", 240, 44 + 2)
    label("HOME FLAGS", 240, 124 + 2)
    label("SYSTEMS", 772, 44 + 2)
    label("CLOCK", 1082, 44 + 2)
    label("SHIELD", 1082, 124 + 2)
    img = brushed(img, 14, seed=7)
    finish(img, w, h, os.path.join(GAME, "hud", "dashboard.png"))


def make_gauge_face():
    size = 160
    img, d = canvas(size, size)
    c = size / 2
    d.ellipse(sc(0, 0, size, size), fill=(14, 16, 20))
    d.ellipse(sc(6, 6, size - 6, size - 6), fill=(22, 26, 32))
    f = font("HornetDisplay-Regular.ttf", 13 * S)
    # Sweep from 225 deg (0) clockwise to -45 deg (max); 0..10 major marks.
    for i in range(0, 51):
        a = math.radians(225 - i * 270 / 50)
        major = i % 5 == 0
        r0 = c - (20 if major else 13)
        r1 = c - 9
        col = RED if i >= 40 else (AMBER if major else (150, 150, 150))
        d.line([((c + math.cos(a) * r0) * S, (c - math.sin(a) * r0) * S),
                ((c + math.cos(a) * r1) * S, (c - math.sin(a) * r1) * S)],
               fill=col, width=(3 if major else 1) * S)
        if major:
            rr = c - 32
            txt = str(i // 5)
            tw = d.textlength(txt, font=f)
            d.text(((c + math.cos(a) * rr) * S - tw / 2, (c - math.sin(a) * rr) * S - 7 * S),
                   txt, font=f, fill=WHITE)
    # Red-line arc.
    d.arc(sc(12, 12, size - 12, size - 12), start=-45 - 0, end=-45 + 54 - 0, fill=RED, width=3 * S)
    small = font("HornetDisplay-Regular.ttf", 9 * S)
    d.text(((c - 18) * S, (c + 28) * S), "x100", font=small, fill=(140, 140, 140))
    finish(img, size, size, os.path.join(GAME, "hud", "gauge_face.png"))


def make_radar_glass():
    w, h = RADAR[2] - RADAR[0], RADAR[3] - RADAR[1]
    img, d = canvas(w, h)
    d.rounded_rectangle(sc(0, 0, w, h), 10 * S, fill=(4, 20, 18, 255))
    # Graticule.
    for i in range(1, 4):
        d.line(sc(w * i / 4, 0, w * i / 4, h), fill=(20, 70, 60, 255), width=S)
        d.line(sc(0, h * i / 4, w, h * i / 4), fill=(20, 70, 60, 255), width=S)
    for r in (30, 60, 90):
        d.ellipse(sc(w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r), outline=(18, 60, 52, 255), width=S)
    finish(img, w, h, os.path.join(GAME, "hud", "radar_glass.png"))
    # Glass glare drawn above the radar's contents.
    img, d = canvas(w, h)
    d.polygon(sc(0, 0, w * 0.55, 0, w * 0.25, h * 0.45, 0, h * 0.6), fill=(255, 255, 255, 22))
    for y in range(0, h, 3):
        d.line(sc(0, y, w, y), fill=(0, 0, 0, 40), width=S)
    finish(img, w, h, os.path.join(GAME, "hud", "radar_glare.png"))


def make_crosshair():
    size = 48
    img, d = canvas(size, size)
    c = size / 2
    for a in (0, 90, 180, 270):
        r = math.radians(a)
        d.line([((c + math.cos(r) * 8) * S, (c + math.sin(r) * 8) * S),
                ((c + math.cos(r) * 18) * S, (c + math.sin(r) * 18) * S)], fill=(*TEAL, 220), width=2 * S)
    d.ellipse(sc(c - 2, c - 2, c + 2, c + 2), fill=(*TEAL, 220))
    finish(img, size, size, os.path.join(GAME, "hud", "reticle.png"))


# Icons -----------------------------------------------------------------------
ICON = 64


def icon_base(d, accent):
    bevel_rect(d, (2, 2, ICON - 2, ICON - 2), 10, (30, 34, 42), tuple(min(255, c + 40) for c in accent), GUN_DARK, 3)


def make_icons():
    out = os.path.join(GAME, "icons")
    # Spring: a coil on a base plate.
    img, d = canvas(ICON, ICON); icon_base(d, LIME)
    d.rectangle(sc(16, 48, 48, 53), fill=GUN_HI)
    pts = []
    for i in range(0, 121):
        t = i / 120
        y = 46 - t * 30
        x = 32 + math.sin(t * math.pi * 8) * 12
        pts.append((x * S, y * S))
    d.line(pts, fill=LIME, width=3 * S, joint="curve")
    d.rectangle(sc(18, 12, 46, 16), fill=GUN_HI)
    finish(img, ICON, ICON, os.path.join(out, "spring.png"))
    # Boost: stacked chevrons.
    img, d = canvas(ICON, ICON); icon_base(d, AMBER)
    for i, y in enumerate((14, 26, 38)):
        col = tuple(int(c * (0.55 + 0.15 * i)) for c in AMBER)
        d.polygon(sc(14, y + 14, 32, y, 50, y + 14, 50, y + 20, 32, y + 6, 14, y + 20), fill=col)
    finish(img, ICON, ICON, os.path.join(out, "boost.png"))
    # Barrier: a short brick wall rising.
    img, d = canvas(ICON, ICON); icon_base(d, (220, 120, 60))
    for row in range(4):
        y = 46 - row * 9
        off = 0 if row % 2 == 0 else 7
        for col in range(-1, 4):
            x = 12 + off + col * 14
            x0, x1 = max(12, x), min(52, x + 12)
            if x1 - x0 > 3:
                d.rectangle(sc(x0, y - 7, x1, y), fill=(196, 96, 52), outline=(90, 40, 20), width=S)
    d.polygon(sc(32, 4, 40, 12, 24, 12), fill=WHITE)
    finish(img, ICON, ICON, os.path.join(out, "barrier.png"))
    # Shield: a hex bubble.
    img, d = canvas(ICON, ICON); icon_base(d, TEAL)
    hexa = [(32 + 20 * math.cos(math.radians(60 * i + 30)), 32 + 20 * math.sin(math.radians(60 * i + 30)))
            for i in range(6)]
    d.polygon([(x * S, y * S) for x, y in hexa], fill=(*TEAL_DIM, 255), outline=TEAL, width=3 * S)
    d.polygon(sc(24, 22, 32, 18, 32, 30, 24, 34), fill=(*TEAL, 140))
    finish(img, ICON, ICON, os.path.join(out, "shield.png"))
    # Phantom (cloak): a dashed hull outline.
    img, d = canvas(ICON, ICON); icon_base(d, (170, 120, 255))
    hull = [(14, 40), (22, 26), (42, 26), (50, 40), (44, 46), (20, 46)]
    for i in range(len(hull)):
        (x0, y0), (x1, y1) = hull[i], hull[(i + 1) % len(hull)]
        for t in (0.0, 0.5):
            xa, ya = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            xb, yb = x0 + (x1 - x0) * (t + 0.3), y0 + (y1 - y0) * (t + 0.3)
            d.line(sc(xa, ya, xb, yb), fill=(200, 170, 255), width=3 * S)
    d.ellipse(sc(28, 30, 36, 38), fill=(200, 170, 255))
    finish(img, ICON, ICON, os.path.join(out, "phantom.png"))
    # Jammer: crossed arrows (reverses a rival's controls).
    img, d = canvas(ICON, ICON); icon_base(d, RED)
    d.line(sc(16, 20, 48, 44), fill=RED_HI, width=4 * S)
    d.line(sc(16, 44, 48, 20), fill=RED_HI, width=4 * S)
    d.polygon(sc(48, 44, 40, 44, 48, 36), fill=RED_HI)
    d.polygon(sc(16, 20, 24, 20, 16, 28), fill=RED_HI)
    finish(img, ICON, ICON, os.path.join(out, "jammer.png"))
    # Flags for the tally: filled and empty pennants per team.
    for team, col, hi in (("red", RED, RED_HI), ("blue", BLUE, BLUE_HI)):
        for state in ("full", "empty"):
            img, d = canvas(ICON, ICON)
            d.rectangle(sc(18, 8, 22, 58), fill=GUN_HI if state == "full" else GUN_LO)
            pennant = sc(22, 10, 52, 22, 22, 34)
            if state == "full":
                d.polygon(pennant, fill=col, outline=hi, width=2 * S)
                d.polygon(sc(22, 12, 34, 17, 22, 22), fill=hi)
            else:
                d.polygon(pennant, outline=(80, 84, 94), width=2 * S)
            finish(img, ICON, ICON, os.path.join(out, f"flag_{team}_{state}.png"))


# World sprites ---------------------------------------------------------------
def make_world_sprites():
    # In the world, so under assets/ where Fio's renderer resolves sprites.
    out = os.path.join(ROOT, "assets", "sprites", "levitate")
    for team, col, hi in (("red", RED, RED_HI), ("blue", BLUE, BLUE_HI)):
        w, h = 128, 192
        img, d = canvas(w, h)
        d.ellipse(sc(44, 178, 84, 190), fill=(0, 0, 0, 90))
        d.rectangle(sc(58, 20, 66, 184), fill=GUN_HI)
        d.rectangle(sc(62, 20, 66, 184), fill=GUN)
        d.ellipse(sc(54, 10, 70, 26), fill=AMBER)
        # A rippled pennant.
        top, bottom = [], []
        for i in range(0, 41):
            t = i / 40
            x = 66 + t * 56
            wave = math.sin(t * math.pi * 2) * 6
            top.append((x * S, (28 + t * 20 + wave) * S))
            bottom.append((x * S, (92 - t * 20 + wave) * S))
        d.polygon(top + bottom[::-1], fill=col)
        d.line(top, fill=hi, width=3 * S)
        d.ellipse(sc(80, 46, 100, 66), outline=WHITE, width=3 * S)
        finish(img, w, h, os.path.join(out, f"flag_{team}.png"))
    # Floating pickup orbs, one per power-up, wrapping the 64 px icon.
    for name in ("shield", "phantom", "barrier", "jammer"):
        icon = Image.open(os.path.join(GAME, "icons", f"{name}.png")).convert("RGBA")
        w = h = 96
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((4, 4, w - 4, h - 4), fill=(255, 255, 255, 70))
        glow = glow.filter(ImageFilter.GaussianBlur(6))
        img.alpha_composite(glow)
        img.alpha_composite(icon, (16, 16))
        path = os.path.join(out, f"pickup_{name}.png")
        img.save(path)
        print("wrote", os.path.relpath(path, ROOT))


# Textures --------------------------------------------------------------------
def noise_tile(size, base, spread, seed):
    rnd = random.Random(seed)
    img = Image.new("RGB", (size, size), base)
    px = img.load()
    for y in range(size):
        for x in range(size):
            n = rnd.randint(-spread, spread)
            px[x, y] = tuple(max(0, min(255, c + n)) for c in base)
    return img.filter(ImageFilter.GaussianBlur(0.6))


def make_textures():
    out = os.path.join(ROOT, "assets", "textures", "levitate")
    os.makedirs(out, exist_ok=True)
    size = 256
    # Block wall: big chunky blocks with bevels, in three colourways.
    for name, base in (("wall_slate", (96, 104, 120)), ("wall_sand", (170, 146, 104)),
                       ("wall_moss", (88, 118, 86))):
        img = noise_tile(size, base, 10, hash(name) & 0xffff)
        d = ImageDraw.Draw(img)
        for row in range(4):
            y0 = row * 64
            off = 0 if row % 2 == 0 else 64
            for col in range(-1, 3):
                x0 = col * 128 + off
                hi = tuple(min(255, c + 34) for c in base)
                lo = tuple(max(0, c - 44) for c in base)
                d.rectangle((x0, y0, x0 + 127, y0 + 63), outline=lo, width=3)
                d.line((x0 + 3, y0 + 3, x0 + 124, y0 + 3), fill=hi, width=2)
                d.line((x0 + 3, y0 + 3, x0 + 3, y0 + 60), fill=hi, width=2)
        img.save(os.path.join(out, f"{name}.png")); print("wrote", f"assets/textures/levitate/{name}.png")
    # Floor: a two-tone checker with fine grid -- the arena deck.
    img = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(img)
    for y in range(2):
        for x in range(2):
            col = (58, 62, 72) if (x + y) % 2 == 0 else (72, 78, 90)
            d.rectangle((x * 128, y * 128, x * 128 + 127, y * 128 + 127), fill=col)
    for i in range(0, size, 32):
        d.line((i, 0, i, size), fill=(48, 52, 60), width=1)
        d.line((0, i, size, i), fill=(48, 52, 60), width=1)
    img.save(os.path.join(out, "floor_deck.png")); print("wrote assets/textures/levitate/floor_deck.png")
    # Ceiling / sky-dark trim.
    noise_tile(size, (30, 32, 40), 6, 3).save(os.path.join(out, "trim_dark.png"))
    # Pads: glowing floor plates with their icon motif.
    for name, col in (("pad_spring", LIME), ("pad_boost", AMBER), ("pad_barrier", (220, 120, 60))):
        w = h = 128
        img, d = canvas(w, h)
        d.rectangle(sc(0, 0, w, h), fill=(22, 24, 30, 255))
        d.rounded_rectangle(sc(6, 6, w - 6, h - 6), 14 * S, fill=tuple(int(c * 0.25) for c in col) + (255,),
                            outline=col, width=4 * S)
        for k in range(4):
            r = 14 + k * 12
            d.ellipse(sc(w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r),
                      outline=tuple(int(c * (1 - k * 0.2)) for c in col) + (255,), width=2 * S)
        if name == "pad_boost":
            for y in (36, 60):
                d.polygon(sc(40, y + 20, 64, y, 88, y + 20, 88, y + 28, 64, y + 8, 40, y + 28), fill=col)
        finish(img, w, h, os.path.join(out, f"{name}.png"))


# Branding --------------------------------------------------------------------
def craft_silhouette(d, cx, cy, scale, body, trim, glow):
    """Levitate's hovercraft: a wedge hull over a skirt, twin fins and a
    canopy -- an original design, seen three-quarters from the front."""
    def p(*coords):
        if coords and isinstance(coords[0], tuple):
            pairs = coords
        else:
            pairs = list(zip(coords[0::2], coords[1::2]))
        return [((cx + x * scale) * S, (cy + y * scale) * S) for x, y in pairs]
    (sx0, sy0), (sx1, sy1) = p((-50, 18), (50, 34))
    d.ellipse((sx0, sy0, sx1, sy1), fill=(0, 0, 0, 80))                              # shadow
    d.polygon(p(-46, 10, -34, 22, 34, 22, 46, 10, 34, 4, -34, 4), fill=glow)            # skirt glow
    d.polygon(p(-44, 6, -30, -10, 30, -10, 44, 6, 30, 14, -30, 14), fill=body)          # hull
    d.polygon(p(-30, -10, -16, -24, 16, -24, 30, -10), fill=trim)                       # deck
    d.polygon(p(-12, -24, -6, -34, 6, -34, 12, -24), fill=(120, 220, 255))              # canopy
    d.polygon(p(-30, -10, -40, -30, -34, -30, -22, -12), fill=trim)                     # fin L
    d.polygon(p(30, -10, 40, -30, 34, -30, 22, -12), fill=trim)                         # fin R
    d.line(p(-44, 6, 44, 6), fill=WHITE, width=max(1, int(scale)) * S)


def make_branding():
    # App icon.
    size = 256
    img, d = canvas(size, size)
    d.rounded_rectangle(sc(8, 8, 248, 248), 48 * S, fill=(18, 22, 34))
    d.rounded_rectangle(sc(8, 8, 248, 248), 48 * S, outline=TEAL, width=6 * S)
    for r in (60, 90):
        d.arc(sc(128 - r * 1.4, 150 - r * 0.5, 128 + r * 1.4, 150 + r * 0.5), 0, 180, fill=(30, 90, 80), width=3 * S)
    craft_silhouette(d, 128, 140, 2.2, RED, (150, 30, 30), (*TEAL, 200))
    finish(img, size, size, os.path.join(ROOT, "assets", "icon.png"))
    Image.open(os.path.join(ROOT, "assets", "icon.png")).save(
        os.path.join(ROOT, "assets", "icon.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote assets/icon.ico")
    # Banner / splash: chrome wordmark over a perspective grid maze.
    for path, (w, h) in ((os.path.join(GAME, "ui", "banner.png"), (720, 240)),
                         (os.path.join(ROOT, "assets", "splash.png"), (455, 200))):
        img, d = canvas(w, h, (10, 12, 22, 255))
        horizon = h * 0.52
        for i in range(0, 24):
            t = i / 23
            y = horizon + (h - horizon) * (t ** 2)
            d.line(sc(0, y, w, y), fill=(20, 80 + int(60 * t), 72), width=S)
        for i in range(-12, 13):
            d.line(sc(w / 2 + i * 6, horizon, w / 2 + i * w / 8, h), fill=(20, 110, 96), width=S)
        # Sky gradient.
        for y in range(int(horizon)):
            t = y / horizon
            d.line(sc(0, y, w, y), fill=(int(14 + 30 * t), int(10 + 20 * t), int(40 + 50 * t)), width=S)
        craft_silhouette(d, w * 0.78, h * 0.70, h / 120, RED, (150, 30, 30), (*TEAL, 200))
        f = font("Rushfordclean-rgz89.otf", int(h * 0.30) * S)
        text = "LEVITATE!"
        tw = d.textlength(text, font=f)
        x, y = (w * 0.06) * S, (h * 0.14) * S
        d.text((x + 4 * S, y + 4 * S), text, font=f, fill=(0, 0, 0, 160))
        # Chrome: fill with a vertical gradient through a mask.
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).text((x, y), text, font=f, fill=255)
        grad = Image.new("RGBA", img.size)
        gd = ImageDraw.Draw(grad)
        top, bottom = int(y), int(y + h * 0.36 * S)
        for yy in range(top, bottom):
            t = (yy - top) / max(1, bottom - top)
            if t < 0.5:
                c = (int(250 - 90 * t), int(250 - 70 * t), 255)
            else:
                c = (int(120 + 200 * (t - 0.5)), int(90 + 120 * (t - 0.5)), int(60 + 40 * (t - 0.5)))
            gd.line([(0, yy), (img.size[0], yy)], fill=c + (255,))
        img.paste(grad, (0, 0), mask)
        edge = mask.filter(ImageFilter.FIND_EDGES)
        img.paste(Image.new("RGBA", img.size, (*TEAL, 255)), (0, 0), edge)
        sub = font("HornetDisplay-Regular.ttf", int(h * 0.075) * S)
        d.text((x + 6 * S, y + h * 0.36 * S), "CAPTURE  THE  FLAGS  ·  RULE  THE  MAZE", font=sub, fill=AMBER)
        finish(img, w, h, path)


def main():
    make_dashboard()
    make_gauge_face()
    make_radar_glass()
    make_crosshair()
    make_icons()
    make_world_sprites()
    make_textures()
    make_branding()
    make_hovercraft_sprites()


if __name__ == "__main__":
    main()


# Hovercraft: 8-direction monster sprites --------------------------------------
# A small faceted 3D model of Levitate!'s craft (the same original design as
# the app icon), rendered orthographically from eight bearings with flat
# shading, so every view agrees with the others.
#
# Fio's eight views (engine/monster_facing.py): file _1 is the front, _2
# front-left, _3 left, _4 back-left, _5 back, _6 back-right, _7 right and _8
# front-right. In the craft's own frame +Z is forward, +X is its left (as for
# Fio's player) and +Y is up; view k looks from a bearing of (k-1)*45 degrees
# from the nose, turning toward the craft's left.

HOVER_TEAMS = {
    # body, body shadow side, trim, stripe
    "red": ((206, 44, 44), (150, 26, 30), (120, 22, 26), (250, 236, 220)),
    "blue": ((46, 104, 220), (30, 70, 160), (24, 46, 112), (230, 240, 255)),
}
SPRITE_SIZE = 256
CRAFT_SCALE = 1.55        # model units -> sprite pixels
CAMERA_ELEVATION = 16.0   # degrees above the horizon


def _prism(bottom, top, colours):
    """Faces of a prism between two outlines given as [(x, z)] at heights
    (y0, y1): ``bottom = (y0, outline)``, ``top = (y1, outline)``.
    *colours* is ``(side, top, bottom)``; a side colour may be a callable
    ``f(index)`` for per-edge colour."""
    (y0, lo), (y1, hi) = bottom, top
    side, top_c, bottom_c = colours
    faces = []
    n = len(lo)
    for i in range(n):
        j = (i + 1) % n
        quad = [(lo[i][0], y0, lo[i][1]), (lo[j][0], y0, lo[j][1]),
                (hi[j][0], y1, hi[j][1]), (hi[i][0], y1, hi[i][1])]
        faces.append((quad, side(i) if callable(side) else side))
    faces.append(([(x, y1, z) for x, z in hi], top_c))
    faces.append(([(x, y0, z) for x, z in reversed(lo)], bottom_c))
    return faces


def _mirror(outline):
    """An outline given for the left half (x >= 0, nose to tail) mirrored into
    a closed loop."""
    return outline + [(-x, z) for x, z in reversed(outline)]


def hovercraft_model(team):
    body, shade, trim, stripe = HOVER_TEAMS[team]
    skirt_c = (44, 46, 54)
    faces = []
    # Skirt: a wide rounded footprint, dark rubber.
    skirt = []
    for i in range(16):
        a = math.radians(i * 360 / 16)
        skirt.append((math.sin(a) * 46, math.cos(a) * 62))
    faces += _prism((0, skirt), (12, [(x * 0.97, z * 0.97) for x, z in skirt]),
                    (skirt_c, skirt_c, skirt_c))
    # Hull: a wedge, narrow at the nose, broad at the tail.
    hull_lo = _mirror([(14, 64), (40, 30), (44, -20), (38, -52)])
    hull_hi = _mirror([(8, 48), (30, 22), (34, -18), (30, -46)])

    def hull_side(i):
        # The nose facets catch the stripe; the rest is body colour.
        return stripe if i in (0, len(hull_lo) - 1) else body
    faces += _prism((12, hull_lo), (30, hull_hi), (hull_side, body, shade))
    # Deck and cabin.
    deck = _mirror([(20, 14), (24, -16), (20, -40)])
    cabin_top = _mirror([(12, 0), (16, -16), (14, -32)])
    faces += _prism((30, deck), (46, cabin_top), (trim, trim, trim))
    # Canopy: a bright slanted glass panel on the cabin's front.
    faces.append(([(20, 30, 14), (-20, 30, 14), (-12, 46, 0), (12, 46, 0)], (130, 220, 255)))
    # Tail fins, left and right.
    for sx in (1, -1):
        fin_lo = [(sx * 24, -30), (sx * 30, -30), (sx * 30, -50), (sx * 24, -50)]
        fin_hi = [(sx * 30, -44), (sx * 34, -44), (sx * 34, -56), (sx * 30, -56)]
        faces += _prism((30, fin_lo if sx > 0 else fin_lo[::-1]),
                        (66, fin_hi if sx > 0 else fin_hi[::-1]), (body, stripe, shade))
    # Thruster: a glowing panel across the tail.
    faces.append(([(-22, 16, -51.5), (22, 16, -51.5), (20, 27, -47), (-20, 27, -47)], (255, 170, 60)))
    return faces


def _shade(colour, normal, light):
    lit = max(0.0, sum(n * l for n, l in zip(normal, light)))
    k = 0.45 + 0.65 * lit
    return tuple(max(0, min(255, int(c * k))) for c in colour[:3])


def render_hovercraft(team, view, flare=False, wreck=False):
    """One sprite: *view* 1..8 as Fio numbers them."""
    theta = math.radians((view - 1) * 45.0)
    elev = math.radians(CAMERA_ELEVATION)
    d = (math.sin(theta), 0.0, math.cos(theta))                  # craft -> camera
    right = (math.cos(theta), 0.0, -math.sin(theta))
    toward = (d[0] * math.cos(elev), math.sin(elev), d[2] * math.cos(elev))
    up = (-d[0] * math.sin(elev), math.cos(elev), -d[2] * math.sin(elev))
    light = (0.35, 0.85, 0.40)
    norm = math.sqrt(sum(v * v for v in light))
    light = tuple(v / norm for v in light)

    size = SPRITE_SIZE
    img, draw = canvas(size, size)
    cx, cy = size / 2, size * 0.66

    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    def project(p):
        if wreck:
            # Lying askew: rolled onto one side a little and sunk.
            x, y, z = p
            roll = math.radians(18)
            p = (x * math.cos(roll) - y * math.sin(roll),
                 x * math.sin(roll) + y * math.cos(roll) - 6, z)
        return ((cx + dot(p, right) * CRAFT_SCALE) * S,
                (cy - dot(p, up) * CRAFT_SCALE) * S), dot(p, toward)

    # The hover glow / shadow beneath.
    glow = (*TEAL, 110) if not wreck else (0, 0, 0, 90)
    gw, gh = 62 * CRAFT_SCALE, 62 * CRAFT_SCALE * math.sin(elev) * 1.4 + 8
    draw.ellipse(sc(cx - gw, cy + 6 - gh / 2, cx + gw, cy + 6 + gh / 2), fill=glow)

    polys = []
    for points, colour in hovercraft_model(team):
        a, b, c = points[0], points[1], points[2]
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        length = math.sqrt(dot(n, n)) or 1.0
        n = tuple(x / length for x in n)
        projected = [project(p) for p in points]
        depth = sum(z for _xy, z in projected) / len(projected)
        polys.append((depth, [xy for xy, _z in projected], colour, n))
    # Painter's algorithm: farthest first. Faces pointing away are skipped
    # unless the outline is flat (two-sided panels).
    for depth, pts, colour, n in sorted(polys, key=lambda item: item[0]):
        facing = dot(n, toward)
        if facing < -0.02 and len(pts) > 4:
            continue
        fill = colour if colour == (255, 170, 60) or colour == (130, 220, 255) else _shade(colour, n, light)
        if wreck:
            fill = tuple(int(c * 0.45) for c in fill)
        draw.polygon(pts, fill=fill + (255,), outline=(14, 14, 18, 255))
    if flare and not wreck:
        # Thruster flare, seen from behind and the sides only.
        tail, depth = project((0, 22, -60))
        if depth < 8:
            r = 16 * S
            draw.ellipse((tail[0] - r, tail[1] - r * 0.7, tail[0] + r, tail[1] + r * 0.7),
                         fill=(255, 210, 120, 200))
    if wreck:
        for i in range(5):
            x = cx - 20 + i * 11
            draw.ellipse(sc(x - 9, cy - 70 - i * 7, x + 9, cy - 52 - i * 7), fill=(60, 60, 66, 150))
    return img


def make_hovercraft_sprites():
    """assets/sprites/monsters/hovercraft/ (red) and .../hovercraft/blue/:
    idle_1..8, shoot_1..8 (thrusters lit), dead, and idle/shoot (front)."""
    base = os.path.join(ROOT, "assets", "sprites", "monsters", "hovercraft")
    for team, folder in (("red", base), ("blue", os.path.join(base, "blue"))):
        for view in range(1, 9):
            finish(render_hovercraft(team, view), SPRITE_SIZE, SPRITE_SIZE,
                   os.path.join(folder, f"idle_{view}.png"))
            finish(render_hovercraft(team, view, flare=True), SPRITE_SIZE, SPRITE_SIZE,
                   os.path.join(folder, f"shoot_{view}.png"))
        finish(render_hovercraft(team, 1), SPRITE_SIZE, SPRITE_SIZE, os.path.join(folder, "idle.png"))
        finish(render_hovercraft(team, 1, flare=True), SPRITE_SIZE, SPRITE_SIZE,
               os.path.join(folder, "shoot.png"))
        finish(render_hovercraft(team, 2, wreck=True), SPRITE_SIZE, SPRITE_SIZE,
               os.path.join(folder, "dead.png"))
