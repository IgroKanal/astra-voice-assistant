"""Create subtle full-body speaking frames on top of the approved portrait faces."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
AVATARS = ROOT / "assets" / "avatars"
BASES = (
    "full_female.png",
    "full_female_saya.png",
    "full_male.png",
    "full_male_kai.png",
)
MOUTH = (497, 204, 528, 229)


def open_mouth_layer(size: tuple[int, int]) -> Image.Image:
    scale = 4
    layer = Image.new("RGBA", (size[0] * scale, size[1] * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    box = tuple(value * scale for value in (*MOUTH,))
    draw.ellipse(box, fill=(65, 24, 34, 245))
    inner = (MOUTH[0] + 5, MOUTH[1] + 6, MOUTH[2] - 5, MOUTH[3] - 4)
    draw.ellipse(tuple(value * scale for value in inner), fill=(128, 42, 56, 255))
    tongue = (MOUTH[0] + 9, MOUTH[1] + 18, MOUTH[2] - 9, MOUTH[3] - 2)
    draw.ellipse(tuple(value * scale for value in tongue), fill=(198, 95, 105, 245))
    upper = (MOUTH[0] + 3, MOUTH[1] - 1, MOUTH[2] - 3, MOUTH[1] + 8)
    draw.arc(tuple(value * scale for value in upper), 180, 360, fill=(39, 22, 28, 220), width=3 * scale)
    return layer.resize(size, Image.Resampling.LANCZOS)


def main() -> None:
    layer = open_mouth_layer((1024, 1536))
    for base_name in BASES:
        image = Image.open(AVATARS / base_name).convert("RGBA")
        image.alpha_composite(layer)
        output_name = base_name.removesuffix(".png") + "_speaking.png"
        image.save(AVATARS / output_name, optimize=True)
        print("Generated " + output_name)


if __name__ == "__main__":
    main()
