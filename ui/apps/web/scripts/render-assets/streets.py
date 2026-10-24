"""Neighborhood street map for the address-selection screen."""
import random, sys
from PIL import Image, ImageDraw

random.seed(4)
OUT = sys.argv[1]
K = 2
W, H = 968, 848
img = Image.new("RGB", (W * K, H * K), (240, 240, 238))
d = ImageDraw.Draw(img)

# park + creek for texture
d.rectangle([0, 0, 260 * K, 230 * K], fill=(226, 234, 222))
d.line([(0, 600 * K), (300 * K, 640 * K), (520 * K, 760 * K), (620 * K, 848 * K)], fill=(206, 222, 232), width=18 * K)

cols = [0, 150, 330, 510, 690, 870, 1040]
rows = [0, 140, 300, 470, 640, 810, 990]
road = (255, 255, 255)
for x in cols:
    d.rectangle([(x - 7) * K, 0, (x + 7) * K, H * K], fill=road)
for y in rows:
    d.rectangle([0, (y - 7) * K, W * K, (y + 7) * K], fill=road)
# arterial
d.rectangle([(510 - 11) * K, 0, (510 + 11) * K, H * K], fill=(255, 236, 214))

target = None
for i in range(len(cols) - 1):
    for j in range(len(rows) - 1):
        x1, x2 = cols[i] + 14, cols[i + 1] - 14
        y1, y2 = rows[j] + 14, rows[j + 1] - 14
        if x2 < 270 and y2 < 240:
            continue
        lots = max(3, (x2 - x1) // 34)
        lw = (x2 - x1) / lots
        for row, (ry1, ry2) in enumerate(((y1, y1 + (y2 - y1) / 2 - 4), (y1 + (y2 - y1) / 2 + 4, y2))):
            for k in range(lots):
                lx1 = x1 + k * lw + 2
                lx2 = lx1 + lw - 4
                bw = lw * random.uniform(0.5, 0.75)
                bh = (ry2 - ry1) * random.uniform(0.4, 0.6)
                bx = lx1 + (lw - 4 - bw) / 2
                by = ry1 + 6 if row == 0 else ry2 - 6 - bh
                fill = (218, 218, 214)
                if i == 2 and j == 2 and row == 1 and k == 2:
                    target = (lx1, ry1, lx2, ry2, bx, by, bw, bh)
                    continue
                d.rectangle([bx * K, by * K, (bx + bw) * K, (by + bh) * K], fill=fill, outline=(200, 200, 196), width=K)

lx1, ry1, lx2, ry2, bx, by, bw, bh = target
d.rectangle([lx1 * K, ry1 * K, lx2 * K, ry2 * K], fill=(255, 236, 226), outline=(255, 90, 31), width=2 * K)
d.rectangle([bx * K, by * K, (bx + bw) * K, (by + bh) * K], fill=(255, 140, 92), outline=(194, 65, 12), width=2 * K)
img.save(f"{OUT}/streets.png")
print("target lot", [round(v) for v in target])
