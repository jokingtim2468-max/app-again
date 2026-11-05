"""Render the Tickbench app icon (build/icon.png + build/icon.ico) from the logo geometry."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "build"
S = 1024
BG = (15, 18, 20, 255)
AMBER = (242, 169, 59, 255)


def render(size: int = S) -> Image.Image:
    k = size / 22.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0.6 * k, 0.6 * k, 21.4 * k, 21.4 * k], radius=5.5 * k, fill=BG, outline=AMBER, width=max(2, int(0.9 * k)))
    pts = [(5 * k, 14.5 * k), (8.2 * k, 11 * k), (10.6 * k, 13.2 * k), (16.8 * k, 7 * k)]
    d.line(pts, fill=AMBER, width=int(1.9 * k), joint="curve")
    r = 0.95 * k
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=AMBER)
    d.line([(5 * k, 17 * k), (17 * k, 17 * k)], fill=(242, 169, 59, 130), width=int(1.2 * k))
    return img


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    big = render()
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png")
    big.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT / "icon.png", OUT / "icon.ico")
