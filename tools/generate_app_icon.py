"""Render Astra's original vector emblem into Windows multi-resolution icons."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "assets" / "branding"
    output.mkdir(parents=True, exist_ok=True)
    size = 1024
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 28, 996, 996), radius=220, fill="#141a30", outline="#7465c8", width=18)
    draw.ellipse((130, 130, 894, 894), fill="#222a48")
    draw.polygon([(512, 180), (800, 800), (647, 800), (512, 484), (377, 800), (224, 800)], fill="#b7a1ff")
    draw.polygon([(399, 638), (625, 638), (669, 736), (355, 736)], fill="#65e4e4")
    draw.polygon([(775, 138), (800, 207), (870, 232), (800, 257), (775, 326), (750, 257), (680, 232), (750, 207)], fill="#81f4ec")
    image.save(output / "astra.png")
    image.save(output / "astra.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    (output / "astra.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><rect x="28" y="28" width="968" height="968" rx="220" fill="#141a30" stroke="#7465c8" stroke-width="18"/><circle cx="512" cy="512" r="382" fill="#222a48"/><path d="M512 180 800 800H647L512 484 377 800H224Z" fill="#b7a1ff"/><path d="M399 638H625L669 736H355Z" fill="#65e4e4"/><path d="M775 138 800 207 870 232 800 257 775 326 750 257 680 232 750 207Z" fill="#81f4ec"/></svg>', encoding="utf-8")
    print(output / "astra.ico")


if __name__ == "__main__":
    main()
