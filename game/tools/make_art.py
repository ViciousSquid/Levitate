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


def make_icons(capture=None):
    """Draw the 64 px icons. With *capture* (a dict), nothing is written:
    each icon's supersampled drawing is stored there by name instead, for
    art built from the same glyphs (the power-up models' faces)."""
    out = os.path.join(GAME, "icons")

    def done(img, w, h, path):
        if capture is None:
            finish(img, w, h, path)
        else:
            capture[os.path.splitext(os.path.basename(path))[0]] = img
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
    done(img, ICON, ICON, os.path.join(out, "spring.png"))
    # Boost: stacked chevrons.
    img, d = canvas(ICON, ICON); icon_base(d, AMBER)
    for i, y in enumerate((14, 26, 38)):
        col = tuple(int(c * (0.55 + 0.15 * i)) for c in AMBER)
        d.polygon(sc(14, y + 14, 32, y, 50, y + 14, 50, y + 20, 32, y + 6, 14, y + 20), fill=col)
    done(img, ICON, ICON, os.path.join(out, "boost.png"))
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
    done(img, ICON, ICON, os.path.join(out, "barrier.png"))
    # Shield: a hex bubble.
    img, d = canvas(ICON, ICON); icon_base(d, TEAL)
    hexa = [(32 + 20 * math.cos(math.radians(60 * i + 30)), 32 + 20 * math.sin(math.radians(60 * i + 30)))
            for i in range(6)]
    d.polygon([(x * S, y * S) for x, y in hexa], fill=(*TEAL_DIM, 255), outline=TEAL, width=3 * S)
    d.polygon(sc(24, 22, 32, 18, 32, 30, 24, 34), fill=(*TEAL, 140))
    done(img, ICON, ICON, os.path.join(out, "shield.png"))
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
    done(img, ICON, ICON, os.path.join(out, "phantom.png"))
    # Jammer: crossed arrows (reverses a rival's controls).
    img, d = canvas(ICON, ICON); icon_base(d, RED)
    d.line(sc(16, 20, 48, 44), fill=RED_HI, width=4 * S)
    d.line(sc(16, 44, 48, 20), fill=RED_HI, width=4 * S)
    d.polygon(sc(48, 44, 40, 44, 48, 36), fill=RED_HI)
    d.polygon(sc(16, 20, 24, 20, 16, 28), fill=RED_HI)
    done(img, ICON, ICON, os.path.join(out, "jammer.png"))
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
            done(img, ICON, ICON, os.path.join(out, f"flag_{team}_{state}.png"))


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


# Branding --------------------------------------------------------------------
# Levitate!'s logo is its hovercraft: the faceted red craft of the sprites
# (render_hovercraft, below), seen from the front left. The app icon, the
# console's logo and the mark on the launcher and splash are all that render.
#
# The launcher and splash set it in a 1990s synthwave scene -- a slatted sun
# over a neon grid, a few Memphis shapes -- and the launcher stands on a
# blacklight bowling-alley carpet (make_carpet).
HOT_PINK = (255, 46, 160)
NEON_CYAN = (40, 240, 255)
NEON_YELLOW = (255, 232, 60)
NEON_LIME = (140, 255, 80)
NEON_ORANGE = (255, 140, 40)
NEON_PURPLE = (170, 90, 255)


def craft_logo(height, glow=True):
    """The logo: the red hovercraft, front-left, *height* pixels tall
    (RGBA, cropped to the craft)."""
    scale = height / 118.0
    size = int(256 * scale)
    art = render_hovercraft("red", 2, size=size, scale=CRAFT_SCALE * scale, glow=glow)
    art = art.resize((size, size), Image.LANCZOS)
    return art.crop(art.getbbox())


def _vertical_gradient(size, stops):
    """An RGB image shaded top to bottom through *stops*: ``[(t, colour)]``."""
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = (t - t0) / max(1e-6, t1 - t0)
                d.line([(0, y), (w, y)], fill=tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(3)))
                break
    return img


def synthwave_scene(w, h, wordmark=True, seed=7):
    """The launcher banner / splash: a slatted sun going down behind a neon
    grid, the craft hovering over it, the wordmark across the sky."""
    rng = random.Random(seed)
    W, H = w * S, h * S
    horizon = int(H * 0.60)
    img = _vertical_gradient((W, H), [(0.0, (18, 8, 48)), (0.34, (74, 16, 110)),
                                      (0.56, (214, 30, 140)), (0.60, (255, 120, 150)),
                                      (0.601, (10, 4, 30)), (1.0, (26, 8, 60))]).convert("RGBA")
    d = ImageDraw.Draw(img)
    for _ in range(int(w * h / 900)):
        x, y = rng.random() * W, rng.random() * horizon * 0.8
        r = rng.choice((1, 1, 1, 2)) * S * 0.5
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 235, 255, rng.randint(90, 230)))
    # The sun: yellow through orange to pink, cut by slats that widen downward.
    radius = int(H * 0.40)
    cx, cy = int(W * 0.70), horizon - int(H * 0.06)
    sun = _vertical_gradient((radius * 2, radius * 2), [(0.0, (255, 236, 90)), (0.5, (255, 130, 60)),
                                                        (1.0, (255, 40, 150))])
    mask = Image.new("L", sun.size, 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((0, 0, radius * 2, radius * 2), fill=255)
    y, gap, bar = int(radius * 0.95), S * 2, S * 9
    while y < radius * 2:
        md.rectangle((0, y, radius * 2, y + gap), fill=0)
        y += gap + bar
        gap += int(S * 1.6)
        bar = max(S * 3, bar - S)
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((cx - radius * 1.25, cy - radius * 1.25, cx + radius * 1.25,
                                  cy + radius * 1.25), fill=(255, 90, 170, 80))
    img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(radius * 0.22)))
    sky = img.crop((0, 0, W, horizon))
    sky.paste(sun, (cx - radius, cy - radius), mask)
    img.paste(sky, (0, 0))
    d = ImageDraw.Draw(img)
    # Memphis shapes in the sky: a triangle, a field of dots, a squiggle.
    tri = [(W * 0.035, H * 0.50), (W * 0.115, H * 0.50), (W * 0.075, H * 0.30)]
    d.line(tri + [tri[0]], fill=(*NEON_CYAN, 255), width=S * 2, joint="curve")
    for i in range(6):
        for j in range(3):
            x, y = W * 0.44 + i * S * 7, H * 0.07 + j * S * 7
            d.ellipse((x - S * 1.4, y - S * 1.4, x + S * 1.4, y + S * 1.4), fill=(*NEON_YELLOW, 255))
    squiggle = [(W * 0.90 + i * S * 5, H * 0.10 + (S * 5 if i % 2 else 0)) for i in range(9)]
    d.line(squiggle, fill=(*NEON_LIME, 255), width=S * 2, joint="curve")
    # The grid: lines to the vanishing point, and rows closing on the horizon.
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for i in range(-18, 19):
        gd.line((W / 2 + i * W * 0.035, horizon, W / 2 + i * W * 0.22, H), fill=(*NEON_CYAN, 255), width=S)
    for i in range(1, 15):
        y = horizon + (H - horizon) * (i / 14.0) ** 2.2
        gd.line((0, y, W, y), fill=(*NEON_CYAN, 255), width=S)
    img.alpha_composite(grid.filter(ImageFilter.GaussianBlur(S * 2.2)))
    img.alpha_composite(grid)
    d = ImageDraw.Draw(img)
    d.line((0, horizon, W, horizon), fill=(255, 220, 255, 255), width=S * 2)
    # The craft, hovering over the grid in front of the sun.
    craft = craft_logo(int(H * 0.56))
    img.alpha_composite(craft, (int(cx - craft.width * 0.5), int(H * 0.93 - craft.height)))
    if wordmark:
        text = "LEVITATE!"
        f = font("Rushfordclean-rgz89.otf", int(H * 0.36))
        d = ImageDraw.Draw(img)
        tw = int(d.textlength(text, font=f))
        th = int(H * 0.40)
        layer = Image.new("RGBA", (tw + th, th + S * 12), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ox, oy = int(th * 0.3), S * 4
        ld.text((ox + S * 5, oy + S * 5), text, font=f, fill=(*NEON_CYAN, 255))
        ld.text((ox + S * 2, oy + S * 2), text, font=f, fill=(40, 8, 70, 255))
        face = Image.new("L", layer.size, 0)
        ImageDraw.Draw(face).text((ox, oy), text, font=f, fill=255)
        fill = _vertical_gradient(layer.size, [(0.0, (255, 250, 200)), (0.45, (255, 232, 60)),
                                               (0.55, (255, 90, 170)), (1.0, (255, 46, 160))])
        layer.paste(fill, (0, 0), face)
        # Slanted, as if written at speed.
        layer = layer.transform(layer.size, Image.AFFINE, (1, 0.24, -th * 0.24, 0, 1, 0),
                                resample=Image.BICUBIC)
        x, y = int(W * 0.035), int(H * 0.085)
        img.alpha_composite(layer, (x, y))
        d = ImageDraw.Draw(img)
        d.line((x + th * 0.2, y + th * 0.99, x + tw * 0.92, y + th * 0.91), fill=(*HOT_PINK, 255), width=S * 3)
        sub = font("HornetDisplay-Regular.ttf", int(H * 0.066))
        d.text((x + th * 0.22, y + th * 1.04), "CAPTURE  THE  FLAGS  /  RULE  THE  MAZE",
               font=sub, fill=(*NEON_CYAN, 255))
    return img.resize((w, h), Image.LANCZOS)


def make_carpet(size=384, seed=1994):
    """A tile of blacklight bowling-alley carpet: neon squiggles, stars and
    confetti on near-black. Seamless: every shape is drawn wrapped."""
    rng = random.Random(seed)
    W = size * S
    img = Image.new("RGBA", (W, W), (9, 5, 20, 255))
    colours = (HOT_PINK, NEON_CYAN, NEON_LIME, NEON_ORANGE, NEON_PURPLE, NEON_YELLOW)

    def wrapped(draw_at):
        for dx in (-W, 0, W):
            for dy in (-W, 0, W):
                draw_at(dx, dy)

    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(15):
        colour = rng.choice(colours) + (255,)
        x, y = rng.random() * W, rng.random() * W
        kind = rng.choice(("swirl", "swirl", "star", "zigzag", "ring", "triangle"))
        r = rng.uniform(0.06, 0.13) * W
        turn = rng.random() * 360
        width = int(S * rng.uniform(2.5, 4.5))
        if kind == "swirl":
            wrapped(lambda dx, dy: d.arc((x - r + dx, y - r + dy, x + r + dx, y + r + dy),
                                         turn, turn + rng.choice((200, 250, 290)), fill=colour, width=width))
        elif kind == "ring":
            wrapped(lambda dx, dy: d.ellipse((x - r * 0.4 + dx, y - r * 0.4 + dy, x + r * 0.4 + dx,
                                              y + r * 0.4 + dy), outline=colour, width=width))
        elif kind == "star":
            pts = []
            for i in range(10):
                rad = r * (0.62 if i % 2 == 0 else 0.26)
                ang = math.radians(turn + i * 36)
                pts.append((x + math.cos(ang) * rad, y + math.sin(ang) * rad))
            wrapped(lambda dx, dy: d.line([(px + dx, py + dy) for px, py in pts + [pts[0]]],
                                          fill=colour, width=width, joint="curve"))
        elif kind == "triangle":
            pts = [(x + math.cos(math.radians(turn + i * 120)) * r * 0.5,
                    y + math.sin(math.radians(turn + i * 120)) * r * 0.5) for i in range(3)]
            wrapped(lambda dx, dy: d.line([(px + dx, py + dy) for px, py in pts + [pts[0]]],
                                          fill=colour, width=width, joint="curve"))
        else:
            ang = math.radians(turn)
            pts = [(x + math.cos(ang) * i * r * 0.28 - math.sin(ang) * (r * 0.16 if i % 2 else -r * 0.16),
                    y + math.sin(ang) * i * r * 0.28 + math.cos(ang) * (r * 0.16 if i % 2 else -r * 0.16))
                   for i in range(6)]
            wrapped(lambda dx, dy: d.line([(px + dx, py + dy) for px, py in pts],
                                          fill=colour, width=width, joint="curve"))
    for _ in range(70):
        colour = rng.choice(colours) + (255,)
        x, y, r = rng.random() * W, rng.random() * W, S * rng.uniform(1.0, 2.2)
        wrapped(lambda dx, dy: d.ellipse((x - r + dx, y - r + dy, x + r + dx, y + r + dy), fill=colour))
    glow = layer.filter(ImageFilter.GaussianBlur(S * 3))
    img.alpha_composite(glow)
    img.alpha_composite(layer)
    # Dimmed: it is the floor the launcher stands on, not the launcher.
    img = Image.blend(img, Image.new("RGBA", (W, W), (9, 5, 20, 255)), 0.42)
    finish(img.convert("RGB"), size, size, os.path.join(GAME, "ui", "carpet.png"))


def make_branding():
    # The logo: the craft alone. App icon (and its .ico), and the editor
    # console's logo.
    size = 256
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    craft = craft_logo(190)
    if craft.width > size - 8:
        craft = craft.resize((size - 8, int(craft.height * (size - 8) / craft.width)), Image.LANCZOS)
    icon.alpha_composite(craft, ((size - craft.width) // 2, (size - craft.height) // 2))
    path = os.path.join(ROOT, "assets", "icon.png")
    icon.save(path)
    print("wrote assets/icon.png")
    icon.save(os.path.join(ROOT, "assets", "icon.ico"),
              sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote assets/icon.ico")
    logo = Image.new("RGBA", (318, 172), (0, 0, 0, 0))
    craft = craft_logo(150)
    logo.alpha_composite(craft, ((318 - craft.width) // 2, (172 - craft.height) // 2))
    logo.save(os.path.join(ROOT, "assets", "logo.png"))
    print("wrote assets/logo.png")
    # The launcher's banner and the splash: the craft in its synthwave scene.
    synthwave_scene(720, 240).convert("RGB").save(os.path.join(GAME, "ui", "banner.png"))
    print("wrote game/assets/ui/banner.png")
    synthwave_scene(455, 200).convert("RGB").save(os.path.join(ROOT, "assets", "splash.png"))
    print("wrote assets/splash.png")
    make_carpet()


def main():
    make_dashboard()
    make_gauge_face()
    make_radar_glass()
    make_crosshair()
    make_icons()
    make_world_sprites()
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


def render_hovercraft(team, view, flare=False, wreck=False, size=None, scale=None, glow=True):
    """One sprite: *view* 1..8 as Fio numbers them. *size* and *scale* draw
    it larger than a sprite (the logo); *glow* is the hover light beneath."""
    theta = math.radians((view - 1) * 45.0)
    elev = math.radians(CAMERA_ELEVATION)
    d = (math.sin(theta), 0.0, math.cos(theta))                  # craft -> camera
    right = (math.cos(theta), 0.0, -math.sin(theta))
    toward = (d[0] * math.cos(elev), math.sin(elev), d[2] * math.cos(elev))
    up = (-d[0] * math.sin(elev), math.cos(elev), -d[2] * math.sin(elev))
    light = (0.35, 0.85, 0.40)
    norm = math.sqrt(sum(v * v for v in light))
    light = tuple(v / norm for v in light)

    size = size or SPRITE_SIZE
    CRAFT_SCALE = scale or globals()["CRAFT_SCALE"]
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
    if glow:
        under = (*TEAL, 110) if not wreck else (0, 0, 0, 90)
        gw, gh = 62 * CRAFT_SCALE, 62 * CRAFT_SCALE * math.sin(elev) * 1.4 + 8
        draw.ellipse(sc(cx - gw, cy + 6 - gh / 2, cx + gw, cy + 6 + gh / 2), fill=under)

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
