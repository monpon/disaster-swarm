"""Top-down prior floor plan (from listing) for mission setup."""
import math, sys
from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1]
K = 2
W, H = 1019, 848
S, OX, OY = 55, 125, 150


def p(x, y):
    return ((OX + x * S) * K, (OY + y * S) * K)


img = Image.new("RGBA", (W * K, H * K), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

sectors = [((0, 0, 6.5, 5.1), (255, 90, 31, 26)), ((0, 5.1, 5.2, 9.5), (255, 90, 31, 14)),
           ((6.5, 0, 14, 5.1), (21, 21, 21, 10)), ((5.2, 5.1, 9.8, 9.5), (21, 21, 21, 18))]
for (x1, y1, x2, y2), c in sectors:
    d.rectangle([p(x1, y1), p(x2, y2)], fill=c)
# no-fly garage hatch, clipped to the garage
hatch = Image.new("RGBA", img.size, (0, 0, 0, 0))
hd = ImageDraw.Draw(hatch)
hd.rectangle([p(9.8, 5.1), p(14, 9.5)], fill=(217, 45, 32, 16))
for i in range(-20, 40):
    hd.line([p(9.8 + i * 0.35, 5.1), p(9.8 + i * 0.35 - 4.4, 9.5)], fill=(217, 45, 32, 80), width=2)
mask = Image.new("L", img.size, 0)
ImageDraw.Draw(mask).rectangle([p(9.8, 5.1), p(14, 9.5)], fill=255)
img.paste(hatch, (0, 0), Image.composite(hatch, Image.new("RGBA", img.size), mask).split()[3])
d = ImageDraw.Draw(img)

ext = 0.22 * S * K
intw = 0.12 * S * K
walls_ext = [(0, 0, 8.0, 0), (9.0, 0, 14, 0), (0, 0, 0, 9.5), (0, 9.5, 7.0, 9.5), (8.0, 9.5, 14, 9.5), (14, 0, 14, 9.5)]
walls_int = [(6.5, 0, 6.5, 1.4), (6.5, 2.4, 6.5, 4.0), (6.5, 3.5, 8.0, 3.5), (9.2, 3.5, 10.7, 3.5), (10.7, 0, 10.7, 3.5),
             (10.7, 3.5, 11.5, 3.5), (12.4, 3.5, 14, 3.5), (0, 5.1, 4.0, 5.1), (5.0, 5.1, 6.8, 5.1), (5.2, 5.1, 5.2, 9.5),
             (6.8, 5.1, 6.8, 7.4), (8.0, 5.1, 8.0, 7.4), (8.0, 5.1, 9.8, 5.1), (5.2, 7.4, 6.8, 7.4), (8.0, 7.4, 9.8, 7.4),
             (9.8, 5.1, 9.8, 9.5), (9.8, 5.1, 11.0, 5.1), (12.0, 5.1, 14, 5.1)]
for x1, y1, x2, y2 in walls_ext:
    d.line([p(x1, y1), p(x2, y2)], fill=(30, 30, 30, 255), width=int(ext))
for x1, y1, x2, y2 in walls_int:
    d.line([p(x1, y1), p(x2, y2)], fill=(45, 45, 45, 255), width=int(intw))


def arc(cx, cy, r, a0, a1, leaf):
    bb = [p(cx - r, cy - r), p(cx + r, cy + r)]
    d.arc([bb[0][0], bb[0][1], bb[1][0], bb[1][1]], a0, a1, fill=(120, 120, 116, 255), width=2)
    lx, ly = leaf
    d.line([p(cx, cy), p(lx, ly)], fill=(45, 45, 45, 255), width=3)


arc(7.0, 9.5, 1.0, 270, 360, (7.0, 8.5))     # front door
arc(8.0, 0.0, 1.0, 90, 180, (8.0, 1.0))      # back door (Entry B)
arc(4.0, 5.1, 1.0, 0, 90, (5.0, 5.1))        # bedroom
arc(11.0, 5.1, 1.0, 0, 90, (12.0, 5.1))      # garage
arc(11.5, 3.5, 0.9, 270, 360, (11.5, 2.6))   # den
# stairs
for i in range(11):
    d.line([p(8.0, 5.1 + i * 0.21), p(9.8, 5.1 + i * 0.21)], fill=(110, 110, 106, 255), width=2)
# furniture (light)
furn = [(0.5, 0.4, 3.4, 1.3), (2.0, 2.4, 3.2, 3.2), (7.0, 0.15, 10.5, 0.7), (7.6, 1.5, 9.4, 2.3), (0.4, 6.6, 2.4, 8.8),
        (4.3, 8.6, 5.0, 9.3), (5.4, 5.3, 6.0, 6.6)]
for x1, y1, x2, y2 in furn:
    d.rectangle([p(x1, y1), p(x2, y2)], outline=(150, 150, 146, 255), width=2)

try:
    f = ImageFont.truetype("/usr/share/fonts/TTF/IBMPlexSans-Medium.ttf", 13 * K)
except Exception:
    f = ImageFont.load_default(size=13 * K)
labels = [("Living room", 3.2, 3.9), ("Kitchen", 8.6, 2.9), ("Den", 12.3, 1.6), ("Hallway", 10.6, 4.3),
          ("Bedroom 1", 2.6, 6.0), ("Bath", 6.0, 7.0), ("Stairs", 8.9, 7.8), ("Entry", 7.4, 8.4), ("Garage", 11.9, 7.3)]
for t, x, y in []:
    tw = d.textlength(t, font=f)
    X, Y = p(x, y)
    d.text((X - tw / 2, Y - 8 * K), t, font=f, fill=(92, 92, 89, 255))
img.save(f"{OUT}/plan.png")
print("ok")
