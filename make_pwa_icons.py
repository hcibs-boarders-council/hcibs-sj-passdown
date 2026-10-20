
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
SOURCE_LOGO = BASE_DIR / "static" / "img" / "logo.jpeg"
OUTPUT_DIR = BASE_DIR / "static" / "img"


def main():
    print("Starting PWA icon generation...")

    if not SOURCE_LOGO.exists():
        print(f"ERROR: Logo not found at {SOURCE_LOGO}")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Image.open(SOURCE_LOGO) as original:
        print(f"Original logo: {original.format}, {original.size}")

        logo = original.convert("RGBA")

        for size in (192, 512):
            icon = logo.resize(
                (size, size),
                Image.Resampling.LANCZOS,
            )

            output_path = OUTPUT_DIR / f"logo-{size}.png"
            icon.save(output_path, format="PNG")

            print(f"Created {output_path.name}: {icon.size}")

    print("PWA icon generation complete!")


if __name__ == "__main__":
    main()
