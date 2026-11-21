import math
import os
import struct
import sys
import zlib
from pathlib import Path

WIDTH = 1024
HEIGHT = 1024
MAX_PNG_BYTES = 1_048_576

PAPER = (246, 241, 231)
CARD_BG = (253, 250, 245)
ILLUS_BG = (237, 230, 216)
INK = (17, 22, 30)
MUTED = (74, 83, 96)
RULE = (32, 39, 50)
LIGHT_RULE = (210, 202, 188)
BANNER_BG = (17, 22, 30)
BANNER_FG = (246, 241, 231)
WHITE = (255, 255, 255)


class Canvas:
    def __init__(self, width: int, height: int, bg: tuple[int, int, int]) -> None:
        self.width = width
        self.height = height
        row = bytes(bg) * width
        self.buf = bytearray(row * height)

    def blend_px(self, x: int, y: int, color: tuple[int, int, int], alpha: float) -> None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height or alpha <= 0.0:
            return
        idx = (y * self.width + x) * 3
        if alpha >= 0.999:
            self.buf[idx] = color[0]
            self.buf[idx + 1] = color[1]
            self.buf[idx + 2] = color[2]
            return
        inv = 1.0 - alpha
        self.buf[idx] = int(self.buf[idx] * inv + color[0] * alpha + 0.5)
        self.buf[idx + 1] = int(self.buf[idx + 1] * inv + color[1] * alpha + 0.5)
        self.buf[idx + 2] = int(self.buf[idx + 2] * inv + color[2] * alpha + 0.5)

    def fill_rect(self, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.width, x + w)
        y1 = min(self.height, y + h)
        if x0 >= x1 or y0 >= y1:
            return
        span = bytes(color) * (x1 - x0)
        stride = self.width * 3
        start = x0 * 3
        end = x1 * 3
        for row_y in range(y0, y1):
            base = row_y * stride
            self.buf[base + start : base + end] = span

    def stroke_rect(
        self, x: int, y: int, w: int, h: int, thickness: int, color: tuple[int, int, int]
    ) -> None:
        self.fill_rect(x, y, w, thickness, color)
        self.fill_rect(x, y + h - thickness, w, thickness, color)
        self.fill_rect(x, y, thickness, h, color)
        self.fill_rect(x + w - thickness, y, thickness, h, color)

    def fill_round_rect(
        self, x: float, y: float, w: float, h: float, r: float, color: tuple[int, int, int]
    ) -> None:
        r = min(r, w * 0.5, h * 0.5)
        x0 = max(0, int(math.floor(x - 1)))
        y0 = max(0, int(math.floor(y - 1)))
        x1 = min(self.width - 1, int(math.ceil(x + w + 1)))
        y1 = min(self.height - 1, int(math.ceil(y + h + 1)))
        cx = x + w * 0.5
        cy = y + h * 0.5
        hx = w * 0.5 - r
        hy = h * 0.5 - r
        for py in range(y0, y1 + 1):
            dy = abs(py + 0.5 - cy) - hy
            for px in range(x0, x1 + 1):
                dx = abs(px + 0.5 - cx) - hx
                qx = max(dx, 0.0)
                qy = max(dy, 0.0)
                dist = math.hypot(qx, qy) + min(max(dx, dy), 0.0) - r
                if dist <= -0.5:
                    self.blend_px(px, py, color, 1.0)
                elif dist < 0.5:
                    self.blend_px(px, py, color, 0.5 - dist)

    def fill_circle(
        self, cx: float, cy: float, r: float, color: tuple[int, int, int]
    ) -> None:
        x0 = max(0, int(math.floor(cx - r - 1.5)))
        y0 = max(0, int(math.floor(cy - r - 1.5)))
        x1 = min(self.width - 1, int(math.ceil(cx + r + 1.5)))
        y1 = min(self.height - 1, int(math.ceil(cy + r + 1.5)))
        for py in range(y0, y1 + 1):
            dy = py + 0.5 - cy
            for px in range(x0, x1 + 1):
                dist = math.hypot(px + 0.5 - cx, dy) - r
                if dist <= -0.5:
                    self.blend_px(px, py, color, 1.0)
                elif dist < 0.5:
                    self.blend_px(px, py, color, 0.5 - dist)

    def stroke_circle(
        self, cx: float, cy: float, r: float, thickness: float, color: tuple[int, int, int]
    ) -> None:
        half_t = thickness * 0.5
        x0 = max(0, int(math.floor(cx - r - half_t - 1.5)))
        y0 = max(0, int(math.floor(cy - r - half_t - 1.5)))
        x1 = min(self.width - 1, int(math.ceil(cx + r + half_t + 1.5)))
        y1 = min(self.height - 1, int(math.ceil(cy + r + half_t + 1.5)))
        for py in range(y0, y1 + 1):
            dy = py + 0.5 - cy
            for px in range(x0, x1 + 1):
                dist = abs(math.hypot(px + 0.5 - cx, dy) - r) - half_t
                if dist <= -0.5:
                    self.blend_px(px, py, color, 1.0)
                elif dist < 0.5:
                    self.blend_px(px, py, color, 0.5 - dist)

    def draw_capsule(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        radius: float,
        color: tuple[int, int, int],
        alpha: float = 1.0,
    ) -> None:
        bx0 = max(0, int(math.floor(min(x0, x1) - radius - 1.5)))
        by0 = max(0, int(math.floor(min(y0, y1) - radius - 1.5)))
        bx1 = min(self.width - 1, int(math.ceil(max(x0, x1) + radius + 1.5)))
        by1 = min(self.height - 1, int(math.ceil(max(y0, y1) + radius + 1.5)))
        vx = x1 - x0
        vy = y1 - y0
        len_sq = vx * vx + vy * vy
        for py in range(by0, by1 + 1):
            cy = py + 0.5 - y0
            for px in range(bx0, bx1 + 1):
                cx = px + 0.5 - x0
                if len_sq <= 1e-9:
                    d = math.hypot(cx, cy) - radius
                else:
                    t = max(0.0, min(1.0, (cx * vx + cy * vy) / len_sq))
                    d = math.hypot(cx - t * vx, cy - t * vy) - radius
                if d <= -0.5:
                    self.blend_px(px, py, color, alpha)
                elif d < 0.5:
                    self.blend_px(px, py, color, (0.5 - d) * alpha)

    def draw_arc(
        self,
        cx: float,
        cy: float,
        r: float,
        deg_start: float,
        deg_end: float,
        thickness: float,
        color: tuple[int, int, int],
        steps: int = 28,
    ) -> None:
        rad_s = math.radians(deg_start)
        rad_e = math.radians(deg_end)
        radius = thickness * 0.5
        prev_x = cx + r * math.cos(rad_s)
        prev_y = cy + r * math.sin(rad_s)
        for i in range(1, steps + 1):
            a = rad_s + (rad_e - rad_s) * (i / steps)
            nx = cx + r * math.cos(a)
            ny = cy + r * math.sin(a)
            self.draw_capsule(prev_x, prev_y, nx, ny, radius, color)
            prev_x, prev_y = nx, ny

    def fill_polygon(
        self, pts: list[tuple[float, float]], color: tuple[int, int, int]
    ) -> None:
        if len(pts) < 3:
            return
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(self.height - 1, int(math.ceil(max(ys))))
        x0 = max(0, int(math.floor(min(xs))))
        x1 = min(self.width - 1, int(math.ceil(max(xs))))
        n = len(pts)
        for py in range(y0, y1 + 1):
            sy = py + 0.5
            intersections: list[float] = []
            for i in range(n):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % n]
                if (ay <= sy < by) or (by <= sy < ay):
                    ix = ax + (sy - ay) * (bx - ax) / (by - ay)
                    intersections.append(ix)
            intersections.sort()
            for i in range(0, len(intersections) - 1, 2):
                lx = max(x0, int(math.floor(intersections[i])))
                rx = min(x1, int(math.ceil(intersections[i + 1])))
                for px in range(lx, rx + 1):
                    self.blend_px(px, py, color, 1.0)


GLYPHS: dict[str, tuple[int, list[list[tuple[int, int]]]]] = {
    " ": (48, []),
    "A": (76, [[(8, 100), (38, 0), (68, 100)], [(18, 66), (58, 66)]]),
    "B": (74, [[(12, 100), (12, 0), (48, 0), (60, 12), (60, 36), (48, 48), (12, 48)], [(48, 48), (64, 60), (64, 86), (48, 100), (12, 100)]]),
    "C": (74, [[(64, 18), (50, 0), (26, 0), (12, 18), (12, 82), (26, 100), (50, 100), (64, 82)]]),
    "D": (76, [[(12, 100), (12, 0), (44, 0), (64, 20), (64, 80), (44, 100), (12, 100)]]),
    "E": (68, [[(58, 0), (12, 0), (12, 100), (60, 100)], [(12, 48), (48, 48)]]),
    "F": (64, [[(56, 0), (12, 0), (12, 100)], [(12, 48), (48, 48)]]),
    "G": (78, [[(64, 18), (50, 0), (26, 0), (12, 18), (12, 82), (26, 100), (52, 100), (66, 82), (66, 54), (42, 54)]]),
    "H": (76, [[(12, 0), (12, 100)], [(64, 0), (64, 100)], [(12, 48), (64, 48)]]),
    "I": (38, [[(19, 0), (19, 100)], [(8, 0), (30, 0)], [(8, 100), (30, 100)]]),
    "J": (62, [[(50, 0), (50, 80), (36, 100), (18, 100), (10, 84)]]),
    "K": (74, [[(12, 0), (12, 100)], [(64, 0), (12, 54)], [(28, 38), (66, 100)]]),
    "L": (64, [[(12, 0), (12, 100), (58, 100)]]),
    "M": (86, [[(12, 100), (12, 0), (43, 62), (74, 0), (74, 100)]]),
    "N": (76, [[(12, 100), (12, 0), (64, 100), (64, 0)]]),
    "O": (80, [[(26, 0), (54, 0), (68, 18), (68, 82), (54, 100), (26, 100), (12, 82), (12, 18), (26, 0)]]),
    "P": (72, [[(12, 100), (12, 0), (48, 0), (62, 14), (62, 40), (48, 54), (12, 54)]]),
    "Q": (80, [[(26, 0), (54, 0), (68, 18), (68, 82), (54, 100), (26, 100), (12, 82), (12, 18), (26, 0)], [(46, 72), (72, 106)]]),
    "R": (74, [[(12, 100), (12, 0), (48, 0), (62, 14), (62, 38), (48, 52), (12, 52)], [(38, 52), (64, 100)]]),
    "S": (72, [[(60, 14), (48, 0), (24, 0), (12, 14), (12, 34), (24, 46), (48, 52), (62, 64), (62, 86), (48, 100), (22, 100), (10, 86)]]),
    "T": (70, [[(6, 0), (64, 0)], [(35, 0), (35, 100)]]),
    "U": (76, [[(12, 0), (12, 80), (26, 100), (50, 100), (64, 80), (64, 0)]]),
    "V": (74, [[(8, 0), (37, 100), (66, 0)]]),
    "W": (94, [[(8, 0), (24, 100), (47, 34), (70, 100), (86, 0)]]),
    "X": (74, [[(10, 0), (64, 100)], [(64, 0), (10, 100)]]),
    "Y": (72, [[(8, 0), (36, 52), (64, 0)], [(36, 52), (36, 100)]]),
    "Z": (70, [[(10, 0), (60, 0), (10, 100), (60, 100)]]),
    "a": (64, [[(16, 36), (44, 36), (54, 46), (54, 100)], [(54, 62), (20, 62), (10, 74), (10, 88), (20, 100), (44, 100), (54, 88)]]),
    "b": (66, [[(12, 0), (12, 100)], [(12, 48), (24, 34), (46, 34), (56, 48), (56, 86), (46, 100), (24, 100), (12, 86)]]),
    "c": (60, [[(52, 46), (42, 34), (22, 34), (12, 46), (12, 86), (22, 100), (42, 100), (52, 86)]]),
    "d": (66, [[(54, 0), (54, 100)], [(54, 48), (42, 34), (22, 34), (12, 48), (12, 86), (22, 100), (42, 100), (54, 86)]]),
    "e": (64, [[(12, 66), (54, 66), (54, 46), (42, 34), (22, 34), (12, 46), (12, 86), (22, 100), (44, 100), (52, 90)]]),
    "f": (46, [[(40, 6), (30, 0), (20, 10), (20, 100)], [(8, 36), (38, 36)]]),
    "g": (66, [[(54, 34), (54, 108), (42, 122), (18, 122)], [(54, 48), (42, 34), (22, 34), (12, 48), (12, 84), (22, 98), (42, 98), (54, 84)]]),
    "h": (66, [[(12, 0), (12, 100)], [(12, 50), (24, 34), (44, 34), (54, 48), (54, 100)]]),
    "i": (32, [[(16, 36), (16, 100)], [(16, 6), (16, 14)]]),
    "j": (38, [[(24, 36), (24, 108), (14, 122), (4, 120)], [(24, 6), (24, 14)]]),
    "k": (60, [[(12, 0), (12, 100)], [(52, 34), (12, 70)], [(24, 58), (54, 100)]]),
    "l": (32, [[(16, 0), (16, 100)]]),
    "m": (90, [[(12, 34), (12, 100)], [(12, 48), (22, 34), (36, 34), (45, 48), (45, 100)], [(45, 48), (56, 34), (70, 34), (78, 48), (78, 100)]]),
    "n": (66, [[(12, 34), (12, 100)], [(12, 48), (24, 34), (44, 34), (54, 48), (54, 100)]]),
    "o": (66, [[(22, 34), (44, 34), (54, 48), (54, 86), (44, 100), (22, 100), (12, 86), (12, 48), (22, 34)]]),
    "p": (66, [[(12, 34), (12, 122)], [(12, 48), (24, 34), (44, 34), (54, 48), (54, 84), (44, 98), (24, 98), (12, 84)]]),
    "q": (66, [[(54, 34), (54, 122)], [(54, 48), (42, 34), (22, 34), (12, 48), (12, 84), (22, 98), (42, 98), (54, 84)]]),
    "r": (48, [[(12, 34), (12, 100)], [(12, 52), (24, 34), (40, 34)]]),
    "s": (58, [[(48, 44), (38, 34), (20, 34), (10, 44), (10, 56), (20, 64), (38, 70), (48, 78), (48, 90), (38, 100), (18, 100), (10, 90)]]),
    "t": (46, [[(20, 6), (20, 88), (30, 100), (40, 98)], [(8, 36), (36, 36)]]),
    "u": (66, [[(12, 34), (12, 86), (22, 100), (44, 100), (54, 86), (54, 34)]]),
    "v": (60, [[(8, 34), (30, 100), (52, 34)]]),
    "w": (82, [[(8, 34), (22, 100), (41, 52), (60, 100), (74, 34)]]),
    "x": (60, [[(10, 34), (50, 100)], [(50, 34), (10, 100)]]),
    "y": (60, [[(8, 34), (30, 96)], [(52, 34), (22, 122), (10, 122)]]),
    "z": (56, [[(10, 34), (48, 34), (10, 100), (48, 100)]]),
    "0": (68, [[(24, 0), (44, 0), (58, 16), (58, 84), (44, 100), (24, 100), (10, 84), (10, 16), (24, 0)], [(14, 80), (54, 20)]]),
    "1": (56, [[(14, 20), (30, 0), (30, 100)], [(12, 100), (48, 100)]]),
    "2": (68, [[(10, 20), (24, 0), (46, 0), (58, 16), (58, 36), (10, 100), (60, 100)]]),
    "3": (68, [[(10, 14), (24, 0), (46, 0), (58, 16), (58, 34), (44, 48), (28, 48)], [(44, 48), (58, 62), (58, 84), (46, 100), (22, 100), (10, 86)]]),
    "4": (68, [[(48, 100), (48, 0), (10, 68), (60, 68)]]),
    "5": (68, [[(56, 0), (14, 0), (14, 44), (44, 44), (58, 58), (58, 84), (44, 100), (22, 100), (10, 86)]]),
    "6": (68, [[(54, 12), (42, 0), (24, 0), (10, 18), (10, 82), (24, 100), (46, 100), (58, 84), (58, 60), (46, 46), (24, 46), (10, 60)]]),
    "7": (66, [[(10, 0), (58, 0), (24, 100)]]),
    "8": (68, [[(24, 48), (12, 34), (12, 14), (24, 0), (44, 0), (56, 14), (56, 34), (44, 48), (24, 48), (10, 62), (10, 84), (24, 100), (44, 100), (58, 84), (58, 62), (44, 48)]]),
    "9": (68, [[(14, 88), (26, 100), (44, 100), (58, 82), (58, 18), (44, 0), (22, 0), (10, 16), (10, 40), (22, 54), (44, 54), (58, 40)]]),
    ".": (32, [[(14, 92), (18, 92), (18, 98), (14, 98), (14, 92)]]),
    ",": (34, [[(16, 90), (18, 90), (12, 114)]]),
    ":": (32, [[(14, 34), (18, 34), (18, 40), (14, 40), (14, 34)], [(14, 88), (18, 88), (18, 94), (14, 94), (14, 88)]]),
    "-": (48, [[(10, 52), (38, 52)]]),
    "+": (60, [[(10, 52), (50, 52)], [(30, 30), (30, 74)]]),
    "/": (56, [[(46, 0), (10, 100)]]),
    "&": (74, [[(58, 100), (14, 34), (14, 14), (26, 0), (42, 0), (52, 14), (52, 30), (12, 66), (12, 86), (24, 100), (44, 100), (62, 76)]]),
    "%": (80, [[(64, 0), (16, 100)], [(16, 8), (26, 8), (26, 22), (16, 22), (16, 8)], [(54, 78), (64, 78), (64, 92), (54, 92), (54, 78)]]),
    "$": (68, [[(56, 18), (44, 6), (22, 6), (10, 18), (10, 36), (22, 48), (46, 54), (58, 66), (58, 84), (46, 94), (22, 94), (10, 82)], [(34, -4), (34, 104)]]),
    "·": (40, [[(18, 48), (22, 48), (22, 54), (18, 54), (18, 48)]]),
}


def measure_text(text: str, size: float, tracking: float = 0.0) -> float:
    scale = size / 100.0
    total = 0.0
    for i, ch in enumerate(text):
        adv = GLYPHS.get(ch, GLYPHS[" "])[0]
        total += adv * scale
        if i + 1 < len(text):
            total += tracking
    return total


def draw_text(
    canvas: Canvas,
    text: str,
    x: float,
    y: float,
    size: float,
    color: tuple[int, int, int],
    weight: float = 0.085,
    tracking: float = 0.0,
) -> float:
    scale = size / 100.0
    radius = max(0.65, size * weight * 0.5)
    cursor = x
    for ch in text:
        adv, strokes = GLYPHS.get(ch, GLYPHS[" "])
        for poly in strokes:
            for i in range(len(poly) - 1):
                px0 = cursor + poly[i][0] * scale
                py0 = y + poly[i][1] * scale
                px1 = cursor + poly[i + 1][0] * scale
                py1 = y + poly[i + 1][1] * scale
                canvas.draw_capsule(px0, py0, px1, py1, radius, color)
        cursor += adv * scale + tracking
    return cursor


def draw_text_centered(
    canvas: Canvas,
    text: str,
    cx: float,
    y: float,
    size: float,
    color: tuple[int, int, int],
    weight: float = 0.085,
    tracking: float = 0.0,
) -> None:
    w = measure_text(text, size, tracking)
    draw_text(canvas, text, cx - w * 0.5, y, size, color, weight, tracking)


def draw_scene_climate(canvas: Canvas, x: int, y: int, w: int, h: int, accent: tuple[int, int, int]) -> None:
    canvas.fill_rect(x, y, w, h, (228, 240, 234))
    cx = x + w * 0.36
    cy = y + h * 0.44
    r = 32.0
    canvas.fill_circle(cx, cy, r, (24, 92, 134))
    canvas.fill_polygon(
        [(cx - 13, cy - 18), (cx + 7, cy - 15), (cx + 15, cy + 4), (cx + 2, cy + 23), (cx - 8, cy + 10)],
        accent,
    )
    canvas.stroke_circle(cx, cy, r, 2.5, INK)
    canvas.draw_arc(cx, cy, r + 8, -55, 45, 3.0, accent)
    bars = [28, 46, 66, 88]
    for i, bh in enumerate(bars):
        bx = x + w - 42 + i * 9
        by = y + h - 16 - bh
        canvas.fill_rect(bx, by, 6, bh, accent if i == 3 else (70, 145, 112))
    canvas.fill_rect(x + 10, y + h - 16, w - 20, 2, INK)


def draw_scene_g20(canvas: Canvas, x: int, y: int, w: int, h: int, accent: tuple[int, int, int]) -> None:
    canvas.fill_rect(x, y, w, h, (244, 232, 222))
    cx = x + w * 0.48
    cy = y + h * 0.48
    africa = [
        (cx - 28, cy - 42),
        (cx + 8, cy - 44),
        (cx + 34, cy - 16),
        (cx + 24, cy + 14),
        (cx + 6, cy + 48),
        (cx - 10, cy + 44),
        (cx - 14, cy + 6),
        (cx - 34, cy - 10),
    ]
    canvas.fill_polygon(africa, accent)
    nodes = [(cx - 10, cy - 22), (cx + 16, cy - 8), (cx - 2, cy + 32), (cx + 10, cy + 14)]
    for i in range(len(nodes) - 1):
        canvas.draw_capsule(nodes[i][0], nodes[i][1], nodes[i + 1][0], nodes[i + 1][1], 1.8, (250, 235, 200))
    for nx, ny in nodes:
        canvas.fill_circle(nx, ny, 4.5, INK)
        canvas.fill_circle(nx, ny, 2.3, (255, 210, 90))


def draw_scene_europe(canvas: Canvas, x: int, y: int, w: int, h: int, accent: tuple[int, int, int]) -> None:
    canvas.fill_rect(x, y, w, h, (226, 235, 246))
    tx = x + 38
    ty = y + h - 22
    hub_y = y + 52
    canvas.draw_capsule(tx, ty, tx, hub_y, 2.5, INK)
    for deg in (-90, 30, 150):
        rad = math.radians(deg)
        canvas.draw_capsule(tx, hub_y, tx + 28 * math.cos(rad), hub_y + 28 * math.sin(rad), 2.2, accent)
    canvas.fill_circle(tx, hub_y, 4.5, INK)
    gx = x + w - 34
    gy = y + h * 0.40
    canvas.stroke_circle(gx, gy, 21, 5.5, (195, 210, 228))
    canvas.draw_arc(gx, gy, 21, -135, 195, 5.5, accent)
    px = x + w - 58
    py = y + h - 54
    canvas.fill_rect(px, py, 44, 24, (28, 52, 92))
    for i in range(1, 4):
        canvas.fill_rect(px + i * 11, py, 1, 24, (140, 185, 230))
    canvas.fill_rect(px, py + 12, 44, 1, (140, 185, 230))
    canvas.fill_rect(x + 12, ty, w - 24, 2, INK)


def draw_scene_asiapac(canvas: Canvas, x: int, y: int, w: int, h: int, accent: tuple[int, int, int]) -> None:
    canvas.fill_rect(x, y, w, h, (236, 229, 245))
    wx = x + 36
    wy = y + 36
    ws = 64
    canvas.fill_round_rect(wx, wy, ws, ws, 8, (35, 28, 52))
    canvas.stroke_rect(wx + 10, wy + 10, ws - 20, ws - 20, 2, accent)
    for i in range(4):
        p = wx + 14 + i * 11
        canvas.fill_rect(p, wy - 7, 4, 7, accent)
        canvas.fill_rect(p, wy + ws, 4, 7, accent)
        canvas.fill_rect(wx - 7, wy + 14 + i * 11, 7, 4, accent)
        canvas.fill_rect(wx + ws, wy + 14 + i * 11, 7, 4, accent)
    canvas.draw_arc(x + w * 0.5, y + h - 18, 48, 200, 340, 2.5, accent)
    canvas.fill_circle(x + 26, y + h - 30, 4.0, INK)
    canvas.fill_circle(x + w - 26, y + h - 30, 4.0, INK)


def draw_scene_mideast(canvas: Canvas, x: int, y: int, w: int, h: int, accent: tuple[int, int, int]) -> None:
    canvas.fill_rect(x, y, w, h, (246, 229, 232))
    canvas.fill_polygon([(x, y), (x + 48, y), (x + 34, y + h), (x, y + h)], (215, 198, 176))
    canvas.fill_polygon([(x + w - 44, y), (x + w, y), (x + w, y + h), (x + w - 28, y + h)], (215, 198, 176))
    cx = x + w * 0.5
    canvas.draw_capsule(cx - 4, y + 18, cx + 6, y + h - 18, 2.2, (26, 95, 145))
    ship_y = y + h * 0.54
    canvas.fill_polygon(
        [(cx - 20, ship_y), (cx + 22, ship_y), (cx + 15, ship_y + 14), (cx - 14, ship_y + 14)],
        INK,
    )
    canvas.fill_rect(int(cx - 8), int(ship_y - 10), 16, 10, accent)
    ax = x + w - 24
    ay = y + 26
    canvas.fill_circle(ax, ay, 13, WHITE)
    canvas.fill_rect(ax - 3, ay - 8, 6, 16, accent)
    canvas.fill_rect(ax - 8, ay - 3, 16, 6, accent)


def draw_scene_space(canvas: Canvas, x: int, y: int, w: int, h: int, accent: tuple[int, int, int]) -> None:
    canvas.fill_rect(x, y, w, h, (19, 34, 48))
    cx = x + w * 0.5
    earth_cy = y + h + 26
    canvas.fill_circle(cx, earth_cy, 72, (28, 112, 148))
    canvas.stroke_circle(cx, earth_cy, 72, 2.5, (110, 215, 230))
    canvas.draw_arc(cx, earth_cy, 96, 220, 320, 2.2, (245, 200, 90))
    rx = cx + 26
    ry = y + 40
    canvas.fill_circle(rx, ry, 5.5, WHITE)
    canvas.fill_rect(int(rx - 12), int(ry - 2), 24, 4, accent)
    for sx, sy in [(x + 22, y + 22), (x + w - 24, y + 24), (x + 30, y + 58), (x + w - 28, y + 66)]:
        canvas.fill_circle(sx, sy, 1.8, WHITE)
    canvas.draw_arc(cx, y + h - 18, 28, 215, 325, 2.0, (120, 235, 220))
    canvas.draw_arc(cx, y + h - 18, 16, 215, 325, 2.0, (120, 235, 220))


SCENE_FN = {
    "climate": draw_scene_climate,
    "g20": draw_scene_g20,
    "europe": draw_scene_europe,
    "asiapac": draw_scene_asiapac,
    "mideast": draw_scene_mideast,
    "space": draw_scene_space,
}


CARDS = [
    {
        "id": "climate",
        "badge": "AMERICAS · CLIMATE",
        "callout": "$300B/YR",
        "accent": (27, 127, 92),
        "h1": "BELEM CLIMATE FINANCE",
        "h2": "ACCORD CLEARED",
        "bullets": [
            "COP30-31 implementation pact",
            "Adaptation & loss-damage fund",
            "Public-private tranche set",
        ],
        "foot": "BELEM · COP30-31 FINANCE PACT",
    },
    {
        "id": "g20",
        "badge": "AFRICA · G20 SUMMIT",
        "callout": "G20 FINAL",
        "accent": (194, 89, 27),
        "h1": "JOHANNESBURG SHERPA",
        "h2": "COMMUNIQUE SEALED",
        "bullets": [
            "Critical minerals corridors",
            "Multilateral debt-relief deal",
            "AU-G20 infrastructure pact",
        ],
        "foot": "JOHANNESBURG · G20 COMMUNIQUE",
    },
    {
        "id": "europe",
        "badge": "EUROPE · ENERGY",
        "callout": "94.2% GAS",
        "accent": (29, 91, 155),
        "h1": "CONTINENTAL WINTER GRID",
        "h2": "& CLEAN INDUSTRY PACT",
        "bullets": [
            "HVDC cross-border balancing",
            "94.2% EU storage ahead of peak",
            "Clean industry power accord",
        ],
        "foot": "BRUSSELS · ENTSO-E WINTER GRID",
    },
    {
        "id": "asiapac",
        "badge": "ASIA-PAC · TECH",
        "callout": "2NM + CABLE",
        "accent": (109, 59, 158),
        "h1": "SEMICONDUCTOR SUPPLY &",
        "h2": "MARITIME CORRIDOR",
        "bullets": [
            "2nm fab supply resilience",
            "Protected subsea cable routes",
            "Pacific port digital customs",
        ],
        "foot": "SINGAPORE · PACIFIC SUPPLY PACT",
    },
    {
        "id": "mideast",
        "badge": "MIDEAST & TRADE",
        "callout": "AID ROUTE",
        "accent": (168, 40, 59),
        "h1": "RED SEA LOGISTICS &",
        "h2": "HUMANITARIAN PASSAGE",
        "bullets": [
            "Escorted maritime transit",
            "Port-to-inland aid convoys",
            "Regional freight stabilization",
        ],
        "foot": "RED SEA · HUMANITARIAN TRANSIT",
    },
    {
        "id": "space",
        "badge": "SCIENCE & SPACE",
        "callout": "ORBIT + SEA",
        "accent": (15, 107, 122),
        "h1": "ORBITAL LAUNCH & DEEP-",
        "h2": "OCEAN MAPPING",
        "bullets": [
            "Heavy-lift orbital insertion",
            "Autonomous AUV seabed scan",
            "4,200m trench telemetry live",
        ],
        "foot": "GLOBAL · ORBITAL & TRENCH DATA",
    },
]


def render_broadsheet() -> Canvas:
    c = Canvas(WIDTH, HEIGHT, PAPER)
    margin = 20
    inner_w = WIDTH - margin * 2

    c.fill_rect(margin, 16, inner_w, 2, RULE)
    draw_text(c, "2026-11-21 · GLOBAL EDITION", margin + 2, 24, 13, MUTED, weight=0.09)
    draw_text_centered(c, "SIX-REGION WORLD BRIEFING", WIDTH * 0.5, 24, 13, MUTED, weight=0.09)
    right_lbl = "VOL. I · NO. 21"
    rw = measure_text(right_lbl, 13)
    draw_text(c, right_lbl, WIDTH - margin - rw - 2, 24, 13, MUTED, weight=0.09)
    c.fill_rect(margin, 44, inner_w, 1, LIGHT_RULE)

    draw_text_centered(c, "WORLD NEWS DISPATCH", WIDTH * 0.5, 56, 48, INK, weight=0.115, tracking=1.6)

    c.fill_rect(margin, 118, inner_w, 34, BANNER_BG)
    draw_text_centered(
        c,
        "SATURDAY, 21 NOVEMBER 2026 · 2026-11-21 GLOBAL EDITION",
        WIDTH * 0.5,
        127,
        17,
        BANNER_FG,
        weight=0.095,
        tracking=0.6,
    )

    grid_top = 166
    gutter = 14
    card_w = (inner_w - gutter) // 2
    card_h = 262
    for idx, card in enumerate(CARDS):
        col = idx % 2
        row = idx // 2
        cx = margin + col * (card_w + gutter)
        cy = grid_top + row * (card_h + gutter)
        accent = card["accent"]

        c.fill_rect(cx, cy, card_w, card_h, CARD_BG)
        c.stroke_rect(cx, cy, card_w, card_h, 1, LIGHT_RULE)
        c.fill_rect(cx, cy, card_w, 5, accent)

        badge_w = int(measure_text(card["badge"], 12.5) + 18)
        c.fill_round_rect(cx + 12, cy + 14, badge_w, 22, 4, accent)
        draw_text(c, card["badge"], cx + 21, cy + 19, 12.5, WHITE, weight=0.095)

        call_w = int(measure_text(card["callout"], 12.5) + 16)
        c.fill_round_rect(cx + card_w - call_w - 12, cy + 14, call_w, 22, 4, ILLUS_BG)
        draw_text(c, card["callout"], cx + card_w - call_w - 4, cy + 19, 12.5, INK, weight=0.095)

        illus_x = cx + 12
        illus_y = cy + 46
        illus_w = 128
        illus_h = 200
        SCENE_FN[card["id"]](c, illus_x, illus_y, illus_w, illus_h, accent)
        c.stroke_rect(illus_x, illus_y, illus_w, illus_h, 1, LIGHT_RULE)

        tx = illus_x + illus_w + 14
        draw_text(c, card["h1"], tx, cy + 50, 18.5, INK, weight=0.105)
        draw_text(c, card["h2"], tx, cy + 75, 18.5, INK, weight=0.105)
        c.fill_rect(tx, cy + 103, card_w - (tx - cx) - 14, 2, accent)

        by = cy + 118
        for bullet in card["bullets"]:
            c.fill_circle(tx + 4, by + 7, 3.0, accent)
            draw_text(c, bullet, tx + 14, by, 14.5, MUTED, weight=0.09)
            by += 31

        foot_y = cy + card_h - 32
        c.fill_rect(tx, foot_y, card_w - (tx - cx) - 14, 20, ILLUS_BG)
        draw_text(c, card["foot"], tx + 8, foot_y + 4, 11.5, INK, weight=0.095)

    footer_y = HEIGHT - 32
    c.fill_rect(margin, footer_y - 8, inner_w, 2, RULE)
    draw_text_centered(
        c,
        "WORLD NEWS DISPATCH · SATURDAY, 21 NOVEMBER 2026 · ALL SIX REGIONS",
        WIDTH * 0.5,
        footer_y,
        13,
        MUTED,
        weight=0.09,
    )
    return c


def encode_png(canvas: Canvas) -> bytes:
    stride = canvas.width * 3
    raw = bytearray((stride + 1) * canvas.height)
    for y in range(canvas.height):
        src_off = y * stride
        dst_off = y * (stride + 1)
        raw[dst_off] = 1
        row = canvas.buf[src_off : src_off + stride]
        dst = dst_off + 1
        raw[dst : dst + 3] = row[0:3]
        for i in range(3, stride):
            raw[dst + i] = (row[i] - row[i - 3]) & 0xFF

    compressed = zlib.compress(bytes(raw), level=9)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", canvas.width, canvas.height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    if len(png) > MAX_PNG_BYTES:
        raise RuntimeError(f"PNG exceeds {MAX_PNG_BYTES} bytes: {len(png)}")
    return png


def resolve_output_path(argv: list[str]) -> Path:
    if len(argv) >= 3 and argv[1] == "--out":
        return Path(argv[2])
    if len(argv) >= 2 and not argv[1].startswith("-"):
        return Path(argv[1])
    out_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    return out_dir / "entry.png"


def main() -> int:
    out_path = resolve_output_path(sys.argv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = render_broadsheet()
    png_bytes = encode_png(canvas)
    out_path.write_bytes(png_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
