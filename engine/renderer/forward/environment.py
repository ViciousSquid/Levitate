"""The world's light: sun, sky and what the lit surfaces need from them.

:class:`Environment` is plain data -- where the sun is, what the sky is like,
how the frame is finished -- that a game (or a console command) sets on
``renderer.environment``. While it is off, which is how it starts, nothing in
this module draws or binds anything and the renderer is the one Fio always
had. Switched on, a Lit frame is drawn like this (``render_scene`` calls in):

1. the sun's shadow map: every shadow-casting brush and model, once, from
   the sun, redrawn only when one of them moves (:meth:`_env_sun_shadows`);
2. the frame goes to an HDR target (``postfx.py``);
3. the lit programs shade physically (``surface.py``); their uniforms and
   textures are set here (:meth:`_bind_surface`, :meth:`_bind_material_maps`);
4. the sky is this module's own: an analytic atmosphere under a layer of
   moving clouds (:meth:`_env_draw_sky`), also rendered into a small
   equirectangular environment map the surfaces reflect and take their sky
   light from;
5. ambient occlusion and reflections, then bloom, tone mapping and
   anti-aliasing (``postfx.py``).
"""

import json
import math
import os
import time

import glm
import numpy as np
import OpenGL.GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader

from engine.constants import RENDER_MODE_LIT
from engine.renderer.core.uniform_rows import uniform_rows
from engine.renderer.forward import surface

ENV_MAP_SIZE = (512, 256)

FULLSCREEN_VERT = """#version 330 core
out vec2 vNdc;
out vec2 vUV;
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2)) * 2.0 - 1.0;
    vNdc = p;
    vUV = p * 0.5 + 0.5;
    gl_Position = vec4(p, 1.0, 1.0);
}
"""

SUN_DEPTH_FRAG = """#version 330 core
void main() {}
"""

#: The sky: Preetham's analytic daylight (the formulation three.js made
#: familiar) under a cloud layer lit by the sun. Mode 0 draws the background,
#: with the sun's disc, gamma-encoded like every colour in the HDR target;
#: mode 1 draws the equirectangular environment map, linear and without the
#: disc (the surfaces compute the sun's own highlight).
SKY_FRAG = """#version 330 core
precision highp float;
layout(location = 0) out vec4 FragColor;
in vec2 vNdc;
in vec2 vUV;
uniform mat4 uInvProjection;
uniform mat4 uInvView;
uniform int uMode;
uniform vec3 uSunDir;
uniform vec3 uSunColor;
uniform vec4 uSkyParams;        // turbidity, rayleigh, mie coefficient, mie g
uniform vec4 uSkyParams2;       // sky gain, sun disc gain, cloud brightness, unused
uniform vec3 uGroundColor;
uniform highp vec3 uCamPos;
""" + surface.ENV_GLSL + surface.CLOUD_GLSL + """
const float E_CUT = 1.6110731556870734;
const vec3 TOTAL_RAYLEIGH = vec3(5.804542996261093E-6, 1.3562911419845635E-5, 3.0265902468824876E-5);
const vec3 MIE_CONST = vec3(1.8399918514433978E14, 2.7798023919660528E14, 4.0790479543861094E14);

vec3 fioAtmosphere(vec3 dir) {
    float sunE = 1000.0 * max(0.0, 1.0 - exp(-((E_CUT - acos(clamp(uSunDir.y, -1.0, 1.0))) / 1.5)));
    float sunfade = 1.0 - clamp(1.0 - exp(uSunDir.y), 0.0, 1.0);
    vec3 betaR = TOTAL_RAYLEIGH * (uSkyParams.y - (1.0 - sunfade));
    vec3 betaM = 0.434 * (0.2 * uSkyParams.x) * 10E-18 * MIE_CONST * uSkyParams.z;
    float zenith = acos(max(0.0, dir.y));
    float inv = 1.0 / (cos(zenith) + 0.15 * pow(93.885 - degrees(zenith), -1.253));
    vec3 fex = exp(-(betaR * 8.4E3 * inv + betaM * 1.25E3 * inv));
    float cosTheta = dot(dir, uSunDir);
    float half_ = cosTheta * 0.5 + 0.5;
    vec3 betaRTheta = betaR * (3.0 / (16.0 * FIO_PI)) * (1.0 + half_ * half_);
    float g = uSkyParams.w;
    vec3 betaMTheta = betaM * (1.0 / (4.0 * FIO_PI))
                    * ((1.0 - g * g) / pow(1.0 - 2.0 * g * cosTheta + g * g, 1.5));
    vec3 scatter = sunE * ((betaRTheta + betaMTheta) / (betaR + betaM));
    vec3 lin = pow(scatter * (1.0 - fex), vec3(1.5));
    lin *= mix(vec3(1.0), pow(scatter * fex, vec3(0.5)),
               clamp(pow(1.0 - uSunDir.y, 5.0), 0.0, 1.0));
    vec3 colour = (lin + vec3(0.1) * fex) * 0.04 + vec3(0.0, 0.0003, 0.00075);
    return pow(colour, vec3(1.0 / (1.2 + 1.2 * sunfade)));
}

void main() {
    vec3 dir;
    if (uMode == 1) {
        float phi = (vUV.x - 0.5) * 2.0 * FIO_PI;
        float elev = (0.5 - vUV.y) * FIO_PI;
        dir = vec3(cos(elev) * sin(phi), sin(elev), -cos(elev) * cos(phi));
    } else {
        vec4 v = uInvProjection * vec4(vNdc, 1.0, 1.0);
        dir = normalize(mat3(uInvView) * (v.xyz / v.w));
    }
    vec3 sky = fioAtmosphere(normalize(vec3(dir.x, max(dir.y, 0.0), dir.z))) * uSkyParams2.x;
    float cosTheta = dot(dir, uSunDir);
    float cover = 0.0;
    if (dir.y > 0.004 && uCloud.x > 0.0) {
        highp vec2 q = uCamPos.xz + dir.xz * (uCloud.z / (dir.y + 0.07));
        float dens = fioCloudDensity(q);
        if (dens > 0.002) {
            // How much cloud lies between this one and the sun.
            highp vec2 sunward = normalize(uSunDir.xz + vec2(1e-5)) * (0.22 / uCloud.w);
            float behind = fioCloudDensityLow(q + sunward) * 0.6
                         + fioCloudDensityLow(q + sunward * 2.3) * 0.4;
            float lit = exp(-1.9 * behind) * (1.0 - 0.5 * dens);
            float grey = dot(sky, vec3(0.2126, 0.7152, 0.0722));
            vec3 shade = mix(sky, vec3(grey), 0.55) * 0.62 + uSunColor * 0.035;
            vec3 bright = uSunColor * 0.34 + mix(sky, vec3(grey), 0.4) * 0.55;
            vec3 cloud = mix(shade, bright, lit) * uSkyParams2.z;
            // The thin edge of a cloud in front of the sun glows.
            cloud += uSunColor * pow(max(cosTheta, 0.0), 48.0) * (1.0 - dens) * 0.55;
            cover = dens * smoothstep(0.004, 0.16, dir.y);
            sky = mix(sky, cloud, cover);
        }
    }
    if (uMode == 0) {
        float disc = smoothstep(0.99972, 0.99990, cosTheta);
        sky += uSunColor * uSkyParams2.y * disc * (1.0 - cover) * step(0.0, dir.y);
    }
    sky = mix(sky, uGroundColor, smoothstep(0.0, -0.12, dir.y));
    FragColor = vec4(uMode == 0 ? fioEncode(sky) : sky, 1.0);
}
"""


class Environment:
    """What lights the world. Every field is plain data; set them and the
    next frame uses them. ``enabled`` False (the default) is Fio's stock
    renderer."""

    def __init__(self):
        self.enabled = False
        # -- the sun -----------------------------------------------------
        #: Compass bearing of the sun (degrees, 0 = +Z, 90 = +X) and its
        #: height above the horizon.
        self.sun_azimuth = 135.0
        self.sun_elevation = 42.0
        #: Linear RGB of sunlight on a surface facing it; ``None`` takes the
        #: colour the atmosphere gives the sun at this elevation.
        self.sun_color = None
        self.sun_intensity = 3.4
        self.shadow_size = 4096
        self.shadow_strength = 1.0
        #: How far around the view point the shadow map reaches when the
        #: world is larger than this (world units).
        self.shadow_range = 9000.0
        # -- the sky -----------------------------------------------------
        self.turbidity = 3.5
        self.rayleigh = 1.4
        self.mie = 0.005
        self.mie_g = 0.8
        self.sky_intensity = 1.0
        self.sun_disc = 28.0
        #: Linear albedo of the ground, for the light it bounces back up.
        self.ground_color = (0.20, 0.19, 0.17)
        self.cloud_cover = 0.42
        self.cloud_softness = 0.22
        self.cloud_height = 2600.0
        self.cloud_size = 5200.0
        self.cloud_brightness = 1.0
        self.cloud_shadows = 0.55
        #: Cloud drift in world units per second, (x, z).
        self.wind = (26.0, 11.0)
        self.ambient_intensity = 1.0
        #: Aerial perspective: extinction per world unit, and how fast it
        #: thins with height.
        self.haze = 0.00003
        self.haze_falloff = 0.0008
        # -- surfaces ----------------------------------------------------
        self.roughness = 0.82
        self.metalness = 0.0
        #: Scale of parallax occlusion mapping: multiplies each material's
        #: own relief depth (its ``parallax``, world units). 0 turns it off.
        self.parallax = 1.0
        self.emissive_gain = 5.0
        self.point_light_gain = 3.0
        # -- the finished frame --------------------------------------------
        self.exposure = 1.0
        self.bloom = 0.10
        self.bloom_threshold = 1.0
        self.ambient_occlusion = 1.0
        self.ao_radius = 56.0
        self.reflections = True
        self.fxaa = True
        self.saturation = 1.04
        self.contrast = 1.05
        #: Linear RGB multiplier applied before tone mapping (white balance).
        self.tint = (1.0, 1.0, 1.0)
        self.vignette = 0.22
        self.grain = 0.012
        self.sun_shafts = 0.35

    def sun_direction(self):
        """Unit vector from the world toward the sun."""
        azimuth = math.radians(self.sun_azimuth)
        elevation = math.radians(max(1.0, min(89.5, self.sun_elevation)))
        c = math.cos(elevation)
        return (math.sin(azimuth) * c, math.sin(elevation), math.cos(azimuth) * c)

    def sun_radiance(self):
        """Linear RGB of sunlight on a surface facing the sun."""
        if self.sun_color is not None:
            colour = np.asarray(self.sun_color, dtype=np.float64)
        else:
            # The atmosphere's own extinction along the path to the sun
            # (the sky shader's fex), normalised to keep the brightness
            # sun_intensity asks for.
            zenith = math.radians(90.0 - max(1.0, min(89.5, self.sun_elevation)))
            inv = 1.0 / (math.cos(zenith)
                         + 0.15 * (93.885 - math.degrees(zenith)) ** -1.253)
            beta_r = np.array([5.804542996261093e-6, 1.3562911419845635e-5,
                               3.0265902468824876e-5]) * self.rayleigh
            beta_m = (0.434 * (0.2 * self.turbidity) * 10e-18 * np.array(
                [1.8399918514433978e14, 2.7798023919660528e14,
                 4.0790479543861094e14]) * self.mie)
            colour = np.exp(-(beta_r * 8.4e3 * inv + beta_m * 1.25e3 * inv))
            colour = colour / max(float(colour.max()), 1e-6)
            colour = 0.35 + 0.65 * colour          # the sun never reads as orange paint
        return tuple(float(v) * self.sun_intensity for v in colour)

    def key(self):
        """Every value, for telling when something changed."""
        return tuple(
            tuple(v) if isinstance(v, (list, tuple)) else v
            for _name, v in sorted(vars(self).items()))


class _Program:
    """A linked program and its uniform locations, looked up once."""

    def __init__(self, vertex, fragment):
        self.id = compileProgram(compileShader(vertex, gl.GL_VERTEX_SHADER),
                                 compileShader(fragment, gl.GL_FRAGMENT_SHADER),
                                 validate=False)
        self._locations = {}

    def __getitem__(self, name):
        location = self._locations.get(name)
        if location is None:
            location = self._locations[name] = gl.glGetUniformLocation(self.id, name)
        return location

    def delete(self):
        if self.id:
            gl.glDeleteProgram(self.id)
            self.id = 0


def load_data_texture(path, anisotropy=0.0, alpha_path=None):
    """The image at *path* as a mip-mapped RGBA texture of plain data (a
    normal or material map: no colour space), or 0. With *alpha_path*, that
    image's brightness becomes the alpha channel (a height map beside a
    normal map)."""
    try:
        from PIL import Image
        from engine.animated_texture import open_still_rgba
        image = open_still_rgba(path)
        if alpha_path:
            height = open_still_rgba(alpha_path).convert('L')
            if height.size != image.size:
                height = height.resize(image.size, Image.BILINEAR)
            image.putalpha(height)
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
    except Exception as exc:
        print(f"[Environment] could not load {path}: {exc}")
        return 0
    texture = int(gl.glGenTextures(1))
    gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                       gl.GL_LINEAR_MIPMAP_LINEAR)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
    gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
    gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, image.width, image.height,
                    0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, image.tobytes())
    gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)
    gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
    _set_anisotropy(anisotropy)
    return texture


#: GL_TEXTURE_MAX_ANISOTROPY (EXT / 4.6 core share the value).
_TEXTURE_MAX_ANISOTROPY = 0x84FE
_MAX_TEXTURE_MAX_ANISOTROPY = 0x84FF


def _set_anisotropy(amount):
    """Anisotropic filtering for the bound 2D texture, where there is any."""
    if amount <= 1.0:
        return
    try:
        gl.glTexParameterf(gl.GL_TEXTURE_2D, _TEXTURE_MAX_ANISOTROPY, float(amount))
    except Exception:
        pass
    while gl.glGetError() != gl.GL_NO_ERROR:
        pass


class EnvironmentMixin:
    """ForwardRenderer's sun, sky and physically shaded surfaces."""

    def _init_environment(self):
        #: Set its fields (and ``enabled``) to light the world physically.
        self.environment = Environment()
        #: Whether this renderer's lit programs carry the physical path
        #: (false in low-power mode, which keeps its own shaders).
        self.surface_shading = False
        self._env_active = False
        self._env_phase = 0
        self._env_key = None
        self._env_started = time.perf_counter()
        self._env_time = 0.0
        self._env_frame = 0
        self._env_surface_state = {}
        self._env_material_bound = {}
        #: Programs whose uSurfaceDefault holds a model's own values.
        self._env_surface_default = {}
        self._env_sun_matrix = glm.mat4(1.0)
        self._env_sun_texel = 1.0
        self._env_shadow_tex = 0
        self._env_shadow_fbo = 0
        self._env_shadow_size = 0
        self._env_shadow_sig = None
        self._env_shadow_ready = False
        self._env_programs = {}
        self._env_vao = 0
        self._env_noise_tex = 0
        self._env_map = 0
        self._env_map_fbo = 0
        self._env_map_key = None
        self._env_map_age = 0
        self._env_ambient = ((0.3, 0.4, 0.6), (0.3, 0.3, 0.3), (0.1, 0.1, 0.1))
        self._env_ground = (0.1, 0.1, 0.1)
        self._env_sun_dir = (0.0, 1.0, 0.0)
        self._env_sun_rgb = (1.0, 1.0, 1.0)
        self._env_anisotropy = None
        #: GL diffuse texture -> (normal map, material map, parallax,
        #: emission) or None when the texture has no companion maps.
        self._material_maps = {}
        self._material_names = {}
        #: The maps on the material units now (units are shared by programs).
        self._env_units_material = None
        self._init_postfx()

    # ------------------------------------------------------------------
    # Programs and shared resources
    # ------------------------------------------------------------------
    def _install_surface_shading(self):
        """Have every lit program compiled from here on carry the physical
        path (surface.surface_source). Called before the shaders compile."""
        if self.lowpower_mode:
            return
        plain = self.shader_loader.compile_from_source

        def compile_from_source(vertex_src, fragment_src):
            return plain(vertex_src, surface.surface_source(fragment_src))

        self.shader_loader.compile_from_source = compile_from_source
        self.surface_shading = True

    def _configure_surface_programs(self):
        """Give each surface program's samplers their own texture units."""
        if not self.surface_shading:
            return
        for name in surface.SURFACE_PROGRAMS:
            program = self.shaders.get(name)
            if not program:
                continue
            gl.glUseProgram(program)
            uniforms = self.uniforms[name]
            if uniforms['uSurfaceMode'] == -1:
                continue
            for sampler, unit in surface.SURFACE_SAMPLERS:
                location = uniforms[sampler]
                if location != -1:
                    gl.glUniform1i(location, unit)
        gl.glUseProgram(0)

    def _env_program(self, name, vertex, fragment):
        program = self._env_programs.get(name)
        if program is None:
            program = self._env_programs[name] = _Program(vertex, fragment)
        return program

    def _env_fullscreen(self):
        """Draw one triangle over the whole viewport."""
        if not self._env_vao:
            self._env_vao = int(gl.glGenVertexArrays(1))
        gl.glBindVertexArray(self._env_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl.glBindVertexArray(0)

    def _env_max_anisotropy(self):
        if self._env_anisotropy is None:
            try:
                value = float(gl.glGetFloatv(_MAX_TEXTURE_MAX_ANISOTROPY))
            except Exception:
                value = 0.0
            while gl.glGetError() != gl.GL_NO_ERROR:
                pass
            self._env_anisotropy = max(0.0, min(16.0, value))
        return self._env_anisotropy

    def _env_noise(self):
        """A 256x256 tileable texture of random values, for the clouds, the
        occlusion pass's rotations and the film grain."""
        if not self._env_noise_tex:
            rng = np.random.default_rng(20261123)
            data = rng.integers(0, 256, size=(256, 256, 4), dtype=np.uint8)
            self._env_noise_tex = int(gl.glGenTextures(1))
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._env_noise_tex)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, 256, 256, 0,
                            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data.tobytes())
        return self._env_noise_tex

    # ------------------------------------------------------------------
    # The frame
    # ------------------------------------------------------------------
    def _env_wanted(self, config, current_mode):
        """Whether this view is drawn with the environment."""
        env = self.environment
        return bool(
            env.enabled and self.surface_shading and current_mode == RENDER_MODE_LIT
            and not self._probe_capture_pass and not self._portal_scene_pass
            and config.get('brush_display_mode', 'Textured') == 'Textured'
            and not self._shader_init_failed)

    def _env_begin(self, config, camera_pos):
        """Start an environment frame: bring the sky map and the sun's
        shadow up to date, then send the frame to the HDR target. Returns
        whether the frame is an environment frame."""
        env = self.environment
        self._env_time = time.perf_counter() - self._env_started
        self._env_frame += 1
        key = env.key()
        if key != self._env_key:
            self._env_key = key
            self._env_surface_state.clear()
            self._env_sun_dir = env.sun_direction()
            self._env_sun_rgb = env.sun_radiance()
            self._env_shadow_sig = None
        try:
            self._env_update_map(camera_pos)
            if not self._postfx_begin():
                return False
        except Exception as exc:
            # A driver that cannot do this keeps the stock renderer.
            print(f"[Environment] disabled: {exc}")
            env.enabled = False
            self._env_active = False
            return False
        self._env_active = True
        self._env_phase = 1
        self._env_units_material = None
        return True

    def _env_light(self, config, camera_pos):
        """Bring the sun's shadow map up to date and bind what every lit
        program reads this frame. After the frame's own bookkeeping, before
        the first lit pass."""
        try:
            self._env_sun_shadows(config, camera_pos)
        except Exception as exc:
            print(f"[Environment] sun shadows off: {exc}")
            self.environment.shadow_strength = 0.0
            self._env_shadow_ready = False
        gl.glActiveTexture(gl.GL_TEXTURE0 + surface.SUN_SHADOW_UNIT)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._env_shadow_tex)
        gl.glActiveTexture(gl.GL_TEXTURE0 + surface.ENV_MAP_UNIT)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._env_map)
        gl.glActiveTexture(gl.GL_TEXTURE0 + surface.NOISE_UNIT)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._env_noise())
        gl.glActiveTexture(gl.GL_TEXTURE0)

    def _env_cloud_uniforms(self, program):
        env = self.environment
        size = max(float(env.cloud_size), 1.0)
        gl.glUniform4f(program['uCloud'], env.cloud_cover, max(env.cloud_softness, 0.01),
                       env.cloud_height, 1.0 / size)
        t = self._env_time
        gl.glUniform2f(program['uCloudOffset'],
                       (env.wind[0] * t / size) % 256.0, (env.wind[1] * t / size) % 256.0)

    # ------------------------------------------------------------------
    # Sky
    # ------------------------------------------------------------------
    def _env_sky_uniforms(self, program, mode, camera):
        env = self.environment
        gl.glUniform1i(program['uMode'], mode)
        gl.glUniform3f(program['uSunDir'], *self._env_sun_dir)
        gl.glUniform3f(program['uSunColor'], *self._env_sun_rgb)
        gl.glUniform4f(program['uSkyParams'], env.turbidity, env.rayleigh, env.mie, env.mie_g)
        gl.glUniform4f(program['uSkyParams2'], env.sky_intensity, env.sun_disc,
                       env.cloud_brightness, 0.0)
        gl.glUniform3f(program['uGroundColor'], *self._env_ground)
        gl.glUniform3f(program['uCamPos'], *camera)
        self._env_cloud_uniforms(program)
        gl.glUniform1i(program['uNoise'], surface.NOISE_UNIT)
        gl.glActiveTexture(gl.GL_TEXTURE0 + surface.NOISE_UNIT)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._env_noise())
        gl.glActiveTexture(gl.GL_TEXTURE0)

    def _env_draw_sky(self, projection, view, behind=False):
        """The sky, behind everything drawn so far (*behind*) or over the
        whole frame."""
        program = self._env_program('sky', FULLSCREEN_VERT, SKY_FRAG)
        if behind:
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDepthFunc(gl.GL_LEQUAL)
        else:
            gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDisable(gl.GL_BLEND)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glUseProgram(program.id)
        # Held in locals: value_ptr points into the matrix it is given.
        inverse_projection = glm.inverse(projection)
        inverse_view = glm.inverse(view)
        gl.glUniformMatrix4fv(program['uInvProjection'], 1, gl.GL_FALSE,
                              glm.value_ptr(inverse_projection))
        gl.glUniformMatrix4fv(program['uInvView'], 1, gl.GL_FALSE,
                              glm.value_ptr(inverse_view))
        self._env_sky_uniforms(program, 0, self._frame_camera_pos)
        self._env_fullscreen()
        gl.glUseProgram(0)
        self._current_shader = None
        gl.glDepthMask(gl.GL_TRUE)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)

    def _env_update_map(self, camera_pos):
        """Keep the environment map (the sky, equirectangular, mip-mapped)
        and the sky-light colours taken from it. Redrawn when the
        environment changes, and now and then for the clouds' drift."""
        env = self.environment
        key = (env.sun_azimuth, env.sun_elevation, env.sun_color, env.sun_intensity,
               env.turbidity, env.rayleigh, env.mie, env.mie_g, env.sky_intensity,
               tuple(env.ground_color), env.cloud_cover, env.cloud_softness,
               env.cloud_height, env.cloud_size, env.cloud_brightness,
               env.ambient_intensity)
        changed = key != self._env_map_key
        self._env_map_age += 1
        if not changed and self._env_map_age < 90:
            return
        width, height = ENV_MAP_SIZE
        if not self._env_map:
            self._env_map = int(gl.glGenTextures(1))
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._env_map)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA16F, width, height, 0,
                            gl.GL_RGBA, gl.GL_FLOAT, None)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                               gl.GL_LINEAR_MIPMAP_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            self._env_map_fbo = int(gl.glGenFramebuffers(1))
        camera = self._camera_xyz(camera_pos) if camera_pos is not None else (0.0, 0.0, 0.0)
        previous_fbo = int(gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING))
        previous_viewport = [int(v) for v in gl.glGetIntegerv(gl.GL_VIEWPORT)]
        scissor = bool(gl.glIsEnabled(gl.GL_SCISSOR_TEST))
        gl.glDisable(gl.GL_SCISSOR_TEST)
        program = self._env_program('sky', FULLSCREEN_VERT, SKY_FRAG)
        # First for a changed environment with a black ground, to measure the
        # sky's light on it; then with the ground lit by that sky and sun.
        passes = 2 if changed else 1
        try:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._env_map_fbo)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                      gl.GL_TEXTURE_2D, self._env_map, 0)
            gl.glDrawBuffers(1, [gl.GL_COLOR_ATTACHMENT0])
            gl.glViewport(0, 0, width, height)
            gl.glDisable(gl.GL_DEPTH_TEST)
            gl.glDisable(gl.GL_BLEND)
            gl.glDepthMask(gl.GL_FALSE)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
            gl.glUseProgram(program.id)
            for index in range(passes):
                if changed and index == 0:
                    self._env_ground = (0.0, 0.0, 0.0)
                self._env_sky_uniforms(program, 1, camera)
                self._env_fullscreen()
                gl.glBindTexture(gl.GL_TEXTURE_2D, self._env_map)
                gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
                if changed:
                    self._env_measure_ambient(final=index == passes - 1)
        finally:
            gl.glUseProgram(0)
            self._current_shader = None
            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
            gl.glDepthMask(gl.GL_TRUE)
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, previous_fbo)
            gl.glViewport(*previous_viewport)
            if scissor:
                gl.glEnable(gl.GL_SCISSOR_TEST)
        self._env_map_key = key
        self._env_map_age = 0
        self._env_surface_state.clear()

    def _env_measure_ambient(self, final):
        """Sky light on surfaces facing up, sideways and down, from the
        environment map's 16x8 mip, and the ground's own colour under it."""
        env = self.environment
        level = int(round(math.log2(ENV_MAP_SIZE[0] / 16)))
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._env_map)
        raw = gl.glGetTexImage(gl.GL_TEXTURE_2D, level, gl.GL_RGB, gl.GL_FLOAT)
        texels = np.frombuffer(raw, dtype=np.float32).reshape(8, 16, 3).astype(np.float64)
        v = (np.arange(8) + 0.5) / 8.0
        u = (np.arange(16) + 0.5) / 16.0
        elevation = (0.5 - v)[:, None] * math.pi
        phi = (u - 0.5)[None, :] * 2.0 * math.pi
        direction = np.stack([np.cos(elevation) * np.sin(phi),
                              np.sin(elevation) * np.ones_like(phi),
                              -np.cos(elevation) * np.cos(phi)], axis=-1)
        solid = np.cos(elevation) * np.ones_like(phi)

        def irradiance(normal):
            cosine = np.clip(direction @ np.asarray(normal, dtype=np.float64), 0.0, None)
            weight = cosine * solid
            return (texels * weight[..., None]).sum(axis=(0, 1)) / max(weight.sum(), 1e-9)

        up = irradiance((0.0, 1.0, 0.0))
        if not final:
            sun = np.asarray(self._env_sun_rgb) * max(self._env_sun_dir[1], 0.0)
            ground = np.asarray(env.ground_color, dtype=np.float64) * (up + sun * 0.55)
            self._env_ground = tuple(float(c) for c in ground)
            return
        side = sum(irradiance(n) for n in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))) / 4.0
        down = irradiance((0.0, -1.0, 0.0))
        gain = float(env.ambient_intensity)
        self._env_ambient = tuple(tuple(float(c) * gain for c in colour)
                                  for colour in (up, side, down))

    # ------------------------------------------------------------------
    # The sun's shadow map
    # ------------------------------------------------------------------
    def _env_shadow_target(self, size):
        if self._env_shadow_tex and self._env_shadow_size == size:
            return
        if self._env_shadow_tex:
            gl.glDeleteTextures([self._env_shadow_tex])
        self._env_shadow_tex = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._env_shadow_tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_DEPTH_COMPONENT24, size, size, 0,
                        gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_BORDER)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_BORDER)
        gl.glTexParameterfv(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_BORDER_COLOR,
                            (1.0, 1.0, 1.0, 1.0))
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_COMPARE_MODE,
                           gl.GL_COMPARE_REF_TO_TEXTURE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_COMPARE_FUNC, gl.GL_LEQUAL)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        if not self._env_shadow_fbo:
            self._env_shadow_fbo = int(gl.glGenFramebuffers(1))
        self._env_shadow_size = size
        self._env_shadow_sig = None

    def _env_sun_frame(self, table, casters, camera_pos):
        """The sun's view of the casters: ``(matrix, world units a texel)``.

        An orthographic box around every caster, or around the view point
        when the world is larger than ``shadow_range``; snapped to whole
        texels there so the shadows do not swim as the view moves."""
        env = self.environment
        direction = glm.vec3(*self._env_sun_dir)
        up = glm.vec3(0.0, 1.0, 0.0) if abs(direction.y) < 0.99 else glm.vec3(0.0, 0.0, 1.0)
        centre = table.center[casters]
        half = table.half[casters]
        low = (centre - half).min(axis=0).astype(np.float64)
        high = (centre + half).max(axis=0).astype(np.float64)
        reach = float(env.shadow_range)
        size = int(self._env_shadow_size)
        follow = max(high[0] - low[0], high[2] - low[2]) > 2.0 * reach
        if follow and camera_pos is not None:
            cx, _cy, cz = self._camera_xyz(camera_pos)
            low[0], high[0] = max(low[0], cx - reach), min(high[0], cx + reach)
            low[2], high[2] = max(low[2], cz - reach), min(high[2], cz + reach)
        middle = glm.vec3(*((low + high) * 0.5))
        look = glm.lookAt(middle + direction * 1000.0, middle, up)
        corners = np.array([[x, y, z, 1.0] for x in (low[0], high[0])
                            for y in (low[1], high[1]) for z in (low[2], high[2])])
        matrix = np.array(look.to_list(), dtype=np.float64).T      # row-major
        in_light = corners @ matrix.T
        lo = in_light[:, :3].min(axis=0)
        hi = in_light[:, :3].max(axis=0)
        span = max(hi[0] - lo[0], hi[1] - lo[1]) * 1.02
        texel = span / size
        mid_x = (lo[0] + hi[0]) * 0.5
        mid_y = (lo[1] + hi[1]) * 0.5
        if follow:
            mid_x = math.floor(mid_x / texel) * texel
            mid_y = math.floor(mid_y / texel) * texel
        projection = glm.ortho(mid_x - span * 0.5, mid_x + span * 0.5,
                               mid_y - span * 0.5, mid_y + span * 0.5,
                               -hi[2] - 16.0, -lo[2] + 16.0)
        key = (round(mid_x, 2), round(mid_y, 2), round(span, 2),
               round(float(lo[2]), 1), round(float(hi[2]), 1))
        return projection * look, texel, key

    def _env_sun_shadows(self, config, camera_pos):
        """Draw the sun's shadow map when a caster, the sun or the map's
        size has changed since it was last drawn."""
        env = self.environment
        self._env_shadow_ready = False
        if env.shadow_strength <= 0.0 or not self.shadows_enabled:
            return
        table = config.get('render_table')
        all_slots = config.get('all_brush_slots')
        entity_table = config.get('entity_table')
        if table is None or all_slots is None or entity_table is None:
            return
        size = int(max(512, min(8192, env.shadow_size)))
        self._env_shadow_target(size)
        casters = self._kept_shadow_casters(table, all_slots)
        if not len(casters):
            return
        in_slots, brush_keys = self._kept_casters_in_reach(
            'sun', table, casters, 0.0, 0.0, 0.0, 1.0e9)
        model_slots = self._dense_shadow_model_slots(
            entity_table, config.get('thing_hidden'))
        in_models, model_keys = self._collect_dense_shadow_models(
            entity_table, model_slots, 0.0, 0.0, 0.0, 1.0e9)
        if not len(in_slots):
            return
        matrix, texel, frame_key = self._env_sun_frame(table, in_slots, camera_pos)
        self._env_sun_matrix = matrix
        self._env_sun_texel = texel
        self._env_shadow_ready = True
        signature = (frame_key, self._env_sun_dir, size, brush_keys, model_keys)
        previous = self._env_shadow_sig
        if (previous is not None and previous[:3] == signature[:3]
                and (previous[3] is brush_keys or previous[3] == brush_keys)
                and previous[4] == model_keys):
            return
        self._env_shadow_sig = signature
        self._env_draw_shadow_map(table, in_slots, entity_table, in_models, matrix, size)

    def _env_depth_programs(self):
        """The depth-only programs: per-object and instanced, built from the
        cube-map depth pass's own vertex shaders."""
        programs = self._env_programs
        if 'sun_depth' not in programs:
            vertex = self._shader_source('depth_cube.vert')
            programs['sun_depth'] = _Program(vertex, SUN_DEPTH_FRAG)
            instanced = self._instanced_vertex_source(vertex, preamble='')
            programs['sun_depth_instanced'] = (
                _Program(instanced, SUN_DEPTH_FRAG)
                if instanced and self._cube_vbo is not None else None)
        return programs['sun_depth'], programs['sun_depth_instanced']

    def _env_draw_shadow_map(self, table, in_brushes, entity_table, in_models, matrix, size):
        plain, instanced = self._env_depth_programs()
        previous_fbo = int(gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING))
        previous_viewport = [int(v) for v in gl.glGetIntegerv(gl.GL_VIEWPORT)]
        scissor = bool(gl.glIsEnabled(gl.GL_SCISSOR_TEST))
        cull = bool(gl.glIsEnabled(gl.GL_CULL_FACE))
        matrix_ptr = glm.value_ptr(matrix)
        try:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._env_shadow_fbo)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
                                      gl.GL_TEXTURE_2D, self._env_shadow_tex, 0)
            gl.glDrawBuffer(gl.GL_NONE)
            gl.glReadBuffer(gl.GL_NONE)
            gl.glViewport(0, 0, size, size)
            gl.glDisable(gl.GL_SCISSOR_TEST)
            gl.glDisable(gl.GL_BLEND)
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDepthMask(gl.GL_TRUE)
            gl.glDepthFunc(gl.GL_LESS)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
            gl.glClear(gl.GL_DEPTH_BUFFER_BIT)
            # Brushes are closed solids: drawing the faces turned away from
            # the sun puts the stored depth behind every lit face, which then
            # cannot shadow itself. Cube brushes are wound clockwise-outward,
            # convex meshes counter-clockwise (see PortalsMixin).
            gl.glEnable(gl.GL_CULL_FACE)
            gl.glCullFace(gl.GL_BACK)
            gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
            gl.glPolygonOffset(1.0, 1.0)
            cube_slots, geo_slots, stream = self._prepare_shadow_instances(
                table, in_brushes, instanced is not None, key=('shadow', 'sun'))
            cube_vao = self.vaos['cube']
            if len(cube_slots) and stream is not None:
                gl.glUseProgram(instanced.id)
                gl.glUniformMatrix4fv(instanced['lightSpaceMatrix'], 1, gl.GL_FALSE, matrix_ptr)
                gl.glBindVertexArray(stream.vao)
                gl.glBindBuffer(gl.GL_ARRAY_BUFFER, stream.vbo)
                self._point_brush_instances_at(0)
                gl.glDrawArraysInstanced(gl.GL_TRIANGLES, 0, 36, len(cube_slots))
            gl.glUseProgram(plain.id)
            gl.glUniformMatrix4fv(plain['lightSpaceMatrix'], 1, gl.GL_FALSE, matrix_ptr)
            model_loc = plain['model']
            if len(cube_slots) and stream is None:
                cube_models, _ = self._frame_transforms(table, cube_slots)
                upload = uniform_rows('mat4', cube_models)
                gl.glBindVertexArray(cube_vao)
                for index in range(len(cube_slots)):
                    upload(model_loc, index)
                    gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            if len(geo_slots):
                gl.glCullFace(gl.GL_FRONT)
                meshes = self._prepare_geo_meshes(table, geo_slots)
                geo_models, _ = self._frame_transforms(table, geo_slots)
                upload = uniform_rows('mat4', geo_models)
                for index, slot in enumerate(geo_slots):
                    mesh = meshes.get(int(table.geometry_id[int(slot)]))
                    if mesh is None:
                        continue
                    upload(model_loc, index)
                    gl.glBindVertexArray(mesh.vao)
                    gl.glDrawArrays(gl.GL_TRIANGLES, 0, mesh.count)
            # Models need not be closed: both sides, pushed back a little more.
            gl.glDisable(gl.GL_CULL_FACE)
            gl.glPolygonOffset(2.5, 4.0)
            recipes = entity_table.model_recipes()
            resolved = []
            for slot in in_models:
                slot = int(slot)
                recipe = int(entity_table.model_recipe_id[slot])
                if 0 <= recipe < len(recipes):
                    model = self.load_model(recipes[recipe][0])
                    if model and model.is_loaded:
                        resolved.append((slot, model))
            if resolved:
                slots = np.array([s for s, _ in resolved], dtype=np.intp)
                bases = entity_table.model_base_matrix[slots]
                bases[:, 12:15] = entity_table.pos[slots]
                upload = uniform_rows('mat4', bases)
                for index, (_slot, model) in enumerate(resolved):
                    upload(model_loc, index)
                    gl.glBindVertexArray(model.vao)
                    if getattr(model, 'ebo', None) is not None and getattr(model, 'index_count', 0):
                        gl.glDrawElements(gl.GL_TRIANGLES, model.index_count,
                                          gl.GL_UNSIGNED_INT, None)
                    else:
                        gl.glDrawArrays(gl.GL_TRIANGLES, 0, model.vertex_count)
        finally:
            gl.glBindVertexArray(0)
            gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
            gl.glCullFace(gl.GL_BACK)
            if cull:
                gl.glEnable(gl.GL_CULL_FACE)
            else:
                gl.glDisable(gl.GL_CULL_FACE)
            gl.glUseProgram(0)
            self._current_shader = None
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, previous_fbo)
            gl.glViewport(*previous_viewport)
            if scissor:
                gl.glEnable(gl.GL_SCISSOR_TEST)

    # ------------------------------------------------------------------
    # Surface programs
    # ------------------------------------------------------------------
    def _bind_surface(self, shader_name):
        """Give the bound lit program this frame's surface state. Values are
        program state, so each is sent only when it differs from what the
        program last had."""
        if not self.surface_shading:
            return
        uniforms = self.uniforms.get(shader_name)
        if uniforms is None:
            return
        mode_loc = uniforms['uSurfaceMode']
        if mode_loc == -1:
            return
        state = self._env_surface_state.get(shader_name)
        if not self._env_active:
            if state is not None and state[0] != 0:
                gl.glUniform1i(mode_loc, 0)
                self._env_surface_state[shader_name] = (0, None, None)
            return
        env = self.environment
        mode = self._env_phase
        if state is None or state[0] != mode:
            gl.glUniform1i(mode_loc, mode)
        frame = (self._env_map_key, self._env_shadow_ready)
        if state is None or state[1] != frame:
            ambient = self._env_ambient
            gl.glUniform3f(uniforms['uSunDir'], *self._env_sun_dir)
            gl.glUniform3f(uniforms['uSunColor'], *self._env_sun_rgb)
            gl.glUniform3f(uniforms['uAmbientSky'], *ambient[0])
            gl.glUniform3f(uniforms['uAmbientHorizon'], *ambient[1])
            gl.glUniform3f(uniforms['uAmbientGround'], *ambient[2])
            top_mip = math.log2(ENV_MAP_SIZE[0]) - 2.0
            gl.glUniform4f(uniforms['uEnvParams'], top_mip,
                           0.0 if self._postfx_reflects() else 1.0,
                           env.emissive_gain, env.point_light_gain)
            gl.glUniform4f(uniforms['uSurfaceDefault'], env.roughness, env.metalness, 0.0, 0.0)
            self._env_surface_default.pop(shader_name, None)
            gl.glUniform4f(uniforms['uAtmosphere'], env.haze, env.haze_falloff,
                           env.cloud_shadows if env.cloud_cover > 0.0 else 0.0, 0.0)
            gl.glUniform4f(uniforms['uMaterial'], 0.0, 0.0, 0.0, 0.0)
            self._env_material_bound[shader_name] = None
        # The shadow matrix follows the view in a large world, and the
        # clouds drift: both every frame.
        size = float(max(self._env_shadow_size, 1))
        shadow = (glm.value_ptr(self._env_sun_matrix), self._env_sun_texel,
                  self._env_shadow_ready)
        if state is None or state[2] != self._env_frame:
            gl.glUniformMatrix4fv(uniforms['uSunMatrix'], 1, gl.GL_FALSE, shadow[0])
            gl.glUniform4f(uniforms['uSunShadowParams'], 1.0 / size, size,
                           self._env_sun_texel * 1.6,
                           env.shadow_strength if self._env_shadow_ready else 0.0)
            cloud_size = max(float(env.cloud_size), 1.0)
            t = self._env_time
            gl.glUniform4f(uniforms['uCloud'], env.cloud_cover,
                           max(env.cloud_softness, 0.01), env.cloud_height, 1.0 / cloud_size)
            gl.glUniform2f(uniforms['uCloudOffset'],
                           (env.wind[0] * t / cloud_size) % 256.0,
                           (env.wind[1] * t / cloud_size) % 256.0)
        self._env_surface_state[shader_name] = (mode, frame, self._env_frame)
        if shader_name in self._env_surface_default:
            # A model's own roughness and metalness, from its last draw.
            gl.glUniform4f(uniforms['uSurfaceDefault'], env.roughness, env.metalness, 0.0, 0.0)
            del self._env_surface_default[shader_name]
        # A program that draws without materials of its own (models, glow
        # brushes) must not keep the last brush's maps.
        if self._env_material_bound.get(shader_name) is not None:
            gl.glUniform4f(uniforms['uMaterial'], 0.0, 0.0, 0.0, 0.0)
            self._env_material_bound[shader_name] = None

    def _model_surface(self, shader_name, surface):
        """A model draw group's own ``(roughness, metalness)``, or None for
        the environment's (no-op off an environment frame)."""
        if not self._env_active:
            return
        current = self._env_surface_default.get(shader_name)
        if current == surface:
            return
        location = self.uniforms[shader_name]['uSurfaceDefault']
        if location == -1:
            return
        env = self.environment
        if surface is None:
            gl.glUniform4f(location, env.roughness, env.metalness, 0.0, 0.0)
            del self._env_surface_default[shader_name]
        else:
            gl.glUniform4f(location, surface[0], surface[1], 0.0, 0.0)
            self._env_surface_default[shader_name] = surface

    # ------------------------------------------------------------------
    # Material maps
    # ------------------------------------------------------------------
    def _material_for(self, texture):
        """A diffuse texture's companion maps: ``(normal, material,
        parallax, emission)`` as GL names and scalars, or None. Looked for
        once per texture, beside its file (png, webp or jpg):

        * ``<name>_n`` -- the normal map (OpenGL convention), with the
          surface's height in its alpha, or in a separate ``<name>_h``;
        * ``<name>_m`` -- ambient occlusion, roughness and metalness in R, G
          and B, and 1 - emission in alpha;
        * ``<name>.mat.json`` -- ``parallax``, the depth of the relief in
          world units (scaled by the environment's ``parallax``), and
          ``emission``, a gain on the map's emission."""
        try:
            return self._material_maps[texture]
        except KeyError:
            pass
        from engine.asset_archives import asset_bytes, asset_exists
        from engine.asset_paths import confined_path
        if len(self._material_names) != len(self.texture_manager):
            self._material_names = {int(v): k for k, v in self.texture_manager.items()}
        found = None
        key = self._material_names.get(int(texture))
        if key and key.startswith('model_tex:'):
            # A model's own texture, cached by its resolved path.
            key = key[len('model_tex:'):].replace(os.sep, '/')
            key = key[len('assets/'):] if key.startswith('assets/') else None
        if key:
            base = os.path.splitext(key)[0]

            def companion(suffix):
                for extension in ('.png', '.webp', '.jpg'):
                    path = confined_path('assets', base + suffix + extension)
                    if path is not None and asset_exists(path):
                        return path
                return None

            normal_path, material_path = companion('_n'), companion('_m')
            if normal_path and material_path:
                anisotropy = self._env_max_anisotropy()
                height_path = companion('_h')
                normal = load_data_texture(normal_path, anisotropy, height_path)
                material = load_data_texture(material_path, anisotropy)
                # Without a height there is nothing for parallax to follow.
                has_height = bool(height_path) or normal_path.lower().endswith(('.png', '.webp'))
                parallax, emission = (1.0 if has_height else 0.0), 1.0
                sidecar = confined_path('assets', base + '.mat.json')
                if sidecar is not None and asset_exists(sidecar):
                    try:
                        values = json.loads(asset_bytes(sidecar).decode('utf-8'))
                        parallax = float(values.get('parallax', parallax))
                        emission = float(values.get('emission', 1.0))
                    except Exception as exc:
                        print(f"[Environment] {sidecar}: {exc}")
                if normal and material:
                    found = (normal, material, parallax, emission)
                    # The diffuse texture was loaded without it.
                    gl.glBindTexture(gl.GL_TEXTURE_2D, int(texture))
                    _set_anisotropy(anisotropy)
        self._material_maps[texture] = found
        return found

    def _bind_material_maps(self, shader_name, texture):
        """After a brush pass binds diffuse *texture* on unit 0: bind its
        companion maps and tell the program (no-op off an environment frame)."""
        if not self._env_active:
            return
        maps = self._material_for(texture)
        if maps is not None and self._env_units_material is not maps:
            gl.glActiveTexture(gl.GL_TEXTURE0 + surface.NORMAL_MAP_UNIT)
            gl.glBindTexture(gl.GL_TEXTURE_2D, maps[0])
            gl.glActiveTexture(gl.GL_TEXTURE0 + surface.MATERIAL_MAP_UNIT)
            gl.glBindTexture(gl.GL_TEXTURE_2D, maps[1])
            gl.glActiveTexture(gl.GL_TEXTURE0)
            self._env_units_material = maps
        if self._env_material_bound.get(shader_name, False) is maps:
            return
        uniforms = self.uniforms.get(shader_name)
        if uniforms is None:
            return
        location = uniforms['uMaterial']
        if location == -1:
            return
        if maps is None:
            gl.glUniform4f(location, 0.0, 0.0, 0.0, 0.0)
        else:
            env = self.environment
            gl.glUniform4f(location, 1.0, env.parallax * maps[2],
                           env.emissive_gain * maps[3], 0.0)
        self._env_material_bound[shader_name] = maps

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------
    def _cleanup_environment(self):
        self._cleanup_postfx()
        textures = [t for t in (self._env_shadow_tex, self._env_noise_tex, self._env_map) if t]
        for maps in self._material_maps.values():
            if maps:
                textures += [maps[0], maps[1]]
        if textures:
            gl.glDeleteTextures(textures)
        framebuffers = [f for f in (self._env_shadow_fbo, self._env_map_fbo) if f]
        if framebuffers:
            gl.glDeleteFramebuffers(len(framebuffers), framebuffers)
        for program in self._env_programs.values():
            if program is not None:
                program.delete()
        if self._env_vao:
            gl.glDeleteVertexArrays(1, [self._env_vao])
        self._env_programs = {}
        self._material_maps = {}
        self._env_shadow_tex = self._env_noise_tex = self._env_map = 0
        self._env_shadow_fbo = self._env_map_fbo = self._env_vao = 0
        self._env_shadow_size = 0
        self._env_shadow_sig = None
        self._env_map_key = None
        self._env_surface_state.clear()
        self._env_active = False
