"""Synchronize the approved V&B glow monogram across all app platforms."""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
MASTER_SIZE = 1024
APPROVED_MASTER = ROOT / "assets" / "vb-monogram-glow-v5.png"
APPROVED_VECTOR = ROOT / "assets" / "vb-monogram-glow-v5.svg"


def linear_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)
    for y in range(size):
        mix = y / max(1, size - 1)
        color = tuple(round(a + (b - a) * mix) for a, b in zip(top, bottom)) + (255,)
        draw.line((0, y, size, y), fill=color)
    return image


def rounded_mask(size: int, inset: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, size - inset, size - inset), radius=radius, fill=255
    )
    return mask


def rounded_arc(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    start: float,
    end: float,
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    draw.arc(box, start=start, end=end, fill=color, width=width)
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    rx = (box[2] - box[0]) / 2
    ry = (box[3] - box[1]) / 2
    cap = width / 2
    for angle in (start, end):
        radians = math.radians(angle)
        x = cx + rx * math.cos(radians)
        y = cy + ry * math.sin(radians)
        draw.ellipse((x - cap, y - cap, x + cap, y + cap), fill=color)


def draw_nutrition_eye(layer: Image.Image, center: tuple[int, int], radius: int) -> None:
    """Draw a plate/lens, three nutrient arcs and a leaf-shaped pupil."""
    cx, cy = center
    symbol = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(symbol)

    # Lens/plate halo and inner glass pupil.
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(238, 255, 248, 44),
        outline=(255, 255, 255, 174),
        width=max(5, radius // 34),
    )
    ring_radius = round(radius * 0.67)
    ring_width = round(radius * 0.24)
    ring_box = (cx - ring_radius, cy - ring_radius, cx + ring_radius, cy + ring_radius)

    # Protein, carbohydrate and fat balance, rendered like a camera aperture.
    rounded_arc(draw, ring_box, 202, 302, (31, 151, 108, 224), ring_width)
    rounded_arc(draw, ring_box, 322, 422, (66, 183, 163, 210), ring_width)
    rounded_arc(draw, ring_box, 82, 182, (112, 203, 171, 194), ring_width)

    pupil_radius = round(radius * 0.29)
    draw.ellipse(
        (cx - pupil_radius, cy - pupil_radius, cx + pupil_radius, cy + pupil_radius),
        fill=(249, 255, 252, 206),
        outline=(255, 255, 255, 224),
        width=max(4, radius // 42),
    )

    # Leaf pupil: food, health and the act of visually recognizing a meal.
    leaf_w = round(radius * 0.68)
    leaf_h = round(radius * 0.42)
    shift = round(leaf_w * 0.12)
    leaf_size = (leaf_w + shift + 80, leaf_h + 80)
    mask_a = Image.new("L", leaf_size, 0)
    mask_b = Image.new("L", leaf_size, 0)
    ImageDraw.Draw(mask_a).ellipse((30, 30, 30 + leaf_w, 30 + leaf_h), fill=255)
    ImageDraw.Draw(mask_b).ellipse((30 + shift, 30, 30 + shift + leaf_w, 30 + leaf_h), fill=255)
    leaf_mask = ImageChops.multiply(mask_a, mask_b)
    leaf = Image.new("RGBA", leaf_size, (0, 0, 0, 0))
    leaf.paste((35, 133, 94, 232), (0, 0), leaf_mask)
    leaf_draw = ImageDraw.Draw(leaf)
    leaf_draw.line(
        (44 + shift, 30 + leaf_h // 2, 18 + leaf_w, 30 + leaf_h // 2),
        fill=(218, 255, 239, 218),
        width=max(5, radius // 34),
    )
    leaf = leaf.rotate(-35, resample=Image.Resampling.BICUBIC, expand=True)
    symbol.alpha_composite(leaf, (cx - leaf.width // 2, cy - leaf.height // 2))

    # Small recognition glint.
    glint = round(radius * 0.075)
    gx, gy = cx + round(radius * 0.63), cy - round(radius * 0.62)
    draw.line((gx - glint, gy, gx + glint, gy), fill=(255, 255, 255, 216), width=max(3, radius // 50))
    draw.line((gx, gy - glint, gx, gy + glint), fill=(255, 255, 255, 216), width=max(3, radius // 50))

    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow_alpha = symbol.getchannel("A").filter(ImageFilter.GaussianBlur(max(5, radius // 18)))
    shadow.paste((17, 110, 81, 30), (0, max(4, radius // 20)), shadow_alpha)
    layer.alpha_composite(shadow)
    layer.alpha_composite(symbol)


def render_master() -> Image.Image:
    if not APPROVED_MASTER.exists():
        raise FileNotFoundError(f"Approved icon master not found: {APPROVED_MASTER}")
    with Image.open(APPROVED_MASTER) as approved:
        return approved.convert("RGBA").resize((MASTER_SIZE, MASTER_SIZE), Image.Resampling.LANCZOS)

    # Legacy nutrition-lens renderer retained below for reference only.
    scale = 2
    size = MASTER_SIZE * scale
    # Fill the complete square so no dark/transparent fringe can appear in launchers.
    canvas = linear_gradient(size, (246, 255, 251), (211, 244, 231))

    atmosphere = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    atmosphere_draw = ImageDraw.Draw(atmosphere)
    atmosphere_draw.ellipse((-180, -150, 1300, 1320), fill=(150, 230, 202, 66))
    atmosphere_draw.ellipse((1040, 820, 2300, 2080), fill=(74, 192, 157, 42))
    atmosphere = atmosphere.filter(ImageFilter.GaussianBlur(175))
    canvas.alpha_composite(atmosphere)

    draw = ImageDraw.Draw(canvas)
    # A very light internal frame keeps definition without creating a dark outer border.
    draw.rounded_rectangle(
        (28, 28, size - 28, size - 28),
        radius=390,
        outline=(255, 255, 255, 132),
        width=8,
    )

    # Central glass bubble: soft halo, translucent body, inner shade and glossy highlight.
    bubble_box = (390, 382, 1658, 1650)
    halo = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((354, 346, 1694, 1686), fill=(53, 178, 136, 58))
    halo = halo.filter(ImageFilter.GaussianBlur(80))
    canvas.alpha_composite(halo)
    bubble = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    bubble_draw = ImageDraw.Draw(bubble)
    bubble_draw.ellipse(bubble_box, fill=(236, 255, 248, 138), outline=(255, 255, 255, 205), width=12)
    bubble_draw.arc((410, 402, 1638, 1630), start=12, end=168, fill=(255, 255, 255, 185), width=16)
    bubble_draw.arc((426, 418, 1622, 1614), start=192, end=348, fill=(79, 182, 145, 52), width=18)
    canvas.alpha_composite(bubble)

    gloss = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    gloss_draw = ImageDraw.Draw(gloss)
    gloss_draw.ellipse((570, 480, 1110, 700), fill=(255, 255, 255, 104))
    gloss_draw.ellipse((1290, 650, 1430, 790), fill=(255, 255, 255, 86))
    gloss = gloss.filter(ImageFilter.GaussianBlur(42))
    canvas.alpha_composite(gloss)

    # Two light focus accents suggest visual recognition without enclosing the mark.
    accent = (53, 166, 127, 112)
    line_width = 18
    draw.line((214, 470, 214, 310, 374, 310), fill=accent, width=line_width, joint="curve")
    draw.line((size - 214, size - 470, size - 214, size - 310, size - 374, size - 310), fill=accent, width=line_width, joint="curve")

    nutrition_lens = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw_nutrition_eye(nutrition_lens, (size // 2, 1020), 488)
    canvas.alpha_composite(nutrition_lens)

    # Floating micro-bubbles reinforce the soft glass character.
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((size - 424, 250, size - 358, 316), fill=(255, 255, 255, 118), outline=(91, 195, 157, 82), width=4)
    draw.ellipse((size - 330, 354, size - 288, 396), fill=(255, 255, 255, 96))
    draw.ellipse((300, size - 386, 346, size - 340), fill=(255, 255, 255, 88))

    # Flatten the visual transparency onto the mint base so dark launcher themes
    # can never show through the icon, while the bubble still looks translucent.
    opaque = linear_gradient(size, (246, 255, 251), (211, 244, 231))
    opaque.alpha_composite(canvas)
    return opaque.resize((MASTER_SIZE, MASTER_SIZE), Image.Resampling.LANCZOS)


def render_adaptive_foreground() -> Image.Image:
    # Android adaptive icons need transparent padding around the foreground.
    # Crop the approved circular composition and place it inside the safe zone
    # so OEM launcher masks do not clip the V/B monogram.
    master = render_master().resize((360, 360), Image.Resampling.LANCZOS)
    crop_mask = Image.new("L", master.size, 0)
    ImageDraw.Draw(crop_mask).ellipse((1, 1, 358, 358), fill=255)
    master.putalpha(crop_mask)
    foreground = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
    foreground.alpha_composite(master, (36, 36))
    return foreground

    # Legacy adaptive renderer retained below for reference only.
    size = 432
    foreground = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bubble_draw = ImageDraw.Draw(foreground)
    bubble_draw.ellipse((86, 84, 346, 344), fill=(244, 255, 251, 152), outline=(255, 255, 255, 220), width=5)
    bubble_draw.arc((92, 90, 340, 338), start=15, end=165, fill=(255, 255, 255, 190), width=5)
    draw_nutrition_eye(foreground, (216, 214), 104)
    draw = ImageDraw.Draw(foreground)
    accent = (52, 166, 127, 112)
    draw.line((64, 146, 64, 108, 102, 108), fill=accent, width=5, joint="curve")
    draw.line((368, 286, 368, 324, 330, 324), fill=accent, width=5, joint="curve")
    return foreground


def main() -> None:
    master = render_master()
    outputs = [ROOT / "static" / "brand", ROOT / "health_diet_app" / "static" / "brand"]
    for output in outputs:
        output.mkdir(parents=True, exist_ok=True)
        master.save(output / "vb-icon-1024.png", optimize=True)
        master.resize((192, 192), Image.Resampling.LANCZOS).save(output / "vb-icon-192.png", optimize=True)
        master.resize((32, 32), Image.Resampling.LANCZOS).save(output / "favicon-32.png", optimize=True)
        master.resize((16, 16), Image.Resampling.LANCZOS).save(output / "favicon-16.png", optimize=True)
        shutil.copyfile(APPROVED_VECTOR, output / "vb-icon.svg")

    android_res = ROOT / "health_diet_app" / "android" / "app" / "src" / "main" / "res"
    for density, pixels in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
        folder = android_res / f"mipmap-{density}"
        folder.mkdir(parents=True, exist_ok=True)
        master.resize((pixels, pixels), Image.Resampling.LANCZOS).save(folder / "ic_launcher.png", optimize=True)
        master.resize((pixels, pixels), Image.Resampling.LANCZOS).save(folder / "ic_launcher_round.png", optimize=True)

    foreground_dir = android_res / "drawable-nodpi"
    foreground_dir.mkdir(parents=True, exist_ok=True)
    render_adaptive_foreground().save(foreground_dir / "ic_launcher_foreground.png", optimize=True)

    icon_dir = ROOT / "assets"
    icon_dir.mkdir(parents=True, exist_ok=True)
    master.save(icon_dir / "vb-app-icon.png", optimize=True)
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(icon_dir / "vb-app-glow-v5.ico", sizes=ico_sizes)
    master.save(icon_dir / "vb-app.ico", sizes=ico_sizes)


if __name__ == "__main__":
    main()
