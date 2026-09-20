"""Детектор клопа в кадре: маленькое тёмное пятно, которое ПОЛЗЁТ.

Ключевая идея. Отличить клопа от крошки, ворсинки, тени или шума матрицы
по одному кадру невозможно — все они одинаковые тёмные точки. Отличает их
движение: клоп ползёт (примерно 1–4 см/с), а крошка лежит. Поэтому детектор
не «узнаёт клопа на картинке», а ищет пятно нужного РАЗМЕРА, которое живёт
несколько кадров подряд и успевает уползти на пару миллиметров.

Каждому пятну в каждом кадре выставляется вероятность 0..1:

    вероятность = внешность × движение
    внешность   = размер тела и форма (овал, а не нитка)
    движение    = живучесть × (путь + скорость)

Произведение выбрано не случайно: неподвижная крошка правильного размера
получает честный ноль, а не «половину за внешность». Тревога поднимается,
когда вероятность дотянула до порога fire_score.

Все пороги заданы в миллиметрах, а не в пикселях: достаточно один раз
измерить линейкой, сколько сантиметров простыни попадает в кадр по ширине
(параметр fov_width_mm), и настройки перестают зависеть от камеры.

Что детектор НЕ умеет: видеть клопа на общем плане комнаты. При 5 мм длины
тела нужно ~5 пикселей на миллиметр, то есть кадр шириной 20–30 см. Это
камера-макро над одним участком простыни, а не обзорная камера над кроватью.

Формулы и пороги держим слово в слово такими же, как в web/detector.js:
одни и те же кадры обязаны давать один и тот же процент в обеих версиях.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class DetectorConfig:
    """Пороги детектора. Всё, что в миллиметрах, — реальные размеры на простыне."""

    fov_width_mm: float = 200.0      # сколько мм простыни влезает в кадр по ширине
    bug_len_mm: Tuple[float, float] = (1.5, 9.0)    # личинка … взрослый клоп
    bug_len_best: Tuple[float, float] = (3.0, 6.0)  # тело взрослого — полный балл
    min_short_ratio: float = 0.25    # тело овальное; отсекает волосы и складки
    min_fill: float = 0.30           # заполненность рамки: отсекает нитки и царапины
    dark_threshold: int = 18         # насколько пятно темнее фона (0..255)
    bg_alpha: float = 0.02           # скорость забывания фона в покое
    settle_alpha: float = 0.35       # ускоренное забывание после шевеления
    warmup_frames: int = 20          # кадры на построение фона, тревоги не даём
    max_change_frac: float = 0.02    # >2% кадра изменилось — это ты повернулся
    settle_frames: int = 15          # столько кадров после шевеления не верим себе
    min_hits: int = 4                # столько кадров жить на полный балл
    min_travel_mm: float = 2.0       # столько проползти на полный балл
    speed_mm_s: Tuple[float, float] = (0.2, 130.0)  # ползёт 1–4 см/с, вспугнутый — до 12
    speed_best_mm_s: Tuple[float, float] = (3.0, 45.0)  # обычный шаг — полный балл
    match_radius_mm: float = 18.0    # на столько пятно может сместиться за кадр
    miss_limit: int = 5              # столько кадров без пятна — трек закрыт
    fire_score: float = 0.70         # с какой вероятности будить


@dataclass
class Detection:
    """Сработка: где, когда и насколько уверенно."""

    ts: float
    x: int
    y: int
    w: int
    h: int
    length_mm: float
    travel_mm: float
    speed_mm_s: float
    frames: int
    score: float
    why: str = ""

    def describe(self) -> str:
        return (
            f"тело ~{self.length_mm:.1f} мм, проползло {self.travel_mm:.1f} мм "
            f"со скоростью {self.speed_mm_s:.1f} мм/с за {self.frames} кадров "
            f"(вероятность {self.score:.0%})"
        )


@dataclass
class _Track:
    """Одно пятно, прослеженное через несколько кадров."""

    x: float
    y: float
    start_x: float
    start_y: float
    first_ts: float
    last_ts: float
    length_mm: float
    ratio: float = 0.0
    fill: float = 0.0
    hits: int = 1
    misses: int = 0
    path_mm: float = 0.0
    jump_mm: float = 0.0
    box: Tuple[int, int, int, int] = (0, 0, 0, 0)
    fired: bool = False
    score: float = 0.0


@dataclass
class _Blob:
    x: float
    y: float
    length_mm: float
    ratio: float
    fill: float
    box: Tuple[int, int, int, int]


@dataclass
class Candidate:
    """Что сейчас в кадре: рамка, вероятность и разбор, чего не хватает."""

    box: Tuple[int, int, int, int]
    score: float
    why: str
    length_mm: float
    travel_mm: float
    speed_mm_s: float
    frames: int
    jump_mm: float


def _clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def _band(v: float, lo: float, best_lo: float, best_hi: float, hi: float) -> float:
    """Трапеция: 0 вне [lo,hi], 1 внутри [best_lo,best_hi], плавный переход."""
    if v <= lo or v >= hi:
        return 0.0
    if best_lo <= v <= best_hi:
        return 1.0
    return (v - lo) / (best_lo - lo) if v < best_lo else (hi - v) / (hi - best_hi)


class BugDetector:
    """Скармливай кадры через feed(); в ответ получаешь Detection или None."""

    def __init__(self, config: Optional[DetectorConfig] = None):
        self.cfg = config or DetectorConfig()
        self.px_per_mm = 0.0
        self.frame_idx = 0
        self.settle_left = 0
        self._bg: Optional[np.ndarray] = None
        self._tracks: List[_Track] = []
        self.last_mask: Optional[np.ndarray] = None
        self.last_blobs: List[_Blob] = []
        self.last_change_frac = 0.0
        self.candidates: List[Candidate] = []
        self.best: Optional[Candidate] = None

    # ── публичный вход ────────────────────────────────────────────────────────

    def feed(self, frame: np.ndarray, ts: float) -> Optional[Detection]:
        """Один кадр (BGR или серый) и его время в секундах."""
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        if self._bg is None:
            self.px_per_mm = gray.shape[1] / self.cfg.fov_width_mm
            self._bg = gray.astype(np.float32)

        self.frame_idx += 1
        bg_u8 = cv2.convertScaleAbs(self._bg)

        # Клоп темнее простыни, поэтому берём только «потемнения», а не любой diff:
        # так блик от фонаря или засветка экрана телефона не считаются насекомым.
        dark = cv2.subtract(bg_u8, gray)
        _, mask = cv2.threshold(dark, self.cfg.dark_threshold, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        self.last_mask = mask

        self.last_change_frac = float(np.count_nonzero(mask)) / mask.size
        disturbed = self.last_change_frac > self.cfg.max_change_frac

        if disturbed:
            # Ты повернулся, поправил одеяло или включился свет: полкадра «потемнело».
            # Верить такому кадру нельзя — сбрасываем треки и быстро переучиваем фон.
            self.settle_left = self.cfg.settle_frames
            self._tracks.clear()
            self.last_blobs = []
            self.candidates = []
            self.best = None

        alpha = self.cfg.settle_alpha if self.settle_left > 0 else self.cfg.bg_alpha
        cv2.accumulateWeighted(gray.astype(np.float32), self._bg, alpha)

        if self.settle_left > 0:
            self.settle_left -= 1
            return None
        if self.frame_idx <= self.cfg.warmup_frames or disturbed:
            return None

        blobs = self._blobs(mask)
        self.last_blobs = blobs
        return self._track(blobs, ts)

    def reset(self) -> None:
        self._bg = None
        self._tracks.clear()
        self.candidates = []
        self.best = None
        self.frame_idx = 0
        self.settle_left = 0

    # ── разбор кадра ──────────────────────────────────────────────────────────

    def _blobs(self, mask: np.ndarray) -> List[_Blob]:
        """Пятна подходящего размера и формы. Всё лишнее отсеиваем здесь."""
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out: List[_Blob] = []
        lo, hi = self.cfg.bug_len_mm
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            long_mm = max(w, h) / self.px_per_mm
            short_mm = min(w, h) / self.px_per_mm
            ratio = short_mm / long_mm if long_mm else 0.0
            fill = cv2.contourArea(c) / (w * h) if w and h else 0.0
            if not (lo <= long_mm <= hi):
                continue                                  # крошка или рука — мимо
            if ratio < self.cfg.min_short_ratio:
                continue                                  # волос или складка простыни
            if fill < self.cfg.min_fill:
                continue                                  # нитка, царапина, контур тени
            out.append(_Blob(x + w / 2, y + h / 2, long_mm, ratio, fill, (x, y, w, h)))
        return out

    def _track(self, blobs: List[_Blob], ts: float) -> Optional[Detection]:
        """Сшиваем пятна с уже известными треками и решаем, ползёт ли оно."""
        radius = self.cfg.match_radius_mm * self.px_per_mm
        free = list(blobs)
        # Где пятна были в прошлом кадре — чтобы отличить «новое пятно» от «то же
        # самое, но прыгнувшее слишком далеко».
        prev = [(t.x, t.y) for t in self._tracks]

        for tr in self._tracks:
            best, best_d = None, radius
            for b in free:
                d = float(np.hypot(b.x - tr.x, b.y - tr.y))
                if d < best_d:
                    best, best_d = b, d
            if best is None:
                tr.misses += 1
                continue
            free.remove(best)
            tr.path_mm += best_d / self.px_per_mm
            tr.x, tr.y = best.x, best.y
            tr.box = best.box
            tr.length_mm = best.length_mm
            tr.ratio, tr.fill = best.ratio, best.fill
            tr.last_ts = ts
            tr.hits += 1
            tr.misses = 0

        self._tracks = [t for t in self._tracks if t.misses <= self.cfg.miss_limit]
        for b in free:
            near = min((float(np.hypot(b.x - px, b.y - py)) for px, py in prev),
                       default=float("inf"))
            jump = near / self.px_per_mm if radius < near < radius * 8 else 0.0
            self._tracks.append(
                _Track(b.x, b.y, b.x, b.y, ts, ts, b.length_mm,
                       ratio=b.ratio, fill=b.fill, box=b.box, jump_mm=jump)
            )

        return self._evaluate()

    # ── вероятность ───────────────────────────────────────────────────────────

    def _rate(self, tr: _Track) -> Tuple[float, str, float, float]:
        """Вероятность для трека плюс разбор, чего ему не хватает."""
        cfg = self.cfg
        net_mm = float(np.hypot(tr.x - tr.start_x, tr.y - tr.start_y)) / self.px_per_mm
        dt = max(tr.last_ts - tr.first_ts, 1e-6)
        speed = tr.path_mm / dt if tr.hits > 1 else 0.0

        f_size = _band(tr.length_mm, cfg.bug_len_mm[0], cfg.bug_len_best[0],
                       cfg.bug_len_best[1], cfg.bug_len_mm[1])
        f_ratio = _clamp01((tr.ratio - cfg.min_short_ratio) / (0.55 - cfg.min_short_ratio))
        f_fill = _clamp01((tr.fill - cfg.min_fill) / (0.70 - cfg.min_fill))
        f_shape = 0.5 * f_ratio + 0.5 * f_fill
        f_life = min(tr.hits / cfg.min_hits, 1.0)
        f_travel = min(net_mm / cfg.min_travel_mm, 1.0)
        f_speed = _band(speed, cfg.speed_mm_s[0], cfg.speed_best_mm_s[0],
                        cfg.speed_best_mm_s[1], cfg.speed_mm_s[1])

        look = 0.6 * f_size + 0.4 * f_shape
        move = f_life * (0.5 * f_travel + 0.5 * f_speed)
        score = look * move

        # Пятно, прыгнувшее дальше радиуса сшивки, выглядит как новорождённый трек.
        # Говорим правду: дело не в том, что оно стоит, а в том, что оно летит.
        if tr.hits <= 2 and tr.jump_mm > 0:
            return (score, f"прыгает {tr.jump_mm:.0f} мм за кадр — быстрее, чем "
                           f"детектор успевает сшить (предел {cfg.match_radius_mm:.0f} мм). "
                           f"Веди медленнее", net_mm, speed)

        if speed >= cfg.speed_mm_s[1]:
            speed_word = f"скорость {speed:.0f} мм/с — выше потолка {cfg.speed_mm_s[1]:.0f}"
        elif speed <= cfg.speed_mm_s[0]:
            speed_word = "стоит на месте"
        else:
            speed_word = f"скорость {speed:.1f} мм/с"
        parts = [
            (f"живёт {tr.hits} из {cfg.min_hits} кадров", f_life),
            (f"проползло {net_mm:.1f} из {cfg.min_travel_mm} мм", f_travel),
            (speed_word, f_speed),
            (f"тело {tr.length_mm:.1f} мм", f_size),
            ("форма пятна", f_shape),
        ]
        weak = sorted((p for p in parts if p[1] < 0.9), key=lambda p: p[1])
        why = ", ".join(f"{t} ({f:.0%})" for t, f in weak[:2])
        return score, why, net_mm, speed

    def _evaluate(self) -> Optional[Detection]:
        """Считаем всех, показываем всех, будим — того, кто дотянул до порога."""
        self.candidates = []
        hit: Optional[Detection] = None
        for tr in self._tracks:
            score, why, net_mm, speed = self._rate(tr)
            tr.score = score
            self.candidates.append(Candidate(
                box=tr.box, score=score, why=why, length_mm=tr.length_mm,
                travel_mm=net_mm, speed_mm_s=speed, frames=tr.hits, jump_mm=tr.jump_mm))
            if not tr.fired and score >= self.cfg.fire_score and hit is None:
                tr.fired = True
                x, y, w, h = tr.box
                hit = Detection(ts=tr.last_ts, x=x, y=y, w=w, h=h,
                                length_mm=tr.length_mm, travel_mm=net_mm,
                                speed_mm_s=speed, frames=tr.hits,
                                score=round(score, 2), why=why)
        # При равной вероятности вперёд пускаем того, кто прыгнул: его разбор
        # объясняет причину, а «стоит на месте» у соседнего нуля — нет.
        self.candidates.sort(key=lambda c: (-c.score, -c.jump_mm))
        self.best = self.candidates[0] if self.candidates else None
        return hit

    @property
    def last_reason(self) -> str:
        """Разбор самого вероятного кандидата — для строки состояния."""
        return self.best.why if self.best else ""
