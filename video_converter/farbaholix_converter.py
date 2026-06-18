#!/usr/bin/env python3
"""
Farbaholix Video Converter
Локальный конвертер видео для macOS
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import threading
import os
import re
import sys
from pathlib import Path

# ── Farbaholix colors ────────────────────────────────────────────────────────
ORANGE   = "#E46735"
ORANGE_H = "#c55520"
BG       = "#161616"
SURFACE  = "#242424"
BORDER   = "#333333"
TEXT     = "#e0e0e0"
MUTED    = "#888888"
GREEN    = "#4CAF50"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ── Presets ──────────────────────────────────────────────────────────────────
PRESETS = {
    "Фон для сайта": {
        "icon": "🎬",
        "desc": "MP4 · без звука · 1920p · оптимизирован для загрузки",
        "args": [
            "-c:v", "libx264", "-crf", "28", "-preset", "slow",
            "-vf", "scale=1920:-2", "-an", "-movflags", "+faststart"
        ],
        "ext": "_web_bg.mp4",
    },
    "Портфолио веб": {
        "icon": "📹",
        "desc": "MP4 · 1080p · со звуком · для embedding на сайте",
        "args": [
            "-c:v", "libx264", "-crf", "23", "-preset", "slow",
            "-vf", "scale=1920:-2",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"
        ],
        "ext": "_portfolio.mp4",
    },
    "Instagram Reels": {
        "icon": "📱",
        "desc": "MP4 · 1080×1920 · вертикальное · до 90 сек",
        "args": [
            "-c:v", "libx264", "-crf", "23",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                   "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"
        ],
        "ext": "_reels.mp4",
    },
    "Instagram Square": {
        "icon": "⬜",
        "desc": "MP4 · 1080×1080 · квадратное",
        "args": [
            "-c:v", "libx264", "-crf", "23",
            "-vf", "scale=1080:1080:force_original_aspect_ratio=decrease,"
                   "pad=1080:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"
        ],
        "ext": "_square.mp4",
    },
    "WebM (браузеры)": {
        "icon": "🌐",
        "desc": "WebM VP9 · 1080p · без звука · Chrome/Firefox",
        "args": [
            "-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0",
            "-vf", "scale=1920:-2", "-an"
        ],
        "ext": "_web.webm",
    },
    "GIF анимация": {
        "icon": "🎞",
        "desc": "Анимированный GIF · 480p · 12fps · для сайта",
        "args": [
            "-vf", "fps=12,scale=480:-1:flags=lanczos,"
                   "split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer"
        ],
        "ext": ".gif",
    },
}


# ── Main App ──────────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Farbaholix Video Converter")
        self.geometry("620x640")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        self.input_path  = tk.StringVar()
        self.output_dir  = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.preset_var  = tk.StringVar(value=list(PRESETS.keys())[0])
        self.status_var  = tk.StringVar(value="Выберите видеофайл")
        self.progress_var = tk.DoubleVar(value=0)
        self._duration   = 0
        self._converting = False

        self._build_ui()
        self.ffmpeg = self._find_ffmpeg()
        self.ffprobe = self._find_ffprobe()

    # ── ffmpeg detection ──────────────────────────────────────────────────────
    def _find_bin(self, name):
        candidates = [
            name,
            f"/opt/homebrew/bin/{name}",
            f"/usr/local/bin/{name}",
            f"/usr/bin/{name}",
        ]
        for c in candidates:
            try:
                r = subprocess.run([c, "-version"], capture_output=True, timeout=3)
                if r.returncode == 0:
                    return c
            except Exception:
                pass
        return None

    def _find_ffmpeg(self):
        p = self._find_bin("ffmpeg")
        if not p:
            self.status_var.set("⚠️  ffmpeg не найден — brew install ffmpeg")
        return p

    def _find_ffprobe(self):
        return self._find_bin("ffprobe")

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=ORANGE, corner_radius=0, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="FARBAHOLIX",
                     font=ctk.CTkFont("Helvetica Neue", 20, "bold"),
                     text_color="white").pack(side="left", padx=20, pady=16)
        ctk.CTkLabel(header, text="Video Converter",
                     font=ctk.CTkFont("Helvetica Neue", 15),
                     text_color="#ffd0b8").pack(side="left", pady=16)

        body = ctk.CTkFrame(self, fg_color=BG)
        body.pack(fill="both", expand=True, padx=24, pady=20)

        # ── Input ──
        self._label(body, "ИСХОДНЫЙ ФАЙЛ")
        row = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=8)
        row.pack(fill="x", pady=(6, 0))

        ctk.CTkEntry(row, textvariable=self.input_path,
                     fg_color="transparent", border_width=0,
                     text_color=TEXT, font=ctk.CTkFont("Helvetica Neue", 12),
                     placeholder_text="Перетащите файл или нажмите «Выбрать»"
                     ).pack(side="left", fill="x", expand=True, padx=12)

        ctk.CTkButton(row, text="Выбрать", width=90,
                      fg_color=ORANGE, hover_color=ORANGE_H,
                      font=ctk.CTkFont("Helvetica Neue", 12),
                      command=self._pick_input).pack(side="right", padx=8, pady=8)

        # ── Drop hint ──
        drop_zone = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=8,
                                  border_width=1, border_color=BORDER, height=56)
        drop_zone.pack(fill="x", pady=(6, 20))
        drop_zone.pack_propagate(False)

        ctk.CTkLabel(drop_zone, text="↓  Перетащите видео сюда",
                     text_color=MUTED,
                     font=ctk.CTkFont("Helvetica Neue", 12)).pack(expand=True)

        drop_zone.bind("<Button-1>", lambda e: self._pick_input())
        drop_zone.configure(cursor="hand2")

        self._setup_drag_drop(drop_zone)

        # ── Presets ──
        self._label(body, "ФОРМАТ")
        grid = ctk.CTkFrame(body, fg_color=BG)
        grid.pack(fill="x", pady=(6, 4))

        keys = list(PRESETS.keys())
        self._preset_buttons = {}
        for i, name in enumerate(keys):
            p = PRESETS[name]
            col = i % 3
            row_n = i // 3
            btn = ctk.CTkButton(grid,
                                 text=f"{p['icon']}  {name}",
                                 width=180, height=40,
                                 fg_color=ORANGE if i == 0 else SURFACE,
                                 hover_color=ORANGE_H if i == 0 else BORDER,
                                 text_color=TEXT,
                                 font=ctk.CTkFont("Helvetica Neue", 12),
                                 command=lambda n=name: self._select_preset(n))
            btn.grid(row=row_n, column=col, padx=4, pady=4, sticky="ew")
            self._preset_buttons[name] = btn

        grid.columnconfigure((0, 1, 2), weight=1)

        self.desc_label = ctk.CTkLabel(body, text=PRESETS[keys[0]]["desc"],
                                        text_color=MUTED,
                                        font=ctk.CTkFont("Helvetica Neue", 11))
        self.desc_label.pack(anchor="w", pady=(4, 16))

        # ── Output folder ──
        self._label(body, "ПАПКА СОХРАНЕНИЯ")
        row2 = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=8)
        row2.pack(fill="x", pady=(6, 20))

        ctk.CTkEntry(row2, textvariable=self.output_dir,
                     fg_color="transparent", border_width=0,
                     text_color=TEXT,
                     font=ctk.CTkFont("Helvetica Neue", 12)
                     ).pack(side="left", fill="x", expand=True, padx=12)

        ctk.CTkButton(row2, text="Изменить", width=90,
                      fg_color=SURFACE, hover_color=BORDER, text_color=MUTED,
                      border_width=1, border_color=BORDER,
                      font=ctk.CTkFont("Helvetica Neue", 12),
                      command=self._pick_output).pack(side="right", padx=8, pady=8)

        # ── Convert button ──
        self.convert_btn = ctk.CTkButton(body, text="КОНВЕРТИРОВАТЬ",
                                          height=48,
                                          fg_color=ORANGE, hover_color=ORANGE_H,
                                          font=ctk.CTkFont("Helvetica Neue", 14, "bold"),
                                          command=self._start)
        self.convert_btn.pack(fill="x", pady=(0, 12))

        # ── Progress ──
        self.progress_bar = ctk.CTkProgressBar(body, variable=self.progress_var,
                                                progress_color=ORANGE,
                                                fg_color=SURFACE)
        self.progress_bar.pack(fill="x", pady=(0, 8))
        self.progress_bar.set(0)

        ctk.CTkLabel(body, textvariable=self.status_var,
                     text_color=MUTED,
                     font=ctk.CTkFont("Helvetica Neue", 11)).pack(anchor="w")

    def _label(self, parent, text):
        ctk.CTkLabel(parent, text=text, text_color=ORANGE,
                     font=ctk.CTkFont("Helvetica Neue", 10, "bold")).pack(anchor="w")

    # ── Drag & Drop (macOS) ───────────────────────────────────────────────────
    def _setup_drag_drop(self, widget):
        try:
            from tkinterdnd2 import DND_FILES
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except ImportError:
            pass

    def _on_drop(self, event):
        path = event.data.strip("{}")
        self.input_path.set(path)

    # ── Interactions ──────────────────────────────────────────────────────────
    def _select_preset(self, name):
        self.preset_var.set(name)
        for n, btn in self._preset_buttons.items():
            if n == name:
                btn.configure(fg_color=ORANGE, hover_color=ORANGE_H)
            else:
                btn.configure(fg_color=SURFACE, hover_color=BORDER)
        self.desc_label.configure(text=PRESETS[name]["desc"])

    def _pick_input(self):
        p = filedialog.askopenfilename(
            title="Выберите видео",
            filetypes=[
                ("Видео", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv *.mts *.m2ts"),
                ("Все файлы", "*.*"),
            ])
        if p:
            self.input_path.set(p)

    def _pick_output(self):
        p = filedialog.askdirectory(title="Папка для сохранения")
        if p:
            self.output_dir.set(p)

    # ── Conversion ────────────────────────────────────────────────────────────
    def _start(self):
        if self._converting:
            return
        if not self.input_path.get():
            messagebox.showwarning("Нет файла", "Выберите исходное видео")
            return
        if not self.ffmpeg:
            messagebox.showerror("ffmpeg не найден",
                                 "Установите ffmpeg:\nbrew install ffmpeg")
            return
        threading.Thread(target=self._convert, daemon=True).start()

    def _get_duration(self, path):
        if not self.ffprobe:
            return 0
        try:
            r = subprocess.run(
                [self.ffprobe, "-v", "error", "-show_entries",
                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=10)
            return float(r.stdout.strip())
        except Exception:
            return 0

    def _convert(self):
        self._converting = True
        self.convert_btn.configure(state="disabled", text="Конвертирование...")
        self.progress_var.set(0)

        src   = self.input_path.get()
        p     = PRESETS[self.preset_var.get()]
        stem  = Path(src).stem
        dest  = str(Path(self.output_dir.get()) / (stem + p["ext"]))
        dur   = self._get_duration(src)

        cmd = [self.ffmpeg, "-y", "-i", src] + p["args"] + [
            "-progress", "pipe:1", "-nostats", dest
        ]

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            time_re = re.compile(r"out_time_ms=(\d+)")
            spd_re  = re.compile(r"speed=\s*([\d.]+)x")
            speed   = 1.0

            for line in proc.stdout:
                m = time_re.search(line)
                if m and dur:
                    elapsed = int(m.group(1)) / 1_000_000
                    pct = min(elapsed / dur, 1.0)
                    self.progress_var.set(pct)
                    self.status_var.set(
                        f"Прогресс: {int(pct*100)}%  |  "
                        f"{elapsed:.0f} / {dur:.0f} сек  |  {speed:.1f}x"
                    )
                s = spd_re.search(line)
                if s:
                    speed = float(s.group(1))

            proc.wait()

            if proc.returncode == 0:
                size_mb = os.path.getsize(dest) / 1_048_576
                self.progress_var.set(1.0)
                self.status_var.set(
                    f"✅  {Path(dest).name}  —  {size_mb:.1f} МБ"
                )
                subprocess.run(["open", "-R", dest])
            else:
                err = proc.stderr.read()[-600:]
                self.status_var.set("❌  Ошибка конвертации")
                messagebox.showerror("Ошибка", err)

        except Exception as e:
            self.status_var.set(f"❌  {e}")
        finally:
            self._converting = False
            self.convert_btn.configure(state="normal", text="КОНВЕРТИРОВАТЬ")


if __name__ == "__main__":
    app = App()
    app.mainloop()
