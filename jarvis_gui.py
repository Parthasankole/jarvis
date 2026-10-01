import os
import math
import time
import random
from pathlib import Path
import pygame

import jarvis_profile as profile

# Color definitions matching the cinematic Iron Man HUD
BG_BLACK = (0, 0, 0)
CYAN_BRIGHT = (120, 220, 255)
CYAN_GLOW = (80, 175, 235)
CYAN_MUTED = (95, 125, 150)
CYAN_DARK = (40, 65, 85)
WHITE_TEXT = (225, 240, 255)
AMBER_JARVIS = (255, 160, 45)
AMBER_GLOW = (255, 130, 20)

BASE_W = 1672
BASE_H = 941

# Center coordinates aligned with the background artwork's sun
CORE_CX = 836
CORE_CY = 419
SUN_RADIUS = 100


class JarvisHUD:
    """
    High-Fidelity J.A.R.V.I.S. HUD Interface.
    Pixel-perfect match to the reference artwork with full 60 FPS dynamic animations:
      - 3D Monolith Crystal & Solar Corona Star Core (Aligned with background sun)
      - Smooth Organic Fluid Audio Wave tightly hugging the center sun
      - Additive Solar Bloom with zero clipping
      - 3D Orbiting Satellites
      - Real-Time Dual Audio Waveforms
      - Interactive Glowing Mic Button with Sonar Recording Rings
      - Live Chamfered Conversation Panel with Word Wrapping
      - Dynamic LISTEN / THINK / ASSIST Status Indicators
    """

    def __init__(self, width=1366, height=768):
        pygame.init()
        pygame.font.init()

        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode(
            (width, height), pygame.RESIZABLE | pygame.DOUBLEBUF
        )
        pygame.display.set_caption("J.A.R.V.I.S. - Personal Assistant")

        # Load window icon
        try:
            icon_p = Path(__file__).parent / "jarvis.png"
            if icon_p.exists():
                pygame.display.set_icon(pygame.image.load(str(icon_p)))
        except Exception:
            pass

        self.clock = pygame.time.Clock()
        self.running = True

        # High-resolution internal rendering canvas (matches native artwork)
        self.canvas = pygame.Surface((BASE_W, BASE_H))

        # Visual state from backend
        self.state = "IDLE"  # IDLE / LISTENING / THINKING / RESPONDING
        self.history = []    # list of ("You" | "Jarvis", text)
        self.last_user = ""
        self.last_jarvis = ""

        # Fluid wave animation physics (tightly bounded amplitude)
        self.fluid_amp = 2.0
        self.fluid_rot = 0.0

        # Swirling fluid droplets
        self.droplets = []
        for i in range(14):
            self.droplets.append({
                "angle": (i / 14.0) * math.tau,
                "speed": 0.8 + 0.5 * ((i * 5) % 4) / 4.0,
                "radius_offset": -2.0 + 4.0 * ((i * 3) % 3) / 3.0,
                "size": 1.5 if i % 2 == 0 else 2.4,
                "alpha": 140 + (i * 15) % 80
            })

        # Interactive controls
        self._manual_trigger = False
        self._mic_hover = False
        self._click_time = 0.0
        self._interrupt_request = False   # set by Escape/Space/click-while-responding

        # Animation timing
        self.t0 = time.time()

        # Load pristine background template
        self.bg_image = None
        bg_path = Path(__file__).parent / "jarvis_bg_clean.png"
        if not bg_path.exists():
            bg_path = Path(__file__).parent / "jarvis.png"
        if bg_path.exists():
            try:
                self.bg_image = pygame.image.load(str(bg_path)).convert()
            except Exception:
                self.bg_image = pygame.image.load(str(bg_path))

        # Fonts
        self._init_fonts()

    def _init_fonts(self):
        font_names = pygame.font.get_fonts()
        tech_font = "bahnschrift" if "bahnschrift" in font_names else "segoeui"
        clean_font = "segoeui" if "segoeui" in font_names else "arial"
        mono_font = "consolas" if "consolas" in font_names else "monospace"

        self.font_header_status = pygame.font.SysFont(tech_font, 15)
        self.font_conv_label = pygame.font.SysFont(clean_font, 16, bold=True)
        self.font_conv_text = pygame.font.SysFont(mono_font, 14)
        self.font_mic_label = pygame.font.SysFont(clean_font, 13, bold=False)

    # ---------------- public API ----------------
    def set_state(self, state, user_msg="", jarvis_msg=""):
        self.state = state
        user_name = profile.get_user_name()
        if user_msg:
            self.last_user = user_msg
            self.history.append((user_name, user_msg))
        if jarvis_msg:
            self.last_jarvis = jarvis_msg
            self.history.append(("Jarvis", jarvis_msg))
        self.history = self.history[-6:]

    def pop_manual_trigger(self) -> bool:
        if self._manual_trigger:
            self._manual_trigger = False
            return True
        return False

    def pop_interrupt_request(self) -> bool:
        """Returns True once (consuming the flag) if user requested an interrupt."""
        if self._interrupt_request:
            self._interrupt_request = False
            return True
        return False

    # ---------------- Geometry Helpers ----------------
    def _mic_button_canvas_geometry(self):
        cx = 213
        cy = 404
        r = 44
        return cx, cy, r

    def _canvas_to_screen_transform(self):
        scale = min(self.width / float(BASE_W), self.height / float(BASE_H))
        draw_w = int(BASE_W * scale)
        draw_h = int(BASE_H * scale)
        offset_x = (self.width - draw_w) // 2
        offset_y = (self.height - draw_h) // 2
        return scale, offset_x, offset_y, draw_w, draw_h

    # ---------------- Rendering Passes ----------------
    def _draw_center_core_effects(self, t):
        cx, cy = CORE_CX, CORE_CY

        # State-dependent pulsation parameters
        if self.state == "LISTENING":
            speed = 5.0
            glow_strength = 1.15 + 0.15 * math.sin(t * speed)
            sat_speed = 1.2
        elif self.state == "THINKING":
            speed = 8.0
            glow_strength = 1.25 + 0.2 * math.sin(t * speed)
            sat_speed = 2.2
        elif self.state == "RESPONDING":
            speed = 4.0
            glow_strength = 1.2 + 0.15 * math.sin(t * speed)
            sat_speed = 1.3
        else:  # IDLE
            speed = 1.8
            glow_strength = 1.0 + 0.08 * math.sin(t * speed)
            sat_speed = 0.75

        # 1. Soft radial corona bloom (600x600 surface ensures ZERO square edge clipping)
        corona_size = 600
        corona_surf = pygame.Surface((corona_size, corona_size), pygame.SRCALPHA)
        ccx = corona_size // 2
        ccy = corona_size // 2

        # Radial falloff staying well within the 300px half-width
        for i in range(8, 0, -1):
            r = int(i * 13 * glow_strength)
            alpha = int(3 * (9 - i) * (glow_strength * 0.7))
            pygame.draw.circle(corona_surf, (*AMBER_GLOW, min(45, alpha)), (ccx, ccy), r)
        self.canvas.blit(corona_surf, (cx - ccx, cy - ccy), special_flags=pygame.BLEND_ADD)

        # 2. Electric blue energy shimmer on monolith vertical seam
        seam_alpha = int(120 + 70 * math.sin(t * 3.5))
        seam_col = (*CYAN_BRIGHT, min(255, seam_alpha))
        seam_surf = pygame.Surface((20, 560), pygame.SRCALPHA)
        pygame.draw.line(seam_surf, seam_col, (10, 40), (10, 520), 2)
        self.canvas.blit(seam_surf, (cx - 10, cy - 280), special_flags=pygame.BLEND_ADD)

        # 3. 3D Orbiting Satellites along the elliptical ring (aligned at CORE_CY)
        rx = 265
        ry = 65
        theta = t * sat_speed

        # Satellite 1 (Primary cyan orb)
        sx = cx + rx * math.cos(theta)
        sy = cy + ry * math.sin(theta)
        depth = math.sin(theta)  # -1 back, +1 front
        r_sat = max(3, int(4.5 + 1.5 * depth))
        sat_alpha = int(180 + 75 * depth)

        sat_surf = pygame.Surface((32, 32), pygame.SRCALPHA)
        pygame.draw.circle(sat_surf, (*CYAN_BRIGHT, int(sat_alpha * 0.3)), (16, 16), r_sat + 5)
        pygame.draw.circle(sat_surf, (*CYAN_BRIGHT, sat_alpha), (16, 16), r_sat)
        pygame.draw.circle(sat_surf, (255, 255, 255, min(255, sat_alpha + 30)), (16, 16), max(1, r_sat - 2))
        self.canvas.blit(sat_surf, (int(sx - 16), int(sy - 16)))

        # Satellite 2 (Opposite secondary orb)
        theta2 = theta + math.pi
        sx2 = cx + rx * math.cos(theta2)
        sy2 = cy + ry * math.sin(theta2)
        depth2 = math.sin(theta2)
        r_sat2 = max(2, int(3.2 + 1.0 * depth2))
        sat_alpha2 = int(140 + 70 * depth2)

        sat_surf2 = pygame.Surface((24, 24), pygame.SRCALPHA)
        pygame.draw.circle(sat_surf2, (*CYAN_BRIGHT, sat_alpha2), (12, 12), r_sat2)
        self.canvas.blit(sat_surf2, (int(sx2 - 12), int(sy2 - 12)))

    def _draw_fluid_voice_wave(self, t):
        """
        Renders an organic, fluid audio-reactive wave circulating
        tightly around the perimeter of the center sun circle,
        fitting smoothly into the middle part of the artwork.
        """
        cx, cy = CORE_CX, CORE_CY
        R_BASE = SUN_RADIUS

        # Tight, small amplitude so it fits nicely in the middle part
        if self.state == "LISTENING":
            # Fluid undulates with voice detection, hugging the rim (5-7px max)
            target_amp = 5.5 + 2.0 * math.sin(t * 7.5) * math.cos(t * 3.2)
            flow_speed = 3.2
        elif self.state == "RESPONDING":
            # Fluid pulses in rhythm with Jarvis's voice
            target_amp = 4.5 + 1.5 * math.sin(t * 6.5)
            flow_speed = 2.6
        elif self.state == "THINKING":
            # Swirling fluid vortex
            target_amp = 3.8 + 1.2 * math.sin(t * 10.0)
            flow_speed = 5.0
        else:  # IDLE
            # Subtle resting liquid surface tension
            target_amp = 1.8 + 0.6 * math.sin(t * 2.0)
            flow_speed = 1.0

        # Smooth fluid amplitude transition
        self.fluid_amp += (target_amp - self.fluid_amp) * 0.15
        self.fluid_rot += 0.014 * flow_speed

        N = 180
        pts_cyan = []
        pts_gold = []

        fluid_surf = pygame.Surface((BASE_W, BASE_H), pygame.SRCALPHA)

        for i in range(N):
            theta = i * (math.tau / N)
            th_rot = theta - self.fluid_rot

            # Multiple traveling harmonic waves in interfering directions (fluid simulation)
            w1 = math.sin(th_rot * 4.0 - t * 4.0)
            w2 = math.cos(th_rot * 6.0 + t * 2.8) * 0.65
            w3 = math.sin(th_rot * 9.0 - t * 6.2) * 0.38
            w4 = math.cos(th_rot * 14.0 + t * 7.5) * 0.2

            disp = (w1 + w2 + w3 + w4) * self.fluid_amp

            # Primary cyan fluid wave
            r_c = R_BASE + disp
            pts_cyan.append((cx + r_c * math.cos(theta), cy + r_c * math.sin(theta)))

            # Secondary harmonic golden under-current wave
            w_g1 = math.sin(th_rot * 4.0 + t * 3.4)
            w_g2 = math.cos(th_rot * 7.0 - t * 4.8) * 0.6
            disp_gold = (w_g1 + w_g2) * (self.fluid_amp * 0.7)
            r_g = R_BASE + disp_gold - 1.5
            pts_gold.append((cx + r_g * math.cos(theta), cy + r_g * math.sin(theta)))

        # Draw fluid lines (no filled polygon to keep it crisp and transparent)
        if len(pts_gold) > 2:
            gold_alpha = 180 if self.state in ("LISTENING", "RESPONDING") else 110
            pygame.draw.lines(fluid_surf, (*AMBER_JARVIS, gold_alpha), True, pts_gold, 2)

        if len(pts_cyan) > 2:
            cyan_alpha = 240 if self.state in ("LISTENING", "RESPONDING") else 150
            pygame.draw.lines(fluid_surf, (150, 240, 255, cyan_alpha), True, pts_cyan, 2)

        # Draw tiny swirling liquid droplets around the sun rim
        for d in self.droplets:
            d["angle"] = (d["angle"] + 0.016 * d["speed"] * flow_speed) % math.tau
            th = d["angle"]
            w_d = math.sin(th * 4.0 - t * 4.0) * self.fluid_amp
            r_d = R_BASE + w_d + d["radius_offset"] * 0.5
            dx = cx + r_d * math.cos(th)
            dy = cy + r_d * math.sin(th)
            size = d["size"]
            alpha = d["alpha"] if self.state != "IDLE" else int(d["alpha"] * 0.4)

            pygame.draw.circle(fluid_surf, (*CYAN_BRIGHT, alpha), (int(dx), int(dy)), max(1, int(size)))

        self.canvas.blit(fluid_surf, (0, 0), special_flags=pygame.BLEND_ADD)

    def _draw_top_right_status(self):
        items = [
            ("LISTEN", "LISTENING"),
            ("/", ""),
            ("THINK", "THINKING"),
            ("/", ""),
            ("ASSIST", "RESPONDING"),
        ]
        hx = 1378
        hy = 48

        for text, st in items:
            if text == "/":
                col = (65, 90, 115)
                surf = self.font_header_status.render(text, True, col)
            else:
                is_active = (self.state == st)
                if is_active:
                    col = (255, 255, 255)
                    # Subtle text glow
                    glow_surf = self.font_header_status.render(text, True, CYAN_BRIGHT)
                    self.canvas.blit(glow_surf, (hx - 1, hy))
                    self.canvas.blit(glow_surf, (hx + 1, hy))
                else:
                    col = CYAN_MUTED
                surf = self.font_header_status.render(text, True, col)

            self.canvas.blit(surf, (hx, hy))
            hx += surf.get_width() + 16

    def _draw_mic_button(self, t):
        cx, cy, r = self._mic_button_canvas_geometry()

        # Sonar pulse ripple when recording / LISTENING
        if self.state == "LISTENING":
            ripple_t = (t * 2.2) % 1.0
            r_ripple = int(r + ripple_t * 26)
            alpha_ripple = int(140 * (1.0 - ripple_t))
            ripple_surf = pygame.Surface((r_ripple * 2 + 4, r_ripple * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(
                ripple_surf, (*CYAN_BRIGHT, alpha_ripple), (r_ripple + 2, r_ripple + 2), r_ripple, 2
            )
            self.canvas.blit(ripple_surf, (cx - r_ripple - 2, cy - r_ripple - 2))

        # Hover glow halo
        if self._mic_hover:
            hover_surf = pygame.Surface(((r + 14) * 2, (r + 14) * 2), pygame.SRCALPHA)
            for i in range(8, 0, -1):
                pygame.draw.circle(
                    hover_surf, (*CYAN_BRIGHT, int(12 * (9 - i))), (r + 14, r + 14), r + i * 2, 2
                )
            self.canvas.blit(hover_surf, (cx - r - 14, cy - r - 14))

        # Click flash ripple
        dt_click = time.time() - self._click_time
        if dt_click < 0.35:
            click_p = dt_click / 0.35
            cr = int(r + click_p * 35)
            ca = int(220 * (1.0 - click_p))
            click_surf = pygame.Surface((cr * 2 + 4, cr * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(click_surf, (*CYAN_BRIGHT, ca), (cr + 2, cr + 2), cr, 3)
            self.canvas.blit(click_surf, (cx - cr - 2, cy - cr - 2))

    def _draw_waveform_left(self, t):
        # Under mic button: centered at (208, 510)
        mid_y = 510
        x_mid = 208
        bars = 36
        bw = 2.0
        gap = 0.8
        total_w = bars * (bw + gap)
        start_x = x_mid - total_w / 2.0

        is_active = self.state in ("LISTENING", "RESPONDING")

        for i in range(bars):
            w_i = math.sin(i / float(bars - 1) * math.pi) ** 1.3
            if is_active:
                wave = (math.sin(t * 14.0 + i * 0.42) ** 2) * (
                    0.55 + 0.45 * math.sin(t * 6.0 + i * 0.22)
                )
                hh = max(2, int(w_i * (28 * (0.3 + 0.7 * wave))))
            else:
                hh = max(2, int(w_i * (5 + 3 * math.sin(t * 2.8 + i * 0.3))))

            px = int(start_x + i * (bw + gap))
            pygame.draw.rect(
                self.canvas, CYAN_BRIGHT, (px, int(mid_y - hh // 2), max(1, int(bw)), hh)
            )

    def _draw_waveform_bottom_right(self, t):
        # Bottom-right visualizer: centered at (1537, 875)
        mid_y = 875
        x_mid = 1537
        bars = 44
        bw = 2.2
        gap = 1.0
        total_w = bars * (bw + gap)
        start_x = x_mid - total_w / 2.0

        is_active = self.state in ("LISTENING", "RESPONDING")

        for i in range(bars):
            w_i = math.sin(i / float(bars - 1) * math.pi) ** 1.4
            if is_active:
                wave = (math.sin(t * 16.0 + i * 0.38) ** 2) * (
                    0.6 + 0.4 * math.sin(t * 7.5 + i * 0.25)
                )
                hh = max(2, int(w_i * (38 * (0.35 + 0.65 * wave))))
            else:
                hh = max(2, int(w_i * (6 + 4 * math.sin(t * 2.2 + i * 0.28))))

            px = int(start_x + i * (bw + gap))
            pygame.draw.rect(
                self.canvas, CYAN_BRIGHT, (px, int(mid_y - hh // 2), max(1, int(bw)), hh)
            )

    def _wrap_text(self, text, font, max_width):
        words = text.split(" ")
        lines = []
        current = ""
        for w in words:
            test = (current + " " + w).strip()
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = w
        if current:
            lines.append(current)
        return lines

    def _draw_conversation_panel(self):
        # Interior of the conversation frame: X=1342..1605, Y=360..530
        x0 = 1342
        y0 = 360
        max_w = 255
        max_h = 170

        render_queue = []
        history_to_show = self.history[-4:] if self.history else []

        user_name = profile.get_user_name()
        if not history_to_show:
            render_queue.append((user_name, ["> Say 'Hey Jarvis' or click MIC"]))
            render_queue.append(("Jarvis", [f"> Systems online for {user_name}."]))
        else:
            for speaker, text in history_to_show:
                wrapped = self._wrap_text(text, self.font_conv_text, max_w - 20)
                formatted = [f"> {line}" if i == 0 else f"  {line}" for i, line in enumerate(wrapped)]
                render_queue.append((speaker, formatted[:3]))

        total_h = 0
        block_heights = []
        for spk, lines in render_queue:
            bh = 24 + len(lines) * 19 + 8
            block_heights.append(bh)
            total_h += bh

        while total_h > max_h and len(render_queue) > 1:
            render_queue.pop(0)
            total_h -= block_heights.pop(0)

        curr_y = y0
        for spk, lines in render_queue:
            if spk in ("You", user_name):
                col_lbl = CYAN_BRIGHT
                col_txt = WHITE_TEXT
            else:
                col_lbl = AMBER_JARVIS
                col_txt = (180, 215, 240)

            lbl_surf = self.font_conv_label.render(spk, True, col_lbl)
            self.canvas.blit(lbl_surf, (x0, curr_y))
            curr_y += 24

            for l in lines:
                txt_surf = self.font_conv_text.render(l, True, col_txt)
                self.canvas.blit(txt_surf, (x0, curr_y))
                curr_y += 19

            curr_y += 8

    # ---------------- Main Render Loop ----------------
    def render(self):
        t = time.time() - self.t0
        scale, offset_x, offset_y, draw_w, draw_h = self._canvas_to_screen_transform()

        # Handle events
        self._mic_hover = False
        cx_mic, cy_mic, r_mic = self._mic_button_canvas_geometry()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.VIDEORESIZE:
                self.width, self.height = event.w, event.h
                self.screen = pygame.display.set_mode(
                    (self.width, self.height), pygame.RESIZABLE | pygame.DOUBLEBUF
                )

            elif event.type == pygame.KEYDOWN:
                # Escape or Space while Jarvis is speaking → interrupt immediately
                if event.key in (pygame.K_ESCAPE, pygame.K_SPACE):
                    if self.state == "RESPONDING":
                        self._interrupt_request = True

            elif event.type == pygame.MOUSEMOTION:
                mx, my = event.pos
                if scale > 0:
                    cmx = (mx - offset_x) / scale
                    cmy = (my - offset_y) / scale
                    if (cmx - cx_mic) ** 2 + (cmy - cy_mic) ** 2 <= r_mic ** 2:
                        self._mic_hover = True

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if scale > 0:
                    cmx = (mx - offset_x) / scale
                    cmy = (my - offset_y) / scale
                    if (cmx - cx_mic) ** 2 + (cmy - cy_mic) ** 2 <= (r_mic + 8) ** 2:
                        self._manual_trigger = True
                        self._click_time = time.time()
                    elif self.state == "RESPONDING":
                        # Clicking anywhere else on the HUD while Jarvis is speaking
                        # also stops the response so user can take over immediately
                        self._interrupt_request = True

        # 1. Draw base high-res artwork to canvas
        if self.bg_image:
            self.canvas.blit(self.bg_image, (0, 0))
        else:
            self.canvas.fill(BG_BLACK)

        # 2. Draw dynamic visual layers
        self._draw_center_core_effects(t)
        self._draw_fluid_voice_wave(t)
        self._draw_top_right_status()
        self._draw_mic_button(t)
        self._draw_waveform_left(t)
        self._draw_waveform_bottom_right(t)
        self._draw_conversation_panel()

        # 3. Present to screen with aspect-ratio scaling
        self.screen.fill(BG_BLACK)
        if draw_w == BASE_W and draw_h == BASE_H:
            self.screen.blit(self.canvas, (offset_x, offset_y))
        else:
            scaled_surf = pygame.transform.smoothscale(self.canvas, (draw_w, draw_h))
            self.screen.blit(scaled_surf, (offset_x, offset_y))

        pygame.display.flip()
        self.clock.tick(60)


if __name__ == "__main__":
    hud = JarvisHUD(1366, 768)
    hud.set_state("LISTENING", user_msg="What's the weather today?")
    time.sleep(1.0)
    hud.set_state("RESPONDING", jarvis_msg="It's 28°C, partly cloudy in Bangalore.")
    while hud.running:
        hud.render()