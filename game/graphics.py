"""How a Levitate! maze is lit and finished.

Fio's renderer has an :class:`~engine.renderer.forward.environment.Environment`
-- a sun with shadows, a sky, physically shaded surfaces and an HDR finish --
that is off until something switches it on. Levitate! switches it on for a
match, with a look per maze theme (:data:`THEMES`), at the quality the player
chose (``[Renderer] graphics`` in settings.ini; :data:`QUALITIES`).

``classic`` leaves the environment off: Fio's stock renderer, for machines
that cannot afford the rest. The mazes carry fill lights for exactly that
case (:data:`FILL_LIGHT`), which a lit match hides.
"""

from __future__ import annotations

#: ``[Renderer] graphics`` values, best first, with their labels.
QUALITIES = {
    "ultra": "Ultra",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "classic": "Classic (no sun, sky or post-processing)",
}
DEFAULT_QUALITY = "high"

#: The property that marks a maze's fill lights (make_mazes.py): on in a
#: ``classic`` match, hidden in a lit one, where the sun and sky do their job.
FILL_LIGHT = "levitate_fill"

#: What each quality turns on. ``shadow_size`` is the sun's shadow map;
#: ``parallax`` scales every material's relief depth (0: plain normal mapping).
_QUALITY = {
    "ultra": dict(shadow_size=8192, parallax=1.0, reflections=True, ambient_occlusion=1.0,
                  bloom=1.0, sun_shafts=1.0, fxaa=True, cloud_shadows=1.0),
    "high": dict(shadow_size=4096, parallax=1.0, reflections=True, ambient_occlusion=1.0,
                 bloom=1.0, sun_shafts=1.0, fxaa=True, cloud_shadows=1.0),
    "medium": dict(shadow_size=2048, parallax=0.0, reflections=True, ambient_occlusion=1.0,
                   bloom=1.0, sun_shafts=0.0, fxaa=True, cloud_shadows=1.0),
    "low": dict(shadow_size=1024, parallax=0.0, reflections=False, ambient_occlusion=0.0,
                bloom=1.0, sun_shafts=0.0, fxaa=True, cloud_shadows=0.0),
}

#: The look of each maze theme: any :class:`Environment` field. Sun bearings
#: are chosen so that walls throw their shadows diagonally across the
#: corridors, leaving every corridor part sun and part shade.
THEMES = {
    # Breakwater: a harbour wall on a bright, blustery afternoon; rain not
    # long gone, so the apron still holds water.
    "slate": dict(
        sun_azimuth=212.0, sun_elevation=40.0, sun_intensity=3.3,
        sun_color=(1.0, 0.93, 0.82),
        turbidity=2.6, rayleigh=1.25, mie=0.004, sky_intensity=0.92,
        cloud_cover=0.50, cloud_softness=0.24, cloud_shadows=0.5, wind=(34.0, 14.0),
        ground_color=(0.11, 0.115, 0.12), haze=0.000045,
        exposure=0.80, saturation=1.02, contrast=1.06, tint=(0.99, 1.0, 1.03),
        bloom=0.09, sun_shafts=0.30),
    # Sandglass: desert ruins toward evening; low golden sun, long shadows,
    # dust in the air.
    "sand": dict(
        sun_azimuth=128.0, sun_elevation=29.0, sun_intensity=3.5,
        sun_color=(1.0, 0.80, 0.56),
        turbidity=6.5, rayleigh=1.9, mie=0.007, mie_g=0.82, sky_intensity=0.95,
        cloud_cover=0.16, cloud_softness=0.30, cloud_shadows=0.3, wind=(12.0, 20.0),
        ground_color=(0.34, 0.27, 0.19), haze=0.00011, haze_falloff=0.0012,
        exposure=0.80, saturation=1.06, contrast=1.05, tint=(1.03, 1.0, 0.96),
        bloom=0.12, sun_shafts=0.48),
    # Mossgarden: an old walled garden on a fresh morning, high sun through
    # broken cloud.
    "moss": dict(
        sun_azimuth=52.0, sun_elevation=50.0, sun_intensity=3.4,
        sun_color=(1.0, 0.96, 0.88),
        turbidity=3.2, rayleigh=1.5, mie=0.005, sky_intensity=0.95,
        cloud_cover=0.60, cloud_softness=0.26, cloud_shadows=0.6, wind=(18.0, -24.0),
        ground_color=(0.10, 0.13, 0.08), haze=0.00006,
        exposure=0.82, saturation=1.08, contrast=1.05, tint=(1.0, 1.01, 0.98),
        bloom=0.09, sun_shafts=0.32),
    # Frostline: high country in deep snow; a low, clear winter sun.
    "frost": dict(
        sun_azimuth=236.0, sun_elevation=31.0, sun_intensity=3.6,
        sun_color=(1.0, 0.90, 0.76),
        turbidity=2.0, rayleigh=1.1, mie=0.003, sky_intensity=0.90,
        cloud_cover=0.30, cloud_softness=0.30, cloud_shadows=0.35, wind=(22.0, 8.0),
        ground_color=(0.62, 0.66, 0.72), haze=0.00007,
        exposure=0.80, saturation=1.0, contrast=1.07, tint=(0.97, 1.0, 1.05),
        bloom=0.13, sun_shafts=0.42),
    # Emberworks: a foundry at night. The "sun" is the moon; the light that
    # matters is the lamps'.
    "ember": dict(
        sun_azimuth=64.0, sun_elevation=38.0, sun_intensity=0.42,
        sun_color=(0.62, 0.74, 1.0), sun_disc=26.0,
        turbidity=2.2, rayleigh=1.0, mie=0.004, sky_intensity=0.06,
        cloud_cover=0.45, cloud_softness=0.30, cloud_shadows=0.3, cloud_brightness=1.6,
        wind=(16.0, 10.0), ground_color=(0.05, 0.05, 0.06), haze=0.00010,
        point_light_gain=4.2, emissive_gain=6.0, roughness=0.6,
        exposure=1.7, saturation=1.10, contrast=1.08, tint=(1.0, 0.99, 1.02),
        bloom=0.22, sun_shafts=0.0, vignette=0.32),
}
DEFAULT_THEME = "slate"


def quality_from(config) -> str:
    """The ``[Renderer] graphics`` setting of a ConfigParser, or the default."""
    try:
        value = config.get("Renderer", "graphics", fallback=DEFAULT_QUALITY)
    except Exception:
        value = DEFAULT_QUALITY
    value = str(value or "").strip().lower()
    return value if value in QUALITIES else DEFAULT_QUALITY


def lit(quality) -> bool:
    """Whether *quality* lights the maze with the environment."""
    return quality != "classic"


def apply(renderer, theme, quality, focus=None) -> bool:
    """Light *renderer*'s world as maze *theme* at *quality*. *focus* is the
    maze's footprint ``(x0, z0, x1, z1)``: where the sun's shadow map spends
    its resolution. Returns whether the environment is now on (False for
    ``classic`` and for a renderer that has none)."""
    environment = getattr(renderer, "environment", None)
    if environment is None:
        return False
    if not lit(quality) or not getattr(renderer, "surface_shading", False):
        environment.enabled = False
        return False
    fresh = type(environment)()
    look = dict(THEMES.get(theme, THEMES[DEFAULT_THEME]))
    level = _QUALITY.get(quality, _QUALITY[DEFAULT_QUALITY])
    for name, value in look.items():
        setattr(fresh, name, value)
    fresh.shadow_size = level["shadow_size"]
    fresh.parallax = fresh.parallax * level["parallax"]
    fresh.reflections = level["reflections"]
    fresh.ambient_occlusion = fresh.ambient_occlusion * level["ambient_occlusion"]
    fresh.bloom = fresh.bloom * level["bloom"]
    fresh.sun_shafts = fresh.sun_shafts * level["sun_shafts"]
    fresh.fxaa = level["fxaa"]
    fresh.cloud_shadows = fresh.cloud_shadows * level["cloud_shadows"]
    fresh.shadow_focus = tuple(float(v) for v in focus) if focus else None
    fresh.enabled = True
    # One assignment per field, so a frame in progress never sees half a look.
    for name, value in vars(fresh).items():
        setattr(environment, name, value)
    return True


def clear(renderer) -> None:
    """Back to Fio's stock renderer."""
    environment = getattr(renderer, "environment", None)
    if environment is not None:
        environment.enabled = False
