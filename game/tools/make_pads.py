"""Draw Levitate's pad plates: the spring, boost and barrier pads.

Each is a steel plate with a bevelled frame and a glowing emblem, synthesised
here from noise and geometry (numpy + Pillow only). Run from the repository
root:

    python -m game.tools.make_pads
    python -m game.tools.make_pads --preview /tmp/pads   # + contact sheets

Outputs go to ``assets/textures/levitate/`` (committed, so a build never needs
to run this), in the layout Fio's physically shaded frame reads:

``pad_<kind>.png``  RGBA
    Base colour, sRGB, flat-lit.
``pad_<kind>_n.png``  RGBA
    RGB = tangent-space normal, OpenGL convention; A = height (255 = highest).
``pad_<kind>_m.png``  RGBA
    R = ambient occlusion, G = roughness, B = metalness, A = 255 - emission:
    the emblem emits its own colour.

The walls and floors the pads sit among are photo-scanned materials; see
game/tools/fetch_textures.py.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "assets", "textures", "levitate")
F = np.float32


# =============================================================================
# Small maths helpers
# =============================================================================

def rgb(r, g, b):
    """An sRGB colour given as 0-255 components."""
    return np.array([r, g, b], F) / F(255.0)


def sat(x):
    return np.clip(x, 0.0, 1.0)


def smooth(a, b, x):
    """Smoothstep from ``a`` to ``b`` (works with a > b for a falling edge)."""
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(F)


def lerp(a, b, t):
    return a + (b - a) * t


def mixc(base, colour, t):
    """Blend an (H, W, 3) image towards a colour (or image) by mask ``t``."""
    return base + (colour - base) * t[..., None]


def tint(base, factor):
    """Multiply an (H, W, 3) image by a per-pixel scalar."""
    return base * factor[..., None]


def grid(shape):
    """Pixel-centre coordinates (X, Y) as float32 arrays."""
    h, w = shape
    y, x = np.mgrid[0:h, 0:w]
    return x.astype(F) + F(0.5), y.astype(F) + F(0.5)


_FREQ = {}


def _freq(shape):
    if shape not in _FREQ:
        h, w = shape
        fy = np.fft.fftfreq(h).astype(F)[:, None]
        fx = np.fft.rfftfreq(w).astype(F)[None, :]
        _FREQ[shape] = (fx, fy)
    return _FREQ[shape]


def noise(shape, seed, scale, beta=1.8, sx=1.0, sy=1.0, lo=None):
    """Seamlessly tiling gaussian noise synthesised in the frequency domain.

    ``scale`` is the dominant feature wavelength in pixels; above that
    frequency the amplitude falls as f^-beta (a fractal, fBm-like roll-off).
    ``sx`` / ``sy`` > 1 stretch features along x / y.  ``lo`` (pixels) removes
    wavelengths longer than itself.  Output has zero mean and unit variance.
    """
    h, w = shape
    r = np.random.default_rng(seed)
    spec = np.fft.rfft2(r.standard_normal((h, w), dtype=F))
    fx, fy = _freq(shape)
    f2 = (fx * sx) ** 2 + (fy * sy) ** 2
    f0 = 1.0 / scale
    amp = (1.0 + f2 / (f0 * f0)) ** (-beta / 2.0)
    if lo is not None:
        amp = amp * (1.0 - np.exp(-f2 * (lo * lo) * 4.0))
    amp[0, 0] = 0.0
    out = np.fft.irfft2(spec * amp, s=(h, w)).astype(F)
    out -= out.mean()
    out /= out.std() + 1e-9
    return out


def blur(a, sigma, wrap_y=True):
    """Gaussian blur with wrap-around in x (and in y unless ``wrap_y`` False)."""
    if sigma <= 0:
        return a
    a = np.asarray(a, F)
    pad = 0
    if not wrap_y:
        pad = int(min(a.shape[0] - 1, math.ceil(sigma * 3.5)))
        a = np.pad(a, ((pad, pad), (0, 0)), mode="reflect")
    fx, fy = _freq(a.shape)
    g = np.exp(-2.0 * (math.pi * sigma) ** 2 * (fx * fx + fy * fy))
    out = np.fft.irfft2(np.fft.rfft2(a) * g, s=a.shape).astype(F)
    if pad:
        out = out[pad:-pad]
    return out


def sample(img, X, Y):
    """Bilinear lookup of a tiling image at (possibly warped) pixel centres."""
    h, w = img.shape[:2]
    x = X - 0.5
    y = Y - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    tx = (x - x0).astype(F)
    ty = (y - y0).astype(F)
    x1 = (x0 + 1) % w
    y1 = (y0 + 1) % h
    x0 %= w
    y0 %= h
    if img.ndim == 3:
        tx = tx[..., None]
        ty = ty[..., None]
    top = img[y0, x0] * (1 - tx) + img[y0, x1] * tx
    bot = img[y1, x0] * (1 - tx) + img[y1, x1] * tx
    return top * (1 - ty) + bot * ty


def worley(X, Y, period, cells, seed, jitter=1.0):
    """Tiling cellular noise evaluated at pixel coords (X, Y).

    ``period`` = (W, H) in pixels, ``cells`` = (cx, cy) feature points per
    period.  Returns (f1, f2, cell_id): the distances in pixels to the nearest
    and second-nearest feature point and the id of the nearest.
    """
    W, H = period
    cx, cy = cells
    r = np.random.default_rng(seed)
    jx = (0.5 + (r.random((cy, cx), dtype=F) - 0.5) * jitter)
    jy = (0.5 + (r.random((cy, cx), dtype=F) - 0.5) * jitter)
    sx = W / cx
    sy = H / cy
    gx = X / F(sx)
    gy = Y / F(sy)
    ix = np.floor(gx).astype(np.int32)
    iy = np.floor(gy).astype(np.int32)
    f1 = np.full(X.shape, 1e9, F)
    f2 = np.full(X.shape, 1e9, F)
    cid = np.zeros(X.shape, np.int32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nx = ix + dx
            ny = iy + dy
            mx = nx % cx
            my = ny % cy
            px = (nx + jx[my, mx] - gx) * F(sx)
            py = (ny + jy[my, mx] - gy) * F(sy)
            d = np.sqrt(px * px + py * py)
            closer = d < f1
            f2 = np.where(closer, f1, np.minimum(f2, d))
            cid = np.where(closer, my * cx + mx, cid)
            f1 = np.where(closer, d, f1)
    return f1, f2, cid


def spots(X, Y, period, cells, seed, rmin, rmax, keep=1.0, jitter=1.0):
    """Scattered round blobs: at most one per cell of a jittered grid.

    Returns (t, cell_id) where t = distance / radius of that cell's blob
    (t < 1 inside the blob; cells dropped by ``keep`` return a large t).
    """
    f1, _f2, cid = worley(X, Y, period, cells, seed, jitter)
    r = np.random.default_rng(seed + 7919)
    n = cells[0] * cells[1]
    rad = (rmin + (rmax - rmin) * r.random(n) ** 2).astype(F)
    alive = r.random(n) < keep
    rad = np.where(alive, rad, F(1e-3)).astype(F)
    return f1 / rad[cid], cid


def stamp_dist(shape, pts, wrap_y=True):
    """Distance (px) to the nearest of a few points ``(x, y)``, wrapping in x."""
    h, w = shape
    X, Y = grid(shape)
    d = np.full(shape, 1e9, F)
    idx = np.zeros(shape, np.int32)
    for i, (px, py) in enumerate(pts):
        dx = np.abs(X - px)
        dx = np.minimum(dx, w - dx)
        dy = np.abs(Y - py)
        if wrap_y:
            dy = np.minimum(dy, h - dy)
        dd = np.sqrt(dx * dx + dy * dy)
        m = dd < d
        d = np.where(m, dd, d)
        idx = np.where(m, i, idx)
    return d, idx


def drip(src, decay_px, spread=0.0):
    """Smear a source map down the image (rain streaks, rust runs)."""
    h, w = src.shape
    out = np.empty_like(src)
    acc = np.zeros(w, F)
    k = np.exp(-1.0 / np.asarray(decay_px, F)).astype(F)
    for y in range(h):
        acc = acc * k + src[y]
        if spread:
            acc = acc + F(spread) * (np.roll(acc, 1) + np.roll(acc, -1) - 2 * acc)
        out[y] = acc
    return out


def level_dist(n):
    """Approximate distance in pixels to the zero level-set of a smooth field."""
    gx = (np.roll(n, -1, 1) - np.roll(n, 1, 1)) * 0.5
    gy = (np.roll(n, -1, 0) - np.roll(n, 1, 0)) * 0.5
    return np.abs(n) / (np.sqrt(gx * gx + gy * gy) + 1e-6)


def rank(n):
    """Map a noise field to its percentile (0..1), so thresholds are areas."""
    flat = n.ravel()
    order = np.argsort(flat, kind="stable")
    out = np.empty(flat.size, F)
    out[order] = np.linspace(0.0, 1.0, flat.size, dtype=F)
    return out.reshape(n.shape)


def crack_mask(shape, seed, n, length, width, wander=0.18, kink=0.04, branch=0.0, pull=0.03,
               step=4.0, ss=3, kink_mag=0.8):
    """Random-walk crack polylines drawn with wrap-around; returns a 0..1 mask.

    ``length`` and ``width`` are in pixels; cracks taper towards their ends and
    may fork (``branch`` = chance per step).
    """
    H, W = shape
    img = Image.new("L", (W * ss, H * ss), 0)
    d = ImageDraw.Draw(img)
    r = np.random.default_rng(seed)
    todo = []
    for i in range(n):
        x, y, th = r.uniform(0, W), r.uniform(0, H), r.uniform(0, 2 * math.pi)
        todo.append((x, y, th, length * r.uniform(0.6, 1.3), width, 0))
    while todo:
        x, y, th, L, wd, depth = todo.pop()
        th0 = th
        steps = max(2, int(L / step))
        for i in range(steps):
            th += r.normal() * wander + (th0 - th) * pull
            if r.random() < kink:
                th += r.normal() * kink_mag
            dx, dy = math.cos(th) * step, math.sin(th) * step
            f = i / steps
            wseg = wd * min(1.0, 5 * (1 - f) + 0.2) * min(1.0, 8 * f + 0.4) * (0.75 + 0.5 * r.random())
            lw = max(1, int(round(wseg * ss)))
            bx, by = x % W, y % H
            for ox in (-W, 0, W):
                for oy in (-H, 0, H):
                    x0, y0 = (bx + ox) * ss, (by + oy) * ss
                    x1, y1 = x0 + dx * ss, y0 + dy * ss
                    if max(x0, x1) < -lw or min(x0, x1) > W * ss + lw:
                        continue
                    if max(y0, y1) < -lw or min(y0, y1) > H * ss + lw:
                        continue
                    d.line([x0, y0, x1, y1], fill=255, width=lw)
                    if lw > 2:
                        d.ellipse([x1 - lw / 2, y1 - lw / 2, x1 + lw / 2, y1 + lw / 2], fill=255)
            if branch and depth < 2 and r.random() < branch:
                todo.append((x, y, th + r.choice([-1, 1]) * r.uniform(0.5, 1.2),
                             L * (1 - f) * r.uniform(0.3, 0.7), wd * 0.7, depth + 1))
            x += dx
            y += dy
    return np.asarray(img.resize((W, H), Image.BOX), F) / F(255.0)


def per_stone(src, X, Y, sid, n, seed):
    """Sample a noise field with a different random offset for every stone."""
    H, W = src.shape
    r = np.random.default_rng(seed)
    oy = r.integers(0, H, n)[sid]
    ox = r.integers(0, W, n)[sid]
    return src[(np.floor(Y).astype(np.int64) + oy) % H, (np.floor(X).astype(np.int64) + ox) % W]


# =============================================================================
# Masonry: rectangles on a torus -> per-pixel stone id and signed distance
# =============================================================================

class Masonry:
    """A wall/paving bond described as rectangles that tile the texture."""

    def __init__(self, W, H):
        self.W, self.H = W, H
        self.x0, self.y0, self.w, self.h = [], [], [], []

    def add(self, x0, y0, w, h):
        self.x0.append(x0)
        self.y0.append(y0)
        self.w.append(w)
        self.h.append(h)

    @property
    def n(self):
        return len(self.x0)

    def id_map(self):
        W, H = self.W, self.H
        ids = np.full((H, W), -1, np.int32)
        for i in range(self.n):
            xs = np.arange(math.ceil(self.x0[i] - 0.5), math.ceil(self.x0[i] + self.w[i] - 0.5)) % W
            ys = np.arange(math.ceil(self.y0[i] - 0.5), math.ceil(self.y0[i] + self.h[i] - 0.5)) % H
            ids[np.ix_(ys, xs)] = i
        assert (ids >= 0).all(), "masonry layout leaves gaps"
        return ids

    def evaluate(self, X, Y, seed, joint, joint_var=0.0, radius=1.0, radius_var=0.0,
                 rot=0.0, shift=0.0):
        """Signed distance (px, < 0 inside a stone) at warped coords (X, Y).

        ``joint`` is the mortar width in px; each stone gets its own inset,
        corner radius, small rotation (radians) and positional shift (px).
        Returns dict(id, d, px, py, hx, hy): stone id, distance, local
        coordinates relative to the stone centre and the stone half-sizes.
        """
        W, H = self.W, self.H
        r = np.random.default_rng(seed)
        n = self.n
        ids = self.id_map()
        sid = ids[np.floor(Y).astype(np.int64) % H, np.floor(X).astype(np.int64) % W]
        w = np.array(self.w, F)
        h = np.array(self.h, F)
        cx = (np.array(self.x0, F) + w / 2 + (r.random(n) - 0.5) * 2 * shift).astype(F)
        cy = (np.array(self.y0, F) + h / 2 + (r.random(n) - 0.5) * 2 * shift).astype(F)
        inset = (joint / 2 + (r.random(n) - 0.5) * joint_var).astype(F)
        hx = np.maximum(w / 2 - inset, 1.0).astype(F)
        hy = np.maximum(h / 2 - (joint / 2 + (r.random(n) - 0.5) * joint_var), 1.0).astype(F)
        rad = np.clip(radius + (r.random(n) - 0.5) * 2 * radius_var, 0.2, None).astype(F)
        rad = np.minimum(rad, np.minimum(hx, hy) * 0.9).astype(F)
        ang = ((r.random(n) - 0.5) * 2 * rot).astype(F)
        px = ((X - cx[sid] + W / 2) % W) - W / 2
        py = ((Y - cy[sid] + H / 2) % H) - H / 2
        if rot:
            ca, sa = np.cos(ang)[sid], np.sin(ang)[sid]
            px, py = px * ca + py * sa, -px * sa + py * ca
        qx = np.abs(px) - hx[sid] + rad[sid]
        qy = np.abs(py) - hy[sid] + rad[sid]
        d = (np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2)
             + np.minimum(np.maximum(qx, qy), 0) - rad[sid])
        return dict(id=sid, d=d.astype(F), px=px.astype(F), py=py.astype(F),
                    hx=hx[sid], hy=hy[sid], n=n)


def split_run(r, total, lo, hi, step):
    """Random widths (multiples of ``step``, each in [lo, hi]) summing to total."""
    for _ in range(10000):
        out = []
        left = total
        while left > 0:
            wd = step * r.integers(round(lo / step), round(hi / step) + 1)
            if left - wd < lo and left - wd != 0:
                if lo <= left <= hi:
                    wd = left
                else:
                    break
            out.append(wd)
            left -= wd
        if left == 0:
            return out
    raise RuntimeError("could not split run")


# =============================================================================
# Height -> normal / AO, and file output
# =============================================================================

def _shift(a, dy, dx, wrap_y):
    if dx:
        a = np.roll(a, dx, 1)
    if dy:
        if wrap_y:
            a = np.roll(a, dy, 0)
        else:
            a = np.concatenate([a[:1], a[:-1]], 0) if dy > 0 else np.concatenate([a[1:], a[-1:]], 0)
    return a


def normal_from_height(h_cm, px_cm, strength=1.0, wrap_y=True):
    """OpenGL-convention tangent normal (R right, G up the image)."""
    dhdx = (_shift(h_cm, 0, -1, wrap_y) - _shift(h_cm, 0, 1, wrap_y)) / (2 * px_cm)
    dhdy = (_shift(h_cm, -1, 0, wrap_y) - _shift(h_cm, 1, 0, wrap_y)) / (2 * px_cm)   # image-down
    nx = -dhdx * strength
    ny = dhdy * strength
    nz = np.ones_like(nx)
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + 1.0)
    return np.stack([nx * inv, ny * inv, nz * inv], -1).astype(F)


def ao_from_height(h_cm, px_cm, wrap_y=True, gain=1.0):
    """Cheap cavity occlusion: how far a texel sits below its surroundings."""
    occ = np.zeros_like(h_cm)
    for radius_cm, k in ((0.8, 0.55), (2.5, 0.45), (7.0, 0.3)):
        s = radius_cm / px_cm
        occ += k * np.clip(blur(h_cm, s, wrap_y) - h_cm, 0, None) / (0.35 + radius_cm * 0.25)
    return sat(1.0 - gain * occ).astype(F)


def to8(a):
    return np.clip(np.rint(a * 255.0), 0, 255).astype(np.uint8)


def quant(a, levels):
    """Quantise a 0..1 map to ``levels`` steps (smaller PNGs, no visible loss)."""
    return np.rint(sat(a) * (levels - 1)) / (levels - 1)


INFO = {}
SOFTEN_HEIGHT = 0.8     # px, gaussian sigma
SOFTEN_MASKS = 1.1
MASK_LEVELS = 40


def finish(name, albedo, h_cm, rough, metal=None, px_cm=0.5, size_cm=None, wrap_y=True,
           emis=None, ao=None, ao_gain=1.0, nstrength=1.0, albedo_ext="jpg", alpha=None,
           preview=None, tile_y=True):
    """Derive normal + AO from the height field and write the three maps."""
    os.makedirs(OUT, exist_ok=True)
    h_cm = np.asarray(h_cm, F)
    shape = h_cm.shape
    if ao is None:
        ao = ao_from_height(h_cm, px_cm, wrap_y, ao_gain)
    # Single-texel grit is invisible in the shaded result but makes the PNGs
    # incompressible, so take it off before deriving the stored maps.
    h_cm = blur(h_cm, SOFTEN_HEIGHT, wrap_y)
    ao = blur(ao, SOFTEN_MASKS, wrap_y)
    rough = blur(rough, SOFTEN_MASKS, wrap_y)
    nrm = normal_from_height(h_cm, px_cm, nstrength, wrap_y)
    lo, hi = float(h_cm.min()), float(h_cm.max())
    hgt = (h_cm - lo) / max(hi - lo, 1e-6)
    metal = np.zeros(shape, F) if metal is None else metal
    emis = np.zeros(shape, F) if emis is None else emis

    alb8 = to8(sat(albedo))
    n8 = np.dstack([to8(nrm * 0.5 + 0.5), to8(hgt)])
    m8 = np.dstack([to8(quant(ao, MASK_LEVELS)), to8(quant(rough, MASK_LEVELS)), to8(metal),
                    to8(1.0 - sat(emis))])

    if albedo_ext == "jpg":
        Image.fromarray(alb8).save(os.path.join(OUT, name + ".jpg"), quality=92,
                                          subsampling=0, optimize=True)
    else:
        a8 = np.full(shape, 255, np.uint8) if alpha is None else to8(alpha)
        Image.fromarray(np.dstack([alb8, a8])).save(
            os.path.join(OUT, name + ".png"), optimize=True)
    Image.fromarray(n8).save(os.path.join(OUT, name + "_n.png"), optimize=True)
    Image.fromarray(m8).save(os.path.join(OUT, name + "_m.png"), optimize=True)

    INFO[name] = dict(
        pixels=[shape[1], shape[0]],
        size_cm=size_cm or [round(shape[1] * px_cm, 3), round(shape[0] * px_cm, 3)],
        height_range_cm=round(hi - lo, 3),
        tiles=("xy" if tile_y and wrap_y else ("x" if wrap_y is False else "none")),
        albedo=name + "." + albedo_ext,
    )
    if preview:
        write_preview(preview, name, alb8, n8, m8, tile_y=wrap_y)


# =============================================================================
# Preview: tiled albedo + a quick relit render, for eyeballing the result
# =============================================================================

def _lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _srgb(c):
    c = np.clip(c, 0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def relight(alb8, n8, m8, light=(-0.62, 0.55, 0.36), view=(0.25, -0.6, 0.76)):
    alb = _lin(alb8[..., :3].astype(F) / 255)
    n = n8[..., :3].astype(F) / 255 * 2 - 1
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    ao = m8[..., 0].astype(F) / 255
    rough = np.clip(m8[..., 1].astype(F) / 255, 0.04, 1)
    metal = m8[..., 2].astype(F) / 255
    emis = 1 - m8[..., 3].astype(F) / 255
    L = np.array(light, F)
    L /= np.linalg.norm(L)
    V = np.array(view, F)
    V /= np.linalg.norm(V)
    Hv = (L + V) / np.linalg.norm(L + V)
    ndl = np.clip(n @ L, 0, 1)
    ndv = np.clip(n @ V, 1e-3, 1)
    ndh = np.clip(n @ Hv, 0, 1)
    a2 = (rough * rough) ** 2
    D = a2 / (math.pi * ((ndh * ndh) * (a2 - 1) + 1) ** 2)
    f0 = 0.04 * (1 - metal[..., None]) + alb * metal[..., None]
    fres = f0 + (1 - f0) * (1 - float(Hv @ V)) ** 5
    k = (rough + 1) ** 2 / 8
    G = (ndl / (ndl * (1 - k) + k)) * (ndv / (ndv * (1 - k) + k))
    spec = fres * (D * G / (4 * ndv * np.maximum(ndl, 1e-3)))[..., None]
    sun = np.array([3.2, 3.0, 2.7], F)
    sky = np.array([0.35, 0.45, 0.62], F)
    diff = alb * (1 - metal[..., None])
    col = (diff / math.pi + spec) * sun * ndl[..., None]
    col += diff * sky * (0.55 * ao[..., None]) * (0.6 + 0.4 * n[..., 2:3])
    fenv = f0 + (1 - f0) * (1 - ndv[..., None]) ** 5
    col += fenv * sky * 1.6 * ((1 - rough) ** 2 * ao)[..., None]
    col += alb * emis[..., None] * 2.5
    col = col / (1 + col * 0.35) * 1.25
    return to8(_srgb(col))


def write_preview(folder, name, alb8, n8, m8, tile_y=True):
    """Contact sheets: tiled albedo + relit, a 1:1 detail strip and the maps."""
    os.makedirs(folder, exist_ok=True)
    lit = relight(alb8, n8, m8)
    ty = 2 if tile_y else 1
    a = Image.fromarray(np.tile(alb8[..., :3], (ty, 2, 1)))
    b = Image.fromarray(np.tile(lit, (ty, 2, 1)))
    w, h = a.size
    if tile_y:                                   # side by side
        tw = 800
        th = int(h * tw / w)
        sheet = Image.new("RGB", (tw * 2 + 8, th), (255, 0, 255))
        sheet.paste(a.resize((tw, th), Image.LANCZOS), (0, 0))
        sheet.paste(b.resize((tw, th), Image.LANCZOS), (tw + 8, 0))
    else:                                        # walls: stacked, wider
        tw = 1536
        th = int(h * tw / w)
        sheet = Image.new("RGB", (tw, th * 2 + 8), (255, 0, 255))
        sheet.paste(a.resize((tw, th), Image.LANCZOS), (0, 0))
        sheet.paste(b.resize((tw, th), Image.LANCZOS), (0, th + 8))
    sheet.save(os.path.join(folder, name + "_tiled.png"))

    c = min(512, alb8.shape[0], alb8.shape[1])
    y0 = alb8.shape[0] - c if not tile_y else (alb8.shape[0] - c) // 2
    x0 = (alb8.shape[1] - c) // 3
    sl = (slice(y0, y0 + c), slice(x0, x0 + c))
    strip = np.concatenate([alb8[sl][..., :3], lit[sl], n8[sl][..., :3]], 1)
    Image.fromarray(strip).save(os.path.join(folder, name + "_detail.png"))
    c = min(384, c)
    sl = (slice(y0, y0 + c), slice(x0, x0 + c))

    def grey(ch):
        return np.repeat(ch[sl][..., None], 3, 2)

    maps = np.concatenate([grey(n8[..., 3]), grey(m8[..., 0]), grey(m8[..., 1]),
                           np.dstack([m8[sl][..., 2], 255 - m8[sl][..., 3], m8[sl][..., 2] * 0])], 1)
    Image.fromarray(maps).save(os.path.join(folder, name + "_maps.png"))




# =============================================================================
# PADS  (512 x 512 px, one 112 x 112 cm plate each; not tiled)
# =============================================================================

PAD = 512
PAD_PX = 112.0 / 512.0


def _mask(draw_fn, ss=4):
    """Rasterise an emblem drawn in normalised (-1..1) coords, antialiased."""
    n = PAD * ss
    img = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(img)

    def P(u, v):
        return ((u * 0.5 + 0.5) * n, (v * 0.5 + 0.5) * n)

    draw_fn(d, P, n / 2.0)
    return np.asarray(img.resize((PAD, PAD), Image.LANCZOS), F) / F(255.0)


def _ring(d, P, k, radius, width, fill=255):
    x0, y0 = P(-radius - width / 2, -radius - width / 2)
    x1, y1 = P(radius + width / 2, radius + width / 2)
    d.ellipse([x0, y0, x1, y1], outline=fill, width=max(1, int(round(width * k))))


def _disc(d, P, k, cu, cv, radius, fill=255):
    x0, y0 = P(cu - radius, cv - radius)
    x1, y1 = P(cu + radius, cv + radius)
    d.ellipse([x0, y0, x1, y1], fill=fill)


def _stroke(d, P, k, pts, width, fill=255):
    q = [P(u, v) for u, v in pts]
    d.line(q, fill=fill, width=max(1, int(round(width * k))), joint="curve")
    for u, v in (pts[0], pts[-1]):
        _disc(d, P, k, u, v, width / 2, fill)


def _emblem_spring(d, P, k):
    for radius in (0.50, 0.355, 0.21):
        _ring(d, P, k, radius, 0.058)
    _disc(d, P, k, 0, 0, 0.085)


def _emblem_boost(d, P, k):
    _ring(d, P, k, 0.50, 0.034)
    for v0 in (-0.20, 0.07):
        _stroke(d, P, k, [(-0.29, v0 + 0.25), (0.0, v0 - 0.04), (0.29, v0 + 0.25)], 0.095)


def _emblem_barrier(d, P, k):
    _ring(d, P, k, 0.50, 0.05)
    _ring(d, P, k, 0.375, 0.03)
    # a little brick wall inside the rings
    course, gap, brick = 0.098, 0.026, 0.20
    for row in range(3):
        v0 = -0.16 + row * (course + gap)
        off = (row % 2) * (brick + gap) / 2
        for c in range(-2, 3):
            u0 = -0.5 * brick + c * (brick + gap) + off
            a, b = max(u0, -0.255), min(u0 + brick, 0.255)
            if b - a > 0.03:
                x0, y0 = P(a, v0)
                x1, y1 = P(b, v0 + course)
                d.rounded_rectangle([x0, y0, x1, y1], radius=0.012 * k, fill=255)


def _pad(name, colour, emblem_fn, seed, preview=None):
    shape = (PAD, PAD)
    px = PAD_PX
    X, Y = grid(shape)
    u = (X - PAD / 2) / (PAD / 2)
    v = (Y - PAD / 2) / (PAD / 2)
    rad = np.sqrt(u * u + v * v)
    th = np.arctan2(v, u)
    cm = PAD / 2 * px                                      # cm per normalised unit (56)

    def rrect(half, corner):
        qx = np.abs(u) - half + corner
        qy = np.abs(v) - half + corner
        return np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2) + np.minimum(np.maximum(qx, qy), 0) - corner

    n_big = noise(shape, seed + 1, 200)
    n_med = noise(shape, seed + 2, 40)
    n_fine = noise(shape, seed + 3, 7, beta=1.3)
    n_grit = noise(shape, seed + 4, 2.0, beta=0.6)
    brushed = noise(shape, seed + 5, 3, beta=0.9, sx=26, sy=0.55)

    d_out = rrect(0.94, 0.11)                              # frame outer edge
    d_in = rrect(0.80, 0.075)                              # frame inner edge
    frame = smooth(0.004, -0.004, d_out) * smooth(-0.004, 0.004, d_in)
    deck = smooth(0.004, -0.004, d_in)
    border = smooth(-0.004, 0.004, d_out)

    emblem = _mask(emblem_fn)
    line = smooth(0.012, 0.0, np.abs(d_in + 0.045) - 0.011)        # glowing trim strip inside the frame
    lens = np.maximum(emblem, line)
    hazard = smooth(0.006, -0.006, np.abs(rad - 0.655) - 0.055)
    stripe = smooth(-0.25, 0.25, np.sin(th * 22.0 + rad * 34.0))

    # anti-slip studs on the deck, kept clear of the ring and the emblem
    pitch = 0.064
    gu = (u / pitch + 0.5 * (np.floor(v / (pitch * 0.866)) % 2))
    gv = v / (pitch * 0.866)
    du = (gu - np.floor(gu) - 0.5) * pitch
    dv = (gv - np.floor(gv) - 0.5) * pitch * 0.866
    stud_d = np.sqrt(du * du + dv * dv)
    clear = deck * (1 - smooth(0.02, 0.08, blur(np.maximum(lens, hazard), 5.0))) * smooth(-0.03, -0.06, d_in)
    stud = smooth(0.017, 0.011, stud_d) * (clear > 0.98)

    # bolts along the frame
    bolts = [(a * 0.87, b * 0.87) for a in (-1, 1) for b in (-1, 1)]
    bolts += [(0.0, -0.87), (0.0, 0.87), (-0.87, 0.0), (0.87, 0.0)]
    bd = np.full(shape, 9.0, F)
    for bu, bv in bolts:
        bd = np.minimum(bd, np.sqrt((u - bu) ** 2 + (v - bv) ** 2))
    bolt = smooth(0.036, 0.030, bd)

    # --- height (cm) --------------------------------------------------------------
    bevel = 0.035
    hf = 0.55 * np.minimum(smooth(0.0, -bevel, d_out), smooth(0.0, bevel, d_in))
    h = hf + deck * 0.12
    h += stud * 0.09
    h += hazard * 0.07 * deck
    h -= smooth(0.25, 0.75, lens) * 0.16                       # light channels sit below the deck
    h += bolt * (0.16 * smooth(0.036, 0.012, bd) + 0.05) - smooth(0.044, 0.036, bd) * (1 - bolt) * 0.05
    h += brushed * 0.0025 * (1 - lens) + n_big * 0.01 + n_grit * 0.002

    # --- wear -----------------------------------------------------------------------
    edge = np.abs(np.gradient(hf, axis=0)) + np.abs(np.gradient(hf, axis=1))
    edge = sat(blur(edge, 1.5) * 9.0)
    wearn = noise(shape, seed + 6, 30, beta=1.4) + 0.5 * noise(shape, seed + 7, 6, beta=1.1)
    paint_chip = smooth(0.7, 1.0, wearn + 0.5 * noise(shape, seed + 8, 3, beta=0.9))
    scuff = smooth(0.4, 1.6, noise(shape, seed + 9, 60) + 0.3 * n_fine)
    low = sat(blur(h, 5.0) - h)                                    # recesses where dirt collects
    grime = sat(low * 9.0 + smooth(0.6, 1.8, noise(shape, seed + 10, 50)) * 0.5) * (1 - lens)
    grime = sat(grime * (0.6 + 0.4 * smooth(-1, 1, n_fine)))

    # --- albedo ---------------------------------------------------------------------
    steel_dark = tint(np.broadcast_to(rgb(82, 86, 93), shape + (3,)), 1 + brushed * 0.07 + n_med * 0.04 + n_big * 0.04)
    steel_frame = tint(np.broadcast_to(rgb(116, 120, 126), shape + (3,)), 1 + brushed * 0.08 + n_med * 0.04)
    alb = mixc(steel_dark, steel_frame, frame)
    alb = mixc(alb, rgb(170, 172, 175), np.maximum(edge * 0.7, stud * 0.45) * (1 - lens))
    alb = mixc(alb, rgb(138, 141, 146), bolt * 0.8)
    paint = lerp(rgb(26, 27, 30), colour * 0.82, stripe[..., None])
    paint = tint(paint, 1 + n_med * 0.05 + n_fine * 0.05)
    painted = hazard * deck * (1 - paint_chip * 0.9)
    alb = mixc(alb, paint, painted)
    alb = mixc(alb, rgb(44, 40, 36), grime * 0.75)
    glow = sat(blur(lens, 7.0) * 1.5) * (1 - border)
    alb = mixc(alb, colour * 0.75, glow * 0.45 * (1 - lens))
    core = smooth(0.3, 0.9, lens)
    lens_col = colour * (0.94 + 0.06 * sat(blur(lens, 2.0) * 1.2))[..., None]
    alb = mixc(alb, lens_col, core)

    # --- maps -------------------------------------------------------------------------
    metal = sat(1 - np.maximum(painted, core) - grime * 0.9)
    metal = smooth(0.35, 0.65, metal)
    rough = lerp(0.47, 0.38, frame) + brushed * 0.05 + n_med * 0.03 + scuff * 0.06 - edge * 0.08
    rough = lerp(rough, 0.62 + n_fine * 0.03, painted)
    rough = lerp(rough, 0.85, grime * 0.8)
    rough = lerp(rough, 0.2, core)
    emis = np.maximum(core, glow * 0.4) * (1 - 0.35 * line * (1 - emblem))   # the trim strip glows dimmer
    ao = ao_from_height(h, px, gain=1.4)
    ao = lerp(ao, 1.0, core)
    finish(name, alb, h, rough, metal=metal, px_cm=px, emis=emis, ao=ao, albedo_ext="png",
           preview=preview, tile_y=False, wrap_y=True)


def pad_spring(preview=None):
    _pad("pad_spring", rgb(0x8C, 0xF0, 0x3C), _emblem_spring, 800, preview)


def pad_boost(preview=None):
    _pad("pad_boost", rgb(0xF5, 0xA6, 0x23), _emblem_boost, 820, preview)


def pad_barrier(preview=None):
    _pad("pad_barrier", rgb(0xE0, 0x7A, 0x30), _emblem_barrier, 840, preview)


# =============================================================================
# Driver
# =============================================================================

MATERIALS = [pad_spring, pad_boost, pad_barrier]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", help="generate just these materials")
    ap.add_argument("--preview", metavar="DIR", help="also write tiled/relit contact sheets here")
    args = ap.parse_args(argv)
    t_all = time.time()
    for fn in MATERIALS:
        if args.only and fn.__name__ not in args.only:
            continue
        t0 = time.time()
        fn(preview=args.preview)
        sizes = []
        for suffix in (".jpg", ".png", "_n.png", "_m.png"):
            p = os.path.join(OUT, fn.__name__ + suffix)
            if os.path.exists(p) and not (suffix == ".png" and not fn.__name__.startswith("pad_")):
                sizes.append(os.path.getsize(p))
        print(f"wrote {fn.__name__:12s} {time.time() - t0:5.1f}s  {sum(sizes) / 1024:7.0f} KB")
    print(f"done in {time.time() - t_all:.1f}s")


if __name__ == "__main__":
    main()
