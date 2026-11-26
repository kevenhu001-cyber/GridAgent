"""Generate application assets from the approved GridAgent artwork; never redraw it."""
import sys
from pathlib import Path

from PIL import Image

SOURCE = Path(__file__).resolve().parents[1] / "branding" / "gridagent-logo.webp"


def main():
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as opened:
        original = opened.convert("RGB")
    original.save(target / "GridAgent-logo.png")
    # Crop the original continuous surface, excluding the wordmark.
    w, h = original.size
    mark = original.crop(tuple(round(v * scale / 1248) for v, scale in zip(
        (150, 180, 1100, 820), (w, h, w, h))))
    mark.thumbnail((232, 232), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (256, 256), (247, 247, 247))
    canvas.paste(mark, ((256 - mark.width) // 2, (256 - mark.height) // 2))
    canvas.save(target / "GridAgent-symbol.png")
    canvas.save(target / "GridAgent.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    for name, size in (("StoreLogo", 50), ("Square44x44Logo", 44), ("Square150x150Logo", 150)):
        canvas.resize((size, size), Image.Resampling.LANCZOS).save(target / f"{name}.png")


if __name__ == "__main__":
    main()
