#!/usr/bin/env python3
"""The social share cards (owner order, 2026-11-08).

Two designed 1200x630 Open Graph cards, composed from the
site's own brand assets — no clipart, nothing redrawn:

  public/brand/og-card.png       the site-wide default card:
                                 the logo WITH TEXT (the steel +
                                 orange wordmark) over a deep
                                 steel-navy ground, the slogan
                                 under an orange rule.
  public/brand/og-downloads.png  the Downloads page's variant,
                                 same design language: wordmark,
                                 a FREE DOWNLOADS headline, the
                                 coverage line, the slogan.

Why cards at all: the old og:image was the square badge art
(logo-official.webp, 1024x1024), which share renderers center-
crop into the 1200x630 frame — a zoomed, cropped wrench mess
with the generic title. These cards are composed AT the share
frame's own aspect, so what a publisher sees is what a reader
gets.

The wordmark is the plates-free "logo with text" (brand
vocabulary: the corner-plated badge is the Apple app icon's
alone, and never appears here).

Regenerate (needs Pillow) after any wordmark or palette
change; if the art changes, ship under a NEW filename (the
/brand/ path is immutable-cached) and update index.html +
vite.config.ts in the same commit:

    python3 scripts/make-og-cards.py
"""

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
BRAND = HERE.parent / "public" / "brand"
WORDMARK = BRAND / "wordmark-840.webp"

W, H = 1200, 630

# The site palette, sampled from the themes: deep steel ground,
# the light theme's navy ink as the glow, the silver accent
# (#c7ccd4) for the slogan, brand orange for the rule.
GROUND_TOP = (10, 13, 18)
GROUND_BOTTOM = (16, 22, 31)
GLOW = (29, 44, 71)
SILVER = (199, 204, 212)
WHITE = (242, 245, 249)
MUTED = (138, 155, 178)
ORANGE = (255, 106, 0)
FRAME = (214, 221, 232, 38)

FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def ground() -> Image.Image:
    """Vertical steel gradient + a navy radial glow behind the
    center + a whisper of brushed noise, corners vignetted."""
    img = Image.new("RGB", (W, H), GROUND_TOP)
    px = img.load()
    for y in range(H):
        t = y / (H - 1)
        row = tuple(
            round(GROUND_TOP[i] + (GROUND_BOTTOM[i] - GROUND_TOP[i]) * t)
            for i in range(3)
        )
        for x in range(W):
            px[x, y] = row
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-260, -190, W + 260, H + 130], fill=GLOW)
    glow = glow.filter(ImageFilter.GaussianBlur(190))
    # Lay the glow over the gradient, clamped.
    import numpy as np

    base = np.asarray(img).astype(np.int16)
    glow_arr = np.asarray(glow).astype(np.int16)
    img = Image.fromarray(
        np.clip(base + glow_arr - 24, 0, 255).astype("uint8"), "RGB"
    )
    # Brushed noise: seeded, faint, horizontally smeared.
    rng = random.Random(20261108)
    noise = Image.new("L", (W, H))
    npx = noise.load()
    for y in range(H):
        for x in range(W):
            npx[x, y] = 128 + rng.randint(-7, 7)
    noise = noise.resize((W // 6, H)).resize((W, H))
    img = Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.035)
    # Vignette.
    vig = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-W // 3, -H // 3, W + W // 3, H + H // 3], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(160))
    dark = Image.new("RGB", (W, H), (4, 5, 8))
    img = Image.composite(img, dark, vig.point(lambda v: 205 + v // 5))
    return img.convert("RGBA")


def draw_tracked(draw, cx, y, text, font, tracking, fill):
    """Draw text centered at cx with letter tracking (px)."""
    widths = []
    for ch in text:
        box = draw.textbbox((0, 0), ch, font=font)
        widths.append(box[2] - box[0])
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + tracking
    return total


def frame(img):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([30, 30, W - 30, H - 30], radius=18, outline=FRAME, width=2)
    return d


def wordmark(img, width, cy):
    wm = Image.open(WORDMARK).convert("RGBA")
    height = round(width * wm.height / wm.width)
    wm = wm.resize((width, height), Image.LANCZOS)
    img.alpha_composite(wm, (round((W - width) / 2), round(cy - height / 2)))
    return height


def site_card() -> Image.Image:
    img = ground()
    d = frame(img)
    wordmark(img, 900, 252)
    d = ImageDraw.Draw(img)
    d.rectangle([W / 2 - 36, 348, W / 2 + 36, 353], fill=ORANGE + (255,))
    slogan = ImageFont.truetype(FONT_BOLD, 37)
    draw_tracked(d, W / 2, 382, "ORGANIZE. PROTECT. RECOVER.", slogan, 7, SILVER + (255,))
    small = ImageFont.truetype(FONT_BOLD, 23)
    draw_tracked(d, W / 2, 540, "TOOLBOXVAULT.COM", small, 5, MUTED + (255,))
    return img.convert("RGB")


def downloads_card() -> Image.Image:
    img = ground()
    frame(img)
    wordmark(img, 720, 148)
    d = ImageDraw.Draw(img)
    headline = ImageFont.truetype(FONT_BOLD, 96)
    draw_tracked(d, W / 2, 252, "FREE DOWNLOADS", headline, 2, WHITE + (255,))
    cover = ImageFont.truetype(FONT_BOLD, 28)
    draw_tracked(
        d,
        W / 2,
        392,
        "Free documents  ·  a built-in converter  ·  member-shared 3D print files",
        cover,
        1,
        (168, 182, 203, 255),
    )
    d.rectangle([W / 2 - 30, 486, W / 2 + 30, 490], fill=ORANGE + (255,))
    slogan = ImageFont.truetype(FONT_BOLD, 25)
    draw_tracked(d, W / 2, 512, "ORGANIZE. PROTECT. RECOVER.", slogan, 6, SILVER + (255,))
    return img.convert("RGB")


def main():
    site_card().save(BRAND / "og-card.png", optimize=True)
    downloads_card().save(BRAND / "og-downloads.png", optimize=True)
    print("wrote", BRAND / "og-card.png", "and", BRAND / "og-downloads.png")


if __name__ == "__main__":
    main()
