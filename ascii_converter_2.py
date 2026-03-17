#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║           ASCII ART IMAGE SEQUENCE CONVERTER                  ║
║                    Polka Dot Post                             ║
╠═══════════════════════════════════════════════════════════════╣
║  INPUT : Folder of premultiplied RGBA PNGs (recommended)      ║
║          OR subject-on-black PNGs (set IS_PREMULTIPLIED=False)║
║  OUTPUT: Rendered ASCII PNG frames in ascii_output/ subdir    ║
╚═══════════════════════════════════════════════════════════════╝

USAGE (VS Code terminal):
  python ascii_converter.py /path/to/png/folder

  Or drag the folder from the file explorer into the terminal —
  it will paste the path. Then hit Enter.

DEPENDENCIES (run once):
  pip install Pillow numpy
"""

import sys
import os
import random
import glob
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
except ImportError:
    print("─" * 60)
    print("Missing dependencies. Install them by running:")
    print("  pip install Pillow numpy")
    print("─" * 60)
    sys.exit(1)


# ════════════════════════════════════════════════════════════
#  CONFIG  —  Everything you need to tweak is right here
# ════════════════════════════════════════════════════════════

# ── Cell size ────────────────────────────────────────────────
# How many source pixels map to one ASCII character.
# IMPORTANT: Most monospace fonts are ~2x taller than wide.
# Keep CELL_H ≈ 2 × CELL_W so the output isn't squashed.
# Smaller values = more detail, bigger output image.
CELL_W: int = 6
CELL_H: int = 12

# ── Font ─────────────────────────────────────────────────────
# Font size in points for the rendered output PNG.
FONT_SIZE: int = 12

# Path to a monospace .ttf / .otf font.
# Set to None to auto-detect from your system, or provide a path:
#   macOS  : "/Library/Fonts/Courier New.ttf"
#   Windows: "C:/Windows/Fonts/consola.ttf"
#   Linux  : "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_PATH: str | None = None

# ── Custom string scattering ─────────────────────────────────
# Strings whose characters will be randomly scattered through
# the subject. Add as many as you like.
CUSTOM_STRINGS: list[str] = ["BRAND", "PDP", "ASCII", "2026"]

# Probability that any given subject character is drawn from
# CUSTOM_STRINGS instead of the standard ASCII ramp.
#   0.0 = never  |  0.3 = nice mix  |  1.0 = only custom chars
CUSTOM_DENSITY: float = 0.5

# ── Output style ─────────────────────────────────────────────
# "white_on_black"  →  one output folder
# "black_on_white"  →  one output folder
# "colour"          →  one output folder (original pixel colours)
# "both"            →  white_on_black + black_on_white
# "all"             →  all three styles
STYLE: str = "all"

# ── Alpha settings ───────────────────────────────────────────
# Pixels with alpha below this value are treated as background.
# Range: 0–255. Lower = keep more semi-transparent edge pixels.
ALPHA_THRESHOLD: int = 30

# True  → your PNGs have premultiplied alpha (most VFX renders)
# False → subject on solid black background with no alpha channel
IS_PREMULTIPLIED: bool = True

# ── ASCII character ramp ──────────────────────────────────────
# Characters ordered from darkest/sparse to brightest/dense.
# Flip the string to invert the brightness relationship.
ASCII_RAMP: str = (
    " .'`^\",.:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
)

# ── Output ───────────────────────────────────────────────────
# Name of the subfolder created inside your input folder.
OUTPUT_FOLDER: str = "ascii_output"

# ════════════════════════════════════════════════════════════
#  INTERNALS — No need to edit below this line
# ════════════════════════════════════════════════════════════

RAMP_LEN: int = len(ASCII_RAMP)
# Stores whole strings (not individual chars) so "BRAND" is always placed intact.
_CUSTOM_POOL: list[str] = []


def _build_custom_pool() -> None:
    """
    Store each custom string as a whole unit.
    When scattering, a full string like "BRAND" is placed in consecutive
    cells rather than having H, & and M appear at random separate positions.
    """
    global _CUSTOM_POOL
    _CUSTOM_POOL = [s for s in CUSTOM_STRINGS if s]
    if not _CUSTOM_POOL:
        # Fallback: use the denser half of the ramp as single-char strings
        _CUSTOM_POOL = list(ASCII_RAMP[RAMP_LEN // 2:])


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Attempt to load a monospace TrueType font.
    Falls back to PIL's built-in bitmap default if none found.
    """
    candidates = []
    if FONT_PATH:
        candidates.append(FONT_PATH)

    candidates += [
        # macOS
        "/System/Library/Fonts/Menlo.ttc",
        "/Library/Fonts/Courier New.ttf",
        "/System/Library/Fonts/Monaco.ttf",
        # Windows
        "C:/Windows/Fonts/consola.ttf",      # Consolas
        "C:/Windows/Fonts/cour.ttf",          # Courier New
        "C:/Windows/Fonts/lucon.ttf",         # Lucida Console
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
    ]

    for path in candidates:
        if os.path.isfile(path):
            try:
                font = ImageFont.truetype(path, size)
                print(f"  Font loaded: {path}")
                return font
            except Exception:
                continue

    print("  ⚠  No monospace TTF found — using PIL bitmap default.")
    print("     For better output set FONT_PATH to a .ttf on your system.")
    return ImageFont.load_default()


def _get_char_size(
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[int, int]:
    """Return (char_width, char_height) for the loaded font."""
    probe = Image.new("RGB", (200, 60))
    draw = ImageDraw.Draw(probe)
    bbox = draw.textbbox((0, 0), "M", font=font)
    return (bbox[2] - bbox[0]), (bbox[3] - bbox[1])


def _unpremultiply(rgba: np.ndarray) -> np.ndarray:
    """
    Convert a premultiplied RGBA array to straight (unassociated) alpha.
    Pixels with alpha=0 are left as-is.
    """
    r, g, b, a = (rgba[..., i].astype(np.float32) for i in range(4))
    alpha_f = a / 255.0
    mask = alpha_f > 0
    out = rgba.astype(np.float32).copy()
    for ch in (r, g, b):
        pass  # iterate below
    for ch_idx in range(3):
        channel = out[..., ch_idx]
        channel[mask] = channel[mask] / alpha_f[mask]
        out[..., ch_idx] = channel
    return np.clip(out, 0, 255).astype(np.uint8)


def _image_to_ascii_grid(
    img: Image.Image,
) -> list[list[tuple[str, tuple[int, int, int]]]]:
    """
    Convert a PIL Image to a 2-D grid of (char, rgb) tuples.

    Each cell holds:
      char  — the ASCII character to render
      rgb   — the average colour of the source pixels in that cell
               (used by the "colour" style; ignored by mono styles)

    Custom strings (e.g. "BRAND") are emitted as whole consecutive units
    using a pending-character queue so they always appear intact.
    Background (low alpha) cells become (" ", (0, 0, 0)).
    """
    from collections import deque

    img_rgba = img.convert("RGBA")
    rgba = np.array(img_rgba)

    if IS_PREMULTIPLIED:
        rgba = _unpremultiply(rgba)

    h, w = rgba.shape[:2]
    cols = w // CELL_W
    rows = h // CELL_H

    grid: list[list[tuple[str, tuple[int, int, int]]]] = []

    for row_idx in range(rows):
        y0 = row_idx * CELL_H
        y1 = y0 + CELL_H
        row_cells: list[tuple[str, tuple[int, int, int]]] = []

        # Pending queue holds remaining chars of a partially-placed custom string.
        # Cleared whenever we hit a background cell so strings don't straddle gaps.
        pending: deque[str] = deque()

        for col_idx in range(cols):
            x0 = col_idx * CELL_W
            x1 = x0 + CELL_W
            cell = rgba[y0:y1, x0:x1]  # shape (CELL_H, CELL_W, 4)

            alpha_vals = cell[..., 3].astype(np.float32)
            mean_alpha = alpha_vals.mean()

            # ── Background ────────────────────────────────────
            if mean_alpha < ALPHA_THRESHOLD:
                pending.clear()  # don't let a string bleed across a gap
                row_cells.append((" ", (0, 0, 0)))
                continue

            # ── Average colour for this cell (straight alpha) ─
            alpha_w = alpha_vals / 255.0
            weight_sum = alpha_w.sum()
            if weight_sum > 0:
                avg_r = int((cell[..., 0].astype(np.float32) * alpha_w).sum() / weight_sum)
                avg_g = int((cell[..., 1].astype(np.float32) * alpha_w).sum() / weight_sum)
                avg_b = int((cell[..., 2].astype(np.float32) * alpha_w).sum() / weight_sum)
            else:
                avg_r = avg_g = avg_b = 0
            cell_colour: tuple[int, int, int] = (
                min(255, avg_r), min(255, avg_g), min(255, avg_b)
            )

            # ── Brightness (alpha-weighted luminance) ─────────
            lum = (
                0.2126 * cell[..., 0].astype(np.float32) +
                0.7152 * cell[..., 1].astype(np.float32) +
                0.0722 * cell[..., 2].astype(np.float32)
            )
            brightness = (
                (lum * alpha_w).sum() / weight_sum if weight_sum > 0 else 0.0
            )
            brightness_norm = float(brightness) / 255.0  # 0..1

            # ── Character selection ───────────────────────────
            if pending:
                # Continue emitting the current custom string
                char = pending.popleft()
            elif _CUSTOM_POOL and random.random() < CUSTOM_DENSITY:
                # Start a new custom string — queue the tail, emit the head
                chosen: str = random.choice(_CUSTOM_POOL)
                char = chosen[0]
                pending.extend(list(chosen[1:]))
            else:
                ramp_idx = int(brightness_norm * (RAMP_LEN - 1))
                char = ASCII_RAMP[ramp_idx]

            row_cells.append((char, cell_colour))

        grid.append(row_cells)

    return grid


def _render_grid(
    grid: list[list[tuple[str, tuple[int, int, int]]]],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    char_w: int,
    char_h: int,
    style: str,
    original_size: tuple[int, int],
) -> Image.Image:
    """
    Render a 2-D (char, rgb) grid to a PIL RGB image, then resize
    to exactly match the original image dimensions.

    style:
      "white_on_black" — white characters on black background
      "black_on_white" — black characters on white background
      "colour"         — each character drawn in its source pixel colour,
                         on a black background
    original_size: (width, height) of the source frame
    """
    bg_col: tuple[int, int, int]
    fg_col: tuple[int, int, int] | None  # None = use per-cell colour

    if style == "colour":
        bg_col = (0, 0, 0)
        fg_col = None  # signals per-character colouring
    elif style == "white_on_black":
        bg_col = (0, 0, 0)
        fg_col = (255, 255, 255)
    else:  # black_on_white
        bg_col = (255, 255, 255)
        fg_col = (0, 0, 0)

    rows = len(grid)
    cols = max((len(r) for r in grid), default=0)

    img_out = Image.new("RGB", (cols * char_w, rows * char_h), bg_col)
    draw = ImageDraw.Draw(img_out)

    for r_idx, row in enumerate(grid):
        for c_idx, (char, cell_rgb) in enumerate(row):
            if char == " ":
                continue
            colour = cell_rgb if fg_col is None else fg_col
            draw.text(
                (c_idx * char_w, r_idx * char_h),
                char,
                font=font,
                fill=colour,
            )

    # Resize back to the original frame dimensions so the output
    # pixel dimensions and aspect ratio always match the input exactly.
    if img_out.size != original_size:
        img_out = img_out.resize(original_size, Image.LANCZOS)

    return img_out


def process_folder(folder: str) -> None:
    """Main entry point: process all PNGs in the given folder."""
    folder_path = Path(folder.strip('"').strip("'"))

    if not folder_path.is_dir():
        print(f"\n  Error: '{folder_path}' is not a valid directory.\n")
        sys.exit(1)

    # ── Collect frames ────────────────────────────────────────
    frames = sorted(
        glob.glob(str(folder_path / "*.png")) +
        glob.glob(str(folder_path / "*.PNG"))
    )
    if not frames:
        print(f"\n  No PNG files found in: {folder_path}\n")
        sys.exit(1)

    print("─" * 60)
    print(f"  Folder  : {folder_path}")
    print(f"  Frames  : {len(frames)}")
    print(f"  Cell    : {CELL_W}×{CELL_H}px  →  font {FONT_SIZE}pt")
    print(f"  Custom  : {CUSTOM_STRINGS}  density={CUSTOM_DENSITY}")
    print(f"  Style   : {STYLE}")
    print(f"  Premult : {IS_PREMULTIPLIED}")
    print("─" * 60)

    _build_custom_pool()
    font = _find_font(FONT_SIZE)
    char_w, char_h = _get_char_size(font)
    print(f"  Char px : {char_w}w × {char_h}h")
    print("─" * 60)

    styles_to_render: list[str] = (
        ["white_on_black", "black_on_white", "colour"] if STYLE == "all"
        else ["white_on_black", "black_on_white"] if STYLE == "both"
        else [STYLE]
    )

    # ── Create output dirs ────────────────────────────────────
    out_dirs: dict[str, Path] = {}
    for st in styles_to_render:
        d = folder_path / OUTPUT_FOLDER / st
        d.mkdir(parents=True, exist_ok=True)
        out_dirs[st] = d

    # ── Process frames ────────────────────────────────────────
    for i, frame_path in enumerate(frames):
        stem = Path(frame_path).stem
        print(f"  [{i + 1:>4}/{len(frames)}]  {stem}", end="", flush=True)

        try:
            img = Image.open(frame_path)
            original_size = img.size  # (width, height) — captured before any processing
            grid = _image_to_ascii_grid(img)

            for st in styles_to_render:
                out_img = _render_grid(grid, font, char_w, char_h, st, original_size)
                out_path = out_dirs[st] / f"{stem}_ascii.png"
                out_img.save(str(out_path))

            print("  ✓")

        except Exception as e:
            print(f"  ✗  Error: {e}")

    print("─" * 60)
    print(f"  Done! Output → {folder_path / OUTPUT_FOLDER}")
    print("─" * 60)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("Example:")
        print('  python ascii_converter.py "/Users/harv/Desktop/frames/"')
        sys.exit(0)

    process_folder(sys.argv[1])
