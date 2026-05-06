"""
Run once to generate placeholder .ico files in assets/.
Requires Pillow:  pip install Pillow
"""
from pathlib import Path
from PIL import Image, ImageDraw

ASSETS = Path(__file__).parent / "assets"
ASSETS.mkdir(exist_ok=True)

SIZE = 64

def mic_shape(draw, colour, alpha=255):
    r, g, b = tuple(int(colour.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
    fill = (r, g, b, alpha)
    outline = (max(r-40,0), max(g-40,0), max(b-40,0), alpha)
    # Mic body (rounded rect)
    draw.rounded_rectangle([22, 4, 42, 36], radius=10, fill=fill, outline=outline, width=2)
    # Stand arc
    draw.arc([14, 20, 50, 50], start=0, end=180, fill=fill, width=3)
    # Stem
    draw.line([32, 50, 32, 58], fill=fill, width=3)
    # Base
    draw.line([24, 58, 40, 58], fill=fill, width=3)

ICONS = {
    "icon_idle.ico":          ("#888888", 255),
    "icon_recording.ico":     ("#cc0000", 255),
    "icon_recording_alt.ico": ("#ff8888", 200),
    "icon_paused.ico":        ("#ccaa00", 255),
}

for filename, (colour, alpha) in ICONS.items():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    mic_shape(draw, colour, alpha)
    out = ASSETS / filename
    img.save(str(out), format="ICO", sizes=[(64,64),(32,32),(16,16)])
    print(f"  Wrote {out}")

print("Done.")
