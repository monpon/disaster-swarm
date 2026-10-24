"""Mono drone-camera frames of the person types used in the vitals section.

Same look as the feeds in gen2.py: flat-shaded room, light falloff, blur,
sensor noise and vignette. Writes person-lying.png, person-sitting.png and
person-debris.png into the given directory.
"""
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = sys.argv[1]
FW, FH = 640, 400


def render(seed, polys, light):
    rng = np.random.default_rng(seed)
    base = Image.new("L", (FW, FH), 60)
    d = ImageDraw.Draw(base)
    for kind, pts, v in polys:
        if kind == "poly":
            d.polygon(pts, fill=v)
        else:
            d.ellipse(pts, fill=v)
    a = np.asarray(base).astype(np.float32)
    yy, xx = np.mgrid[0:FH, 0:FW]
    lx, ly, lr = light
    a *= 0.55 + 0.75 * np.exp(-(((xx - lx) ** 2 + (yy - ly) ** 2) / (2 * lr**2)))
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.8))
    a = np.asarray(im).astype(np.float32) + rng.normal(0, 9, (FH, FW))
    v = ((xx - FW / 2) / (FW / 2)) ** 2 + ((yy - FH / 2) / (FH / 2)) ** 2
    a *= 1 - 0.38 * np.clip(v, 0, 1.6) / 1.6
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def room(bx1, by1, bx2, by2, fl=96, ce=42, lw=72, rw=66, bw=86):
    return [
        ("poly", [(0, FH), (FW, FH), (bx2, by2), (bx1, by2)], fl),
        ("poly", [(0, 0), (FW, 0), (bx2, by1), (bx1, by1)], ce),
        ("poly", [(0, 0), (bx1, by1), (bx1, by2), (0, FH)], lw),
        ("poly", [(FW, 0), (bx2, by1), (bx2, by2), (FW, FH)], rw),
        ("poly", [(bx1, by1), (bx2, by1), (bx2, by2), (bx1, by2)], bw),
    ]


lying = room(150, 60, 490, 230) + [
    ("poly", [(120, 300), (170, 268), (300, 262), (410, 270), (470, 292), (470, 318), (380, 330), (230, 334), (130, 328)], 186),
    ("ellipse", (462, 270, 512, 316), 176),
    ("poly", [(170, 296), (130, 262), (142, 254), (184, 286)], 170),
    ("poly", [(330, 190), (520, 190), (600, 280), (420, 280)], 132),
]
sitting = room(140, 50, 500, 220) + [
    ("poly", [(250, 150), (330, 150), (338, 300), (244, 300)], 176),
    ("ellipse", (262, 104, 318, 160), 182),
    ("poly", [(244, 286), (338, 286), (420, 300), (430, 330), (250, 330)], 168),
    ("poly", [(250, 170), (222, 250), (236, 256), (262, 186)], 170),
    ("poly", [(330, 170), (356, 250), (342, 256), (318, 186)], 170),
    ("poly", [(440, 140), (560, 120), (560, 300), (440, 290)], 58),
]
debris = room(130, 60, 510, 230, fl=84) + [
    ("poly", [(160, 300), (260, 280), (330, 286), (360, 304), (340, 326), (200, 330)], 170),
    ("poly", [(120, 250), (420, 196), (470, 236), (170, 310)], 70),
    ("poly", [(300, 230), (560, 260), (540, 300), (290, 270)], 54),
    ("poly", [(140, 330), (200, 300), (230, 360), (150, 380)], 62),
    ("poly", [(80, 120), (200, 90), (210, 120), (90, 150)], 66),
]
for seed, (name, polys, light) in enumerate((("lying", lying, (320, 280, 200)), ("sitting", sitting, (290, 200, 190)), ("debris", debris, (300, 280, 210)))):
    render(seed, polys, light).save(f"{OUT}/person-{name}.png")
print("ok")
