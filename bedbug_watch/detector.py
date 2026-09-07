"""Детектор клопа в кадре: маленькое тёмное пятно, которое ПОЛЗЁТ.

Ключевая идея. Отличить клопа от крошки, ворсинки, тени или шума матрицы
по одному кадру невозможно — все они одинаковые тёмные точки. Отличает их
движение: клоп ползёт (примерно 1–4 см/с), а крошка лежит. Поэтому детектор
не «узнаёт клопа на картинке», а ищет пятно нужного РАЗМЕРА, которое живёт
несколько кадров подряд и успевает уползти на пару миллиметров.

Все пороги заданы в миллиметрах, а не в пикселях: достаточно один раз
измерить линейкой, сколько сантиметров простыни попадает в кадр по ширине
(параметр fov_width_mm), и настройки перестают зависеть от камеры.

Что детектор НЕ умеет: видеть клопа на общем плане комнаты. При 5 мм длины
тела нужно ~5 пикселей на миллиметр, то есть кадр шириной 20–30 см. Это
камера-макро над одним участком простыни, а не обзорная камера над кроватью.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class DetectorConfig:
    """Пороги детектора. Всё, что в миллиметрах, — реальные размеры на простыне."""

    fov_width_mm: float = 200.0      # сколько мм простыни влезает в кадр по ширине
    bug_len_mm: Tuple[float, float] = (1.5, 9.0)   # личинка … взрослый клоп
    min_short_ratio: float = 0.25    # тело овальное; отсекает волосы и складки
    min_fill: float = 0.30           # заполненность рамки: отсекает нитки и царапины
    dark_threshold: int = 18         # насколько пятно темнее фона (0..255)
    bg_alpha: float = 0.02           # скорость забывания фона в покое
    settle_alpha: float = 0.35       # ускоренное забывание после шевеления
    warmup_frames: int = 20          # кадры на построение фона, тревоги не даём
    max_change_frac: float = 0.02    # >2% кадра изменилось — это ты повернулся
    settle_frames: int = 15          # столько кадров после шевеления не верим себе
    min_hits: int = 4                # пятно должно прожить столько кадров
    min_travel_mm: float = 2.0       # и уползти на столько от точки старта
    speed_mm_s: Tuple[float, float] = (0.2, 90.0)  # правдоподобная скорость ползания
    match_radius_mm: float = 12.0    # на столько пятно может сместиться за кадр
    miss_limit: int = 5              # столько кадров без пятна — трек закрыт


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

    def describe(self) -> str:
        return (
            f"тело ~{self.length_mm:.1f} мм, проползло {self.travel_mm:.1f} мм "
            f"со скоростью {self.speed_mm_s:.1f} мм/с за {self.frames} кадров "
            f"(уверенность {self.score:.0%})"
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
    hits: int = 1
    misses: int = 0
    path_mm: float = 0.0
    box: Tuple[int, int, int, int] = (0, 0, 0, 0)
    fired: bool = False


@dataclass
class _Blob:
    x: float
    y: float
    length_mm: float
    box: Tuple[int, int, int, int]


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
        self.last_blobs: List[_Blob] = field(default_factory=list)  # type: ignore[assignment]
        self.last_blobs = []
        self.last_change_frac = 0.0

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
            if not (lo <= long_mm <= hi):
                continue                                  # крошка или рука — мимо
            if short_mm < self.cfg.min_short_ratio * long_mm:
                continue                                  # волос или складка простыни
            if cv2.contourArea(c) < self.cfg.min_fill * w * h:
                continue                                  # нитка, царапина, контур тени
            out.append(_Blob(x + w / 2, y + h / 2, long_mm, (x, y, w, h)))
        return out

    def _track(self, blobs: List[_Blob], ts: float) -> Optional[Detection]:
        """Сшиваем пятна с уже известными треками и решаем, ползёт ли оно."""
        radius = self.cfg.match_radius_mm * self.px_per_mm
        free = list(blobs)

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
            tr.last_ts = ts
            tr.hits += 1
            tr.misses = 0

        self._tracks = [t for t in self._tracks if t.misses <= self.cfg.miss_limit]
        for b in free:
            self._tracks.append(
                _Track(b.x, b.y, b.x, b.y, ts, ts, b.length_mm, box=b.box)
            )

        return self._verdict(ts)

    def _verdict(self, ts: float) -> Optional[Detection]:
        """Трек считается клопом, только если он прожил и реально сместился."""
        for tr in self._tracks:
            if tr.fired or tr.hits < self.cfg.min_hits:
                continue
            net_mm = float(np.hypot(tr.x - tr.start_x, tr.y - tr.start_y)) / self.px_per_mm
            if net_mm < self.cfg.min_travel_mm:
                continue                                  # дрожит на месте — не ползёт
            dt = max(tr.last_ts - tr.first_ts, 1e-6)
            speed = tr.path_mm / dt
            lo, hi = self.cfg.speed_mm_s
            if not (lo <= speed <= hi):
                continue                                  # телепорт или ледник — не клоп
            tr.fired = True
            x, y, w, h = tr.box
            return Detection(
                ts=ts, x=x, y=y, w=w, h=h,
                length_mm=tr.length_mm,
                travel_mm=net_mm,
                speed_mm_s=speed,
                frames=tr.hits,
                score=self._score(tr, net_mm),
            )
        return None

    def _score(self, tr: _Track, net_mm: float) -> float:
        """Грубая уверенность: чем дольше живёт и дальше уползло, тем выше."""
        by_life = min(tr.hits / max(self.cfg.min_hits * 3, 1), 1.0)
        by_travel = min(net_mm / max(self.cfg.min_travel_mm * 4, 0.5), 1.0)
        return round(0.35 + 0.65 * (0.5 * by_life + 0.5 * by_travel), 2)
