"""Проверка детектора на синтетических «простынях» — камера для этого не нужна.

Запуск:  python3 test_detector.py
Выход 0 — все сценарии прошли, иначе печатает, что именно сломалось.

Сценарии подобраны так, чтобы ловить обе беды сразу: и пропуск настоящего
клопа, и ложную тревогу от крошки, складки или того, что ты повернулся.
"""
import sys

import cv2
import numpy as np

from detector import BugDetector, DetectorConfig

W, H = 960, 540
FPS = 10.0
CFG = DetectorConfig(fov_width_mm=200.0)     # 4.8 пикселя на миллиметр
PX_MM = W / CFG.fov_width_mm


def sheet(seed: int = 7) -> np.ndarray:
    """Простыня в инфракрасном свете: светлая, шумная, с крошками и складкой."""
    rng = np.random.default_rng(seed)
    img = np.full((H, W), 200, np.uint8)
    img = cv2.add(img, rng.normal(0, 3, (H, W)).astype(np.int16).clip(-30, 30).astype(np.uint8))
    for cx, cy in ((120, 90), (700, 400), (430, 300)):        # неподвижные крошки
        cv2.circle(img, (cx, cy), 8, 70, -1)
    cv2.line(img, (0, 470), (W, 500), 150, 2)                 # складка простыни
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def crawl(img, x, y, length_mm=5.0):
    """Рисуем клопа: тёмный овал заданной длины тела."""
    a = int(length_mm * PX_MM / 2)
    b = max(int(a * 0.62), 2)
    out = img.copy()
    cv2.ellipse(out, (int(x), int(y)), (a, b), 20, 0, 360, 55, -1)
    return out


def run(frames):
    """Прогоняем список кадров через детектор, возвращаем первую сработку."""
    det = BugDetector(CFG)
    hit = None
    for i, f in enumerate(frames):
        d = det.feed(f, i / FPS)
        if d and hit is None:
            hit = d
    return hit


def warmup(n=30):
    return [sheet() for _ in range(n)]


# ── сценарии ──────────────────────────────────────────────────────────────────

def case_bug_crawls():
    """Клоп 5 мм ползёт со скоростью 2 см/с — обязан сработать."""
    frames = warmup()
    x = 300.0
    for _ in range(12):
        frames.append(crawl(sheet(), x, 250))
        x += 2.0 * PX_MM                                  # 2 мм за кадр = 20 мм/с
    return run(frames), True


def case_nymph_crawls():
    """Личинка 2 мм ползёт медленно — тоже должна ловиться."""
    frames = warmup()
    x = 300.0
    for _ in range(16):
        frames.append(crawl(sheet(), x, 250, length_mm=2.2))
        x += 0.8 * PX_MM
    return run(frames), True


def case_stop_and_go():
    """Пополз — замер — пополз. Так они и ходят на самом деле."""
    frames = warmup()
    x = 300.0
    for _ in range(3):
        for _ in range(2):
            frames.append(crawl(sheet(), x, 250))
            x += 2.0 * PX_MM
        frames += [crawl(sheet(), x, 250) for _ in range(40)]   # стоит 4 с
    return run(frames), True


def case_quiet_night():
    """Просто шум и неподвижные крошки — ни одной тревоги за 200 кадров."""
    return run(warmup(200)), False


def case_crumb_dropped():
    """Упала и лежит крошка нужного размера: похожа на клопа, но не ползёт."""
    frames = warmup()
    frames += [crawl(sheet(), 500, 260) for _ in range(40)]
    return run(frames), False


def case_sleeper_turns():
    """Ты повернулся: полкадра ушло в тень. Это не клоп, это ты."""
    frames = warmup()
    for i in range(30):
        f = sheet()
        f[:, : W // 2] = (f[:, : W // 2] * 0.55).astype(np.uint8)
        if i > 12:                                        # и осталось лежать по-новому
            f[:, : W // 2] = (sheet()[:, : W // 2] * 0.55).astype(np.uint8)
        frames.append(f)
    return run(frames), False


def case_moth():
    """Крупное насекомое 25 мм — по размеру не клоп, тревожить незачем."""
    frames = warmup()
    x = 300.0
    for _ in range(12):
        frames.append(crawl(sheet(), x, 250, length_mm=25.0))
        x += 4.0 * PX_MM
    return run(frames), False


def case_fast_shadow():
    """Быстрая тень через кадр: мошка, штора, блик. Клоп так не бегает."""
    frames = warmup()
    x, step = 30.0, 250.0 / FPS * PX_MM        # 25 см/с — втрое выше потолка
    while x < W - 30:
        frames.append(crawl(sheet(), x, 250))
        x += step
    return run(frames), False


def case_hair():
    """Волос: длинный и тонкий. Размер по длине подходит, форма — нет."""
    frames = warmup()
    x = 300
    for _ in range(12):
        f = sheet()
        cv2.line(f, (int(x), 240), (int(x) + 40, 262), (60, 60, 60), 1)
        frames.append(f)
        x += 8
    return run(frames), False


CASES = [
    ("клоп ползёт",              case_bug_crawls),
    ("личинка ползёт",           case_nymph_crawls),
    ("тихая ночь",               case_quiet_night),
    ("пополз, замер, пополз",    case_stop_and_go),
    ("упавшая крошка",           case_crumb_dropped),
    ("спящий повернулся",        case_sleeper_turns),
    ("крупная моль",             case_moth),
    ("быстрая тень",             case_fast_shadow),
    ("волос на простыне",        case_hair),
]


def check_stays_visible() -> int:
    """Замерший клоп не должен пропадать с экрана. Раньше фон съедал его за
    13 секунд, и пятно исчезало из кандидатов совсем."""
    det = BugDetector(CFG)
    for i, f in enumerate(warmup()):
        det.feed(f, i / FPS)
    x = 400.0
    for i in range(4):
        det.feed(crawl(sheet(), x, 250), (30 + i) / FPS)
        x += 2.0 * PX_MM
    gone = None
    for i in range(400):
        det.feed(crawl(sheet(), x, 250), (34 + i) / FPS)
        if not det.candidates:
            gone = i / FPS
            break
    ok = gone is None
    mark = "✓" if ok else "✗"
    detail = "виден все 50 с простоя" if ok else f"ПРОПАЛ через {gone:.1f} с"
    print(f" {mark} {'замерший не пропадает':22} {detail}")
    return 0 if ok else 1


def main() -> int:
    bad = 0
    for name, fn in CASES:
        hit, want = fn()
        ok = bool(hit) == want
        bad += not ok
        mark = "✓" if ok else "✗"
        detail = hit.describe() if hit else "тихо"
        expect = "" if ok else f"   ← ожидали {'тревогу' if want else 'тишину'}"
        print(f" {mark} {name:22} {detail}{expect}")
    bad += check_stays_visible()
    print()
    print("Все сценарии прошли." if not bad else f"Провалено сценариев: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
