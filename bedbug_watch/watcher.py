"""Ночной сторож: смотрит в камеру, ловит ползущее пятно, будит сигналом.

Быстрый старт (камера в USB, кадр — участок простыни шириной 20 см):

    python3 watcher.py --fov-width-mm 200

Полезные режимы:

    --calibrate            ночь без тревог: печатает, что видит, и как это по размеру
    --source rtsp://...    IP-камера или телефон с приложением IP Webcam
    --source ночь.mp4      прогнать уже записанное видео и посмотреть, сработает ли
    --report               утренний разбор: что и когда было за прошедшие ночи
    --sound                пищать в комнате, а не только слать в Telegram

Ctrl+C завершает и печатает итог ночи.
"""
import argparse
import csv
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime, timedelta

import cv2
import numpy as np

import alert
from detector import BugDetector, DetectorConfig, Detection

_BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(_BASE, "nights")
JOURNAL = "journal.csv"
JOURNAL_HEAD = ["время", "длина_мм", "путь_мм", "скорость_мм_с", "уверенность", "фото", "видео"]

_stop = False


def _on_sigint(*_):
    global _stop
    _stop = True


# ── источник кадров ───────────────────────────────────────────────────────────

def open_source(source: str):
    """Число — индекс USB-камеры, всё остальное — файл или сетевой поток."""
    handle = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(handle)
    if not cap.isOpened():
        raise SystemExit(f"Не открылась камера/файл: {source}")
    return cap, (not source.isdigit() and os.path.exists(source))


# ── улики ─────────────────────────────────────────────────────────────────────

def annotate(frame: np.ndarray, d: Detection) -> np.ndarray:
    """Обводим находку и подписываем — иначе на кадре просто точка."""
    out = frame.copy() if frame.ndim == 3 else cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    pad = 12
    cv2.rectangle(out, (d.x - pad, d.y - pad), (d.x + d.w + pad, d.y + d.h + pad),
                  (0, 0, 255), 2)
    stamp = datetime.fromtimestamp(d.ts).strftime("%H:%M:%S")
    cv2.putText(out, f"{stamp}  {d.length_mm:.1f} mm  {d.speed_mm_s:.0f} mm/s",
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return out


def write_clip(path: str, frames: list, fps: float) -> str:
    """Ролик вокруг сработки: одна фотография точки никого не убеждает."""
    if not frames:
        return ""
    h, w = frames[0].shape[:2]
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), max(fps, 1.0), (w, h))
    if not vw.isOpened():
        return ""
    for f in frames:
        vw.write(f if f.ndim == 3 else cv2.cvtColor(f, cv2.COLOR_GRAY2BGR))
    vw.release()
    return path


def journal_write(out_dir: str, row: list) -> None:
    path = os.path.join(out_dir, JOURNAL)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(JOURNAL_HEAD)
        w.writerow(row)


# ── утренний разбор ───────────────────────────────────────────────────────────

def report(out_dir: str) -> int:
    """Группируем сработки по ночам: ночь считаем с полудня до полудня."""
    path = os.path.join(out_dir, JOURNAL)
    if not os.path.exists(path):
        print("Журнал пуст — сторож ещё ни одной ночи не отработал.")
        return 0
    nights: dict = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ts = datetime.fromisoformat(row["время"])
            night = (ts - timedelta(hours=12)).date()
            nights.setdefault(night, []).append((ts, row))
    for night in sorted(nights):
        events = sorted(nights[night])
        print(f"\nНочь с {night:%d.%m} на {night + timedelta(days=1):%d.%m} — "
              f"сработок: {len(events)}")
        for ts, row in events:
            print(f"   {ts:%H:%M:%S}  {float(row['длина_мм']):.1f} мм, "
                  f"путь {float(row['путь_мм']):.1f} мм, "
                  f"уверенность {float(row['уверенность']):.0%}"
                  f"   {os.path.basename(row['видео'] or row['фото'])}")
    print("\nГде гуще всего сработки — там и гнездо. Двигай камеру туда.")
    return 0


# ── основной цикл ─────────────────────────────────────────────────────────────

def watch(args) -> int:
    os.makedirs(args.out, exist_ok=True)
    cap, is_file = open_source(args.source)
    cfg = DetectorConfig(
        fov_width_mm=args.fov_width_mm,
        dark_threshold=args.threshold,
        min_travel_mm=args.min_travel_mm,
    )
    det = BugDetector(cfg)

    prebuf = deque(maxlen=max(int(args.pre * args.fps), 1))
    clip: list = []
    post_left = 0
    clip_name = ""

    started = time.time()
    last_seen = 0.0
    last_alert = -1e9
    frames = alerts = 0
    sizes: list = []
    peak = 0.0

    mode = "КАЛИБРОВКА (тревог не будет)" if args.calibrate else "ОХРАНА"
    ch = "есть" if alert.configured() else "нет — сигнал только в журнал и папку"
    print(f"[{mode}] источник {args.source}, кадр {args.fov_width_mm:.0f} мм по ширине, "
          f"{args.fps:g} к/с, Telegram: {ch}")
    print("Ctrl+C — закончить и показать итог.\n")

    while not _stop:
        ok, frame = cap.read()
        if not ok:
            if is_file:
                break
            time.sleep(0.5)                       # камера моргнула — ждём и пробуем ещё
            continue

        now = (cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0) if is_file else time.time()
        if not is_file and now - last_seen < 1.0 / args.fps:
            continue                              # прореживаем поток до рабочей частоты
        last_seen = now
        frames += 1

        prebuf.append(frame)
        if post_left > 0:
            clip.append(frame)
            post_left -= 1
            if post_left == 0:
                write_clip(clip_name, clip, args.fps)
                clip = []

        d = det.feed(frame, now)
        if args.calibrate:
            sizes += [b.length_mm for b in det.last_blobs]
            if det.best:
                peak = max(peak, det.best.score)
            if frames % int(args.fps * 20) == 0:
                _calib_line(frames, sizes, det, peak=peak)
            continue

        if not d or now - last_alert < args.cooldown:
            continue

        last_alert = now
        alerts += 1
        stamp = datetime.fromtimestamp(now if not is_file else time.time())
        base = os.path.join(args.out, stamp.strftime("%Y-%m-%d_%H-%M-%S"))
        photo = base + ".jpg"
        cv2.imwrite(photo, annotate(frame, d))
        clip_name = base + ".mp4"
        clip = list(prebuf)
        post_left = max(int(args.post * args.fps), 1)

        text = f"🛏 Движение на простыне в {stamp:%H:%M:%S}\n{d.describe()}"
        print(f"  ! {stamp:%H:%M:%S}  {d.describe()}")
        journal_write(args.out, [stamp.isoformat(timespec="seconds"),
                                 f"{d.length_mm:.2f}", f"{d.travel_mm:.2f}",
                                 f"{d.speed_mm_s:.2f}", f"{d.score:.2f}",
                                 photo, clip_name])
        if args.sound:
            alert.beep()
        if not args.no_telegram:
            alert.send_photo(photo, text) or alert.send_text(text)

    if post_left > 0 and clip:
        write_clip(clip_name, clip, args.fps)
    cap.release()

    hours = (time.time() - started) / 3600
    print(f"\nОтработано {hours:.1f} ч, кадров {frames}, сработок {alerts}.")
    if args.calibrate:
        _calib_line(frames, sizes, det, final=True, peak=peak)
    elif alerts:
        print(f"Улики в {args.out}. Разбор: python3 watcher.py --report")
    else:
        print("Тихо. Либо их нет в кадре, либо камера смотрит не туда — "
              "переставь её ближе к шву матраса и повтори.")
    return 0


def _calib_line(frames: int, sizes: list, det: BugDetector,
                final: bool = False, peak: float = 0.0) -> None:
    """В калибровке важны две вещи: попадают ли пятна в диапазон 1.5–9 мм
    и до какой вероятности они дотягивают — то же число, что в браузере."""
    tag = "ИТОГ" if final else f"кадр {frames}"
    if not sizes:
        print(f"  [{tag}] пятен подходящего размера не видно. "
              f"Шум кадра {det.last_change_frac:.3%} — "
              f"{'слишком много света/движения' if det.last_change_frac > 0.02 else 'кадр спокойный'}")
        return
    arr = np.array(sizes)
    print(f"  [{tag}] пятен {len(arr)}, длина тела: "
          f"мин {arr.min():.1f} / медиана {np.median(arr):.1f} / макс {arr.max():.1f} мм; "
          f"лучшая вероятность {peak:.0%}; шум кадра {det.last_change_frac:.3%}")
    if peak and det.last_reason:
        print(f"         разбор последнего кандидата: {det.last_reason}")


def main() -> int:
    p = argparse.ArgumentParser(description="Ночной сторож против клопов")
    p.add_argument("--source", default="0", help="0 = USB-камера, rtsp://…, или файл видео")
    p.add_argument("--fov-width-mm", type=float, default=200.0,
                   help="сколько миллиметров простыни влезает в кадр по ширине")
    p.add_argument("--fps", type=float, default=10.0, help="рабочая частота кадров")
    p.add_argument("--threshold", type=int, default=18, help="насколько пятно темнее фона")
    p.add_argument("--min-travel-mm", type=float, default=2.0, help="сколько должно проползти")
    p.add_argument("--cooldown", type=float, default=120.0, help="пауза между тревогами, с")
    p.add_argument("--pre", type=float, default=6.0, help="секунд ролика ДО сработки")
    p.add_argument("--post", type=float, default=10.0, help="секунд ролика ПОСЛЕ")
    p.add_argument("--out", default=DEFAULT_OUT, help="куда складывать улики и журнал")
    p.add_argument("--sound", action="store_true", help="пищать в комнате")
    p.add_argument("--no-telegram", action="store_true", help="молчать в Telegram")
    p.add_argument("--calibrate", action="store_true", help="ночь настройки без тревог")
    p.add_argument("--report", action="store_true", help="утренний разбор журнала")
    args = p.parse_args()

    signal.signal(signal.SIGINT, _on_sigint)
    return report(args.out) if args.report else watch(args)


if __name__ == "__main__":
    sys.exit(main())
