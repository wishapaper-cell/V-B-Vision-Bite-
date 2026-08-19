"""Generate a standalone V/B glass-ribbon monogram concept preview."""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "vb-monogram-glow-v5.png"


def gradient(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)
    top = (247, 255, 252)
    bottom = (210, 244, 232)
    for y in range(size):
        mix = y / (size - 1)
        color = tuple(round(a + (b - a) * mix) for a, b in zip(top, bottom)) + (255,)
        draw.line((0, y, size, y), fill=color)
    return image


def round_cap(draw: ImageDraw.ImageDraw, point: tuple[int, int], width: int, fill: int) -> None:
    radius = width // 2
    draw.ellipse((point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius), fill=fill)


def draw_monogram_mask(size: int, width: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)

    # The rounded end of the V overlaps the B spine, creating a soft fused
    # junction without the hard horizontal shoulder used in the prior draft.
    v_points = [(425, 580), (900, 1480), (1185, 565)]
    draw.line(v_points, fill=255, width=width, joint="curve")
    for point in v_points:
        round_cap(draw, point, width, 255)

    # B spine and two fuller, circular bowls.
    draw.line((1230, 500, 1230, 1545), fill=255, width=width)
    round_cap(draw, (1230, 1545), width, 255)
    top_box = (860, 500, 1600, 1030)
    bottom_box = (805, 1030, 1655, 1570)
    draw.arc(top_box, start=270, end=450, fill=255, width=width)
    draw.arc(bottom_box, start=270, end=450, fill=255, width=width)
    for point in ((1230, 1030), (1230, 1030), (1230, 1570)):
        round_cap(draw, point, width, 255)
    return mask


def main() -> None:
    size = 2048
    canvas = gradient(size)

    atmosphere = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    glow = ImageDraw.Draw(atmosphere)
    glow.ellipse((-180, -100, 1260, 1320), fill=(127, 224, 190, 62))
    glow.ellipse((1040, 760, 2320, 2100), fill=(62, 179, 149, 42))
    canvas.alpha_composite(atmosphere.filter(ImageFilter.GaussianBlur(170)))

    # Restrained glass bubble, used as a stage rather than another symbol.
    bubble = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    bubble_draw = ImageDraw.Draw(bubble)
    bubble_draw.ellipse((300, 280, 1748, 1728), fill=(248, 255, 252, 116), outline=(255, 255, 255, 210), width=12)
    bubble_draw.arc((326, 306, 1722, 1702), 202, 342, fill=(63, 177, 141, 38), width=18)
    bubble_draw.arc((326, 306, 1722, 1702), 22, 162, fill=(255, 255, 255, 178), width=15)
    canvas.alpha_composite(bubble)

    mask = draw_monogram_mask(size, 156)
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_alpha = mask.filter(ImageFilter.GaussianBlur(48))
    shadow.paste((18, 105, 78, 42), (0, 24), shadow_alpha)
    canvas.alpha_composite(shadow)

    edge_softness = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    edge_softness_alpha = mask.filter(ImageFilter.GaussianBlur(18))
    edge_softness.paste((119, 219, 185, 30), (0, 0), edge_softness_alpha)
    canvas.alpha_composite(edge_softness)

    # A restrained pale-mint outer keyline keeps the monogram crisp without
    # reintroducing the busy internal highlight from earlier drafts.
    expanded_mask = mask.filter(ImageFilter.MaxFilter(25))
    outline_mask = ImageChops.subtract(expanded_mask, mask)
    outline = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    outline.paste((207, 246, 233, 216), (0, 0), outline_mask)
    canvas.alpha_composite(outline)

    ribbon = Image.new("RGBA", canvas.size)
    ribbon_draw = ImageDraw.Draw(ribbon)
    for y in range(size):
        mix = y / (size - 1)
        color = (
            round(39 + (76 - 39) * mix),
            round(142 + (191 - 142) * mix),
            round(108 + (154 - 108) * mix),
            228,
        )
        ribbon_draw.line((0, y, size, y), fill=color)
    ribbon.putalpha(mask.point(lambda value: round(value * 0.91)))
    canvas.alpha_composite(ribbon)

    # A narrow luminous centre line adds a restrained glass-tube character.
    line_halo_mask = draw_monogram_mask(size, 22).filter(ImageFilter.GaussianBlur(18))
    line_halo = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    line_halo.paste((235, 255, 248, 86), (0, 0), line_halo_mask)
    canvas.alpha_composite(line_halo)

    line_core_mask = draw_monogram_mask(size, 10)
    line_core = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    line_core.paste((244, 255, 251, 142), (0, 0), line_core_mask)
    canvas.alpha_composite(line_core)

    # Minimal bubbles reference nutrition and balance without adding literal icons.
    detail = ImageDraw.Draw(canvas)
    detail.ellipse((1560, 340, 1610, 390), fill=(255, 255, 255, 145), outline=(65, 182, 145, 84), width=4)
    detail.ellipse((1640, 420, 1675, 455), fill=(255, 255, 255, 108))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.resize((1024, 1024), Image.Resampling.LANCZOS).convert("RGB").save(OUTPUT, quality=96)


if __name__ == "__main__":
    main()
