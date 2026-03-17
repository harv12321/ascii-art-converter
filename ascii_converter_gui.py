#!/usr/bin/env python3
"""
ASCII Art Image Sequence Converter — GUI
Polka Dot Post
"""

import sys
import os
import random
import glob
import threading
import queue
from pathlib import Path
from collections import deque
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext

try:
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
except ImportError:
    root_check = tk.Tk()
    root_check.withdraw()
    import tkinter.messagebox as mb
    mb.showerror(
        "Missing Dependencies",
        "Please install required packages:\n\n  pip install Pillow numpy\n\nThen relaunch."
    )
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════
#  CORE ENGINE  (same logic as ascii_converter_2.py, class-wrapped)
# ══════════════════════════════════════════════════════════════════

class AsciiConverter:
    ASCII_RAMP = " .'`^\",.:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"

    def __init__(self, config: dict, log_fn):
        self.cfg = config
        self.log = log_fn
        self._ramp_len = len(self.ASCII_RAMP)
        self._custom_pool: list[str] = []

    # ── helpers ─────────────────────────────────────────────────

    def _build_custom_pool(self):
        strings = [s.strip() for s in self.cfg["custom_strings"].split(",") if s.strip()]
        self._custom_pool = strings if strings else list(self.ASCII_RAMP[self._ramp_len // 2:])

    def _find_font(self, size: int):
        candidates = []
        fp = self.cfg["font_path"].strip()
        if fp:
            candidates.append(fp)
        candidates += [
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "C:/Windows/Fonts/lucon.ttf",
            "/System/Library/Fonts/Menlo.ttc",
            "/Library/Fonts/Courier New.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]
        for path in candidates:
            if os.path.isfile(path):
                try:
                    font = ImageFont.truetype(path, size)
                    self.log(f"  Font: {path}")
                    return font
                except Exception:
                    continue
        self.log("  ⚠  No TTF found — using PIL bitmap default.")
        return ImageFont.load_default()

    def _get_char_size(self, font):
        probe = Image.new("RGB", (200, 60))
        draw = ImageDraw.Draw(probe)
        bbox = draw.textbbox((0, 0), "M", font=font)
        return (bbox[2] - bbox[0]), (bbox[3] - bbox[1])

    def _unpremultiply(self, rgba: np.ndarray) -> np.ndarray:
        alpha_f = rgba[..., 3].astype(np.float32) / 255.0
        mask = alpha_f > 0
        out = rgba.astype(np.float32).copy()
        for ch_idx in range(3):
            channel = out[..., ch_idx]
            channel[mask] = channel[mask] / alpha_f[mask]
            out[..., ch_idx] = channel
        return np.clip(out, 0, 255).astype(np.uint8)

    def _image_to_grid(self, img: Image.Image):
        cell_w = self.cfg["cell_w"]
        cell_h = self.cfg["cell_h"]
        alpha_thresh = self.cfg["alpha_threshold"]
        custom_density = self.cfg["custom_density"]
        is_premult = self.cfg["is_premultiplied"]

        img_rgba = img.convert("RGBA")
        rgba = np.array(img_rgba)
        if is_premult:
            rgba = self._unpremultiply(rgba)

        h, w = rgba.shape[:2]
        cols = w // cell_w
        rows = h // cell_h
        grid = []

        for row_idx in range(rows):
            y0, y1 = row_idx * cell_h, row_idx * cell_h + cell_h
            row_cells = []
            pending: deque[str] = deque()

            for col_idx in range(cols):
                x0, x1 = col_idx * cell_w, col_idx * cell_w + cell_w
                cell = rgba[y0:y1, x0:x1]
                alpha_vals = cell[..., 3].astype(np.float32)
                mean_alpha = alpha_vals.mean()

                if mean_alpha < alpha_thresh:
                    pending.clear()
                    row_cells.append((" ", (0, 0, 0)))
                    continue

                alpha_w = alpha_vals / 255.0
                weight_sum = alpha_w.sum()
                if weight_sum > 0:
                    avg_r = int((cell[..., 0].astype(np.float32) * alpha_w).sum() / weight_sum)
                    avg_g = int((cell[..., 1].astype(np.float32) * alpha_w).sum() / weight_sum)
                    avg_b = int((cell[..., 2].astype(np.float32) * alpha_w).sum() / weight_sum)
                else:
                    avg_r = avg_g = avg_b = 0
                cell_colour = (min(255, avg_r), min(255, avg_g), min(255, avg_b))

                lum = (
                    0.2126 * cell[..., 0].astype(np.float32) +
                    0.7152 * cell[..., 1].astype(np.float32) +
                    0.0722 * cell[..., 2].astype(np.float32)
                )
                brightness = (lum * alpha_w).sum() / weight_sum if weight_sum > 0 else 0.0
                brightness_norm = float(brightness) / 255.0

                if pending:
                    char = pending.popleft()
                elif self._custom_pool and random.random() < custom_density:
                    chosen = random.choice(self._custom_pool)
                    char = chosen[0]
                    pending.extend(list(chosen[1:]))
                else:
                    ramp_idx = int(brightness_norm * (self._ramp_len - 1))
                    char = self.ASCII_RAMP[ramp_idx]

                row_cells.append((char, cell_colour))
            grid.append(row_cells)

        return grid

    def _render_grid(self, grid, font, char_w, char_h, style, original_size):
        if style == "colour":
            bg_col, fg_col = (0, 0, 0), None
        elif style == "white_on_black":
            bg_col, fg_col = (0, 0, 0), (255, 255, 255)
        else:
            bg_col, fg_col = (255, 255, 255), (0, 0, 0)

        rows = len(grid)
        cols = max((len(r) for r in grid), default=0)
        img_out = Image.new("RGB", (cols * char_w, rows * char_h), bg_col)
        draw = ImageDraw.Draw(img_out)

        for r_idx, row in enumerate(grid):
            for c_idx, (char, cell_rgb) in enumerate(row):
                if char == " ":
                    continue
                colour = cell_rgb if fg_col is None else fg_col
                draw.text((c_idx * char_w, r_idx * char_h), char, font=font, fill=colour)

        if img_out.size != original_size:
            img_out = img_out.resize(original_size, Image.LANCZOS)
        return img_out

    # ── main ────────────────────────────────────────────────────

    def run(self, folder: str, progress_fn, done_fn, stop_event: threading.Event):
        folder_path = Path(folder.strip('"').strip("'"))
        if not folder_path.is_dir():
            self.log(f"\n  Error: '{folder_path}' is not a valid directory.\n")
            done_fn(success=False)
            return

        frames = sorted(
            glob.glob(str(folder_path / "*.png")) +
            glob.glob(str(folder_path / "*.PNG"))
        )
        if not frames:
            self.log(f"\n  No PNG files found in: {folder_path}\n")
            done_fn(success=False)
            return

        self.log("─" * 58)
        self.log(f"  Folder : {folder_path}")
        self.log(f"  Frames : {len(frames)}")
        self.log(f"  Cell   : {self.cfg['cell_w']}×{self.cfg['cell_h']}px → font {self.cfg['font_size']}pt")
        self.log(f"  Custom : {self.cfg['custom_strings']}  density={self.cfg['custom_density']}")
        self.log(f"  Style  : {self.cfg['style']}")
        self.log("─" * 58)

        self._build_custom_pool()
        font = self._find_font(self.cfg["font_size"])
        char_w, char_h = self._get_char_size(font)
        self.log(f"  Char px: {char_w}w × {char_h}h")
        self.log("─" * 58)

        style_val = self.cfg["style"]
        styles_to_render = (
            ["white_on_black", "black_on_white", "colour"] if style_val == "all"
            else ["white_on_black", "black_on_white"] if style_val == "both"
            else [style_val]
        )

        output_folder = self.cfg.get("output_folder", "ascii_output")
        out_dirs = {}
        for st in styles_to_render:
            d = folder_path / output_folder / st
            d.mkdir(parents=True, exist_ok=True)
            out_dirs[st] = d

        total = len(frames)
        for i, frame_path in enumerate(frames):
            if stop_event.is_set():
                self.log("\n  Cancelled.")
                done_fn(success=False)
                return

            stem = Path(frame_path).stem
            try:
                img = Image.open(frame_path)
                original_size = img.size
                grid = self._image_to_grid(img)
                for st in styles_to_render:
                    out_img = self._render_grid(grid, font, char_w, char_h, st, original_size)
                    out_path = out_dirs[st] / f"{stem}_ascii.png"
                    out_img.save(str(out_path))
                self.log(f"  [{i + 1:>4}/{total}]  {stem}  ✓")
            except Exception as e:
                self.log(f"  [{i + 1:>4}/{total}]  {stem}  ✗  {e}")

            progress_fn(int((i + 1) / total * 100))

        self.log("─" * 58)
        self.log(f"  Done! → {folder_path / output_folder}")
        self.log("─" * 58)
        done_fn(success=True)


# ══════════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════════

DARK_BG    = "#1e1e2e"
PANEL_BG   = "#27273a"
ACCENT     = "#cba6f7"   # lavender
GREEN      = "#a6e3a1"
RED        = "#f38ba8"
TEXT_FG    = "#cdd6f4"
MUTED      = "#6c7086"
INPUT_BG   = "#313244"
BORDER     = "#45475a"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ASCII Art Converter  ·  Polka Dot Post")
        self.configure(bg=DARK_BG)
        self.resizable(True, True)
        self.minsize(900, 620)

        self._stop_event = threading.Event()
        self._log_queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build_ui()
        self._poll_log()

    # ── layout ──────────────────────────────────────────────────

    def _build_ui(self):
        self.columnconfigure(0, weight=0, minsize=310)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # Left panel
        left = tk.Frame(self, bg=PANEL_BG, padx=14, pady=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        left.columnconfigure(1, weight=1)

        # Right panel
        right = tk.Frame(self, bg=DARK_BG, padx=10, pady=10)
        right.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_left(left)
        self._build_right(right)

    def _lbl(self, parent, text, row, col=0, **kw):
        tk.Label(
            parent, text=text, bg=PANEL_BG, fg=TEXT_FG,
            font=("Segoe UI", 9), anchor="w", **kw
        ).grid(row=row, column=col, sticky="w", pady=3, padx=(0, 6))

    def _entry(self, parent, var, row, width=10):
        e = tk.Entry(
            parent, textvariable=var,
            bg=INPUT_BG, fg=TEXT_FG, insertbackground=TEXT_FG,
            relief="flat", font=("Consolas", 9), width=width,
            highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BORDER
        )
        e.grid(row=row, column=1, sticky="ew", pady=3)
        return e

    def _build_left(self, parent):
        r = 0

        # ── Title ──────────────────────────────────────────────
        tk.Label(
            parent, text="ASCII ART CONVERTER", bg=PANEL_BG, fg=ACCENT,
            font=("Segoe UI", 11, "bold")
        ).grid(row=r, column=0, columnspan=2, pady=(0, 10), sticky="w")
        r += 1

        # ── Input folder ───────────────────────────────────────
        tk.Label(parent, text="Input Folder", bg=PANEL_BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(6, 2))
        r += 1

        self._folder_var = tk.StringVar()
        folder_frame = tk.Frame(parent, bg=PANEL_BG)
        folder_frame.grid(row=r, column=0, columnspan=2, sticky="ew", pady=3)
        folder_frame.columnconfigure(0, weight=1)

        tk.Entry(
            folder_frame, textvariable=self._folder_var,
            bg=INPUT_BG, fg=TEXT_FG, insertbackground=TEXT_FG,
            relief="flat", font=("Consolas", 9),
            highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BORDER
        ).grid(row=0, column=0, sticky="ew")
        tk.Button(
            folder_frame, text="Browse", command=self._browse,
            bg=ACCENT, fg=DARK_BG, font=("Segoe UI", 8, "bold"),
            relief="flat", padx=8, cursor="hand2"
        ).grid(row=0, column=1, padx=(6, 0))
        r += 1

        # ── Cell & Font ────────────────────────────────────────
        tk.Label(parent, text="Cell & Font", bg=PANEL_BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(10, 2))
        r += 1

        self._cell_w = tk.IntVar(value=6)
        self._cell_h = tk.IntVar(value=12)
        self._font_size = tk.IntVar(value=12)
        self._font_path = tk.StringVar(value="")

        self._lbl(parent, "Cell W (px)", r);  self._entry(parent, self._cell_w, r, 6);  r += 1
        self._lbl(parent, "Cell H (px)", r);  self._entry(parent, self._cell_h, r, 6);  r += 1
        self._lbl(parent, "Font size (pt)", r); self._entry(parent, self._font_size, r, 6); r += 1
        self._lbl(parent, "Font path", r)
        tk.Entry(
            parent, textvariable=self._font_path,
            bg=INPUT_BG, fg=TEXT_FG, insertbackground=TEXT_FG,
            relief="flat", font=("Consolas", 9),
            highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BORDER
        ).grid(row=r, column=1, sticky="ew", pady=3)
        r += 1

        # ── Custom strings ─────────────────────────────────────
        tk.Label(parent, text="Custom Strings", bg=PANEL_BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(10, 2))
        r += 1

        self._custom_strings = tk.StringVar(value="BRAND, PDP, ASCII, 2026")
        self._custom_density = tk.DoubleVar(value=0.5)

        self._lbl(parent, "Strings (comma-sep)", r)
        tk.Entry(
            parent, textvariable=self._custom_strings,
            bg=INPUT_BG, fg=TEXT_FG, insertbackground=TEXT_FG,
            relief="flat", font=("Consolas", 9),
            highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BORDER
        ).grid(row=r, column=1, sticky="ew", pady=3)
        r += 1

        self._lbl(parent, f"Density", r)
        density_frame = tk.Frame(parent, bg=PANEL_BG)
        density_frame.grid(row=r, column=1, sticky="ew", pady=3)
        density_frame.columnconfigure(0, weight=1)
        self._density_label = tk.Label(density_frame, text="0.50", bg=PANEL_BG,
                                       fg=ACCENT, font=("Consolas", 9), width=4)
        self._density_label.grid(row=0, column=1, padx=(4, 0))
        tk.Scale(
            density_frame, variable=self._custom_density,
            from_=0.0, to=1.0, resolution=0.05, orient="horizontal",
            bg=PANEL_BG, fg=TEXT_FG, highlightthickness=0,
            troughcolor=INPUT_BG, activebackground=ACCENT,
            command=lambda v: self._density_label.config(text=f"{float(v):.2f}")
        ).grid(row=0, column=0, sticky="ew")
        r += 1

        # ── Output style ───────────────────────────────────────
        tk.Label(parent, text="Output Style", bg=PANEL_BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(10, 2))
        r += 1

        self._style = tk.StringVar(value="all")
        style_frame = tk.Frame(parent, bg=PANEL_BG)
        style_frame.grid(row=r, column=0, columnspan=2, sticky="w")
        for val, label in [
            ("all", "All"), ("both", "Mono"), ("white_on_black", "White/Black"),
            ("black_on_white", "Black/White"), ("colour", "Colour")
        ]:
            tk.Radiobutton(
                style_frame, text=label, variable=self._style, value=val,
                bg=PANEL_BG, fg=TEXT_FG, selectcolor=PANEL_BG,
                activebackground=PANEL_BG, activeforeground=ACCENT,
                font=("Segoe UI", 9)
            ).pack(side="left", padx=3)
        r += 1

        # ── Alpha & flags ──────────────────────────────────────
        tk.Label(parent, text="Alpha & Flags", bg=PANEL_BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(10, 2))
        r += 1

        self._alpha_threshold = tk.IntVar(value=30)
        self._is_premult = tk.BooleanVar(value=True)
        self._output_folder = tk.StringVar(value="ascii_output")

        self._lbl(parent, "Alpha threshold", r); self._entry(parent, self._alpha_threshold, r, 6); r += 1

        check_frame = tk.Frame(parent, bg=PANEL_BG)
        check_frame.grid(row=r, column=0, columnspan=2, sticky="w", pady=3)
        tk.Checkbutton(
            check_frame, text="Premultiplied alpha", variable=self._is_premult,
            bg=PANEL_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
            activebackground=PANEL_BG, activeforeground=ACCENT,
            font=("Segoe UI", 9)
        ).pack(side="left")
        r += 1

        self._lbl(parent, "Output subfolder", r)
        tk.Entry(
            parent, textvariable=self._output_folder,
            bg=INPUT_BG, fg=TEXT_FG, insertbackground=TEXT_FG,
            relief="flat", font=("Consolas", 9),
            highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BORDER
        ).grid(row=r, column=1, sticky="ew", pady=3)
        r += 1

        # ── Buttons ────────────────────────────────────────────
        tk.Label(parent, text="", bg=PANEL_BG).grid(row=r, column=0, pady=4); r += 1

        btn_frame = tk.Frame(parent, bg=PANEL_BG)
        btn_frame.grid(row=r, column=0, columnspan=2, sticky="ew")
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)

        self._convert_btn = tk.Button(
            btn_frame, text="▶  Convert", command=self._start_conversion,
            bg=GREEN, fg=DARK_BG, font=("Segoe UI", 10, "bold"),
            relief="flat", padx=10, pady=6, cursor="hand2"
        )
        self._convert_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self._cancel_btn = tk.Button(
            btn_frame, text="■  Cancel", command=self._cancel,
            bg=RED, fg=DARK_BG, font=("Segoe UI", 10, "bold"),
            relief="flat", padx=10, pady=6, cursor="hand2", state="disabled"
        )
        self._cancel_btn.grid(row=0, column=1, sticky="ew")
        r += 1

    def _build_right(self, parent):
        tk.Label(
            parent, text="Output Log", bg=DARK_BG, fg=MUTED,
            font=("Segoe UI", 8, "bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self._log_box = scrolledtext.ScrolledText(
            parent, bg=INPUT_BG, fg=TEXT_FG, insertbackground=TEXT_FG,
            font=("Consolas", 9), relief="flat", wrap="word",
            highlightthickness=1, highlightbackground=BORDER
        )
        self._log_box.grid(row=1, column=0, sticky="nsew")
        self._log_box.config(state="disabled")

        self._progress = ttk.Progressbar(parent, orient="horizontal", mode="determinate")
        self._progress.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "TProgressbar",
            troughcolor=INPUT_BG, background=ACCENT, thickness=6
        )

    # ── actions ─────────────────────────────────────────────────

    def _browse(self):
        folder = filedialog.askdirectory(title="Select folder of PNG frames")
        if folder:
            self._folder_var.set(folder)

    def _get_config(self) -> dict:
        return {
            "cell_w": self._cell_w.get(),
            "cell_h": self._cell_h.get(),
            "font_size": self._font_size.get(),
            "font_path": self._font_path.get(),
            "custom_strings": self._custom_strings.get(),
            "custom_density": self._custom_density.get(),
            "style": self._style.get(),
            "alpha_threshold": self._alpha_threshold.get(),
            "is_premultiplied": self._is_premult.get(),
            "output_folder": self._output_folder.get() or "ascii_output",
        }

    def _log(self, msg: str):
        self._log_queue.put(msg)

    def _poll_log(self):
        while not self._log_queue.empty():
            msg = self._log_queue.get_nowait()
            self._log_box.config(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.config(state="disabled")
        self.after(100, self._poll_log)

    def _set_progress(self, pct: int):
        self._progress["value"] = pct

    def _on_done(self, success: bool):
        self._convert_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")
        if success:
            self._progress["value"] = 100

    def _start_conversion(self):
        folder = self._folder_var.get().strip()
        if not folder:
            self._log("  ⚠  Please select an input folder first.")
            return

        self._stop_event.clear()
        self._convert_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._progress["value"] = 0

        self._log_box.config(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.config(state="disabled")

        cfg = self._get_config()
        converter = AsciiConverter(cfg, self._log)

        def run():
            converter.run(
                folder,
                progress_fn=lambda p: self.after(0, self._set_progress, p),
                done_fn=lambda success: self.after(0, self._on_done, success),
                stop_event=self._stop_event,
            )

        self._worker = threading.Thread(target=run, daemon=True)
        self._worker.start()

    def _cancel(self):
        self._stop_event.set()
        self._cancel_btn.config(state="disabled")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = App()
    app.mainloop()
