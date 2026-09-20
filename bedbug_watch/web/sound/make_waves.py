"""Генератор звука тревоги: море, бьющее в камни.

Почему синтез, а не запись: чужие записи прибоя почти все под лицензией, а
здесь нужен звук, который бесшовно зацикливается и начинается с тишины.

Цикл строится так, чтобы петля была идеальной без склейки. Шумовые подложки
получаются обратным преобразованием Фурье из заданного спектра, а такой сигнал
периодичен по самой своей природе — конец буфера переходит в начало без щелчка.
Огибающие тоже периодичны: все всплески успевают затухнуть до конца круга.

Начало цикла приходится на самую тихую точку отката волны, поэтому звук
входит мягко даже без дополнительного затухания в плеере.

Запуск:  python3 make_waves.py
Результат: waves.mp3 (моно, 32 кГц) рядом с этим файлом.
"""
import os

import numpy as np
import soundfile as sf

SR = 32000          # выше не нужно: у прибоя всё интересное ниже 10 кГц
DUR = 9.0           # длина цикла, с — просили не меньше пяти
BASE = os.path.dirname(os.path.abspath(__file__))

N = int(SR * DUR)
t = np.arange(N) / SR
rng = np.random.default_rng(20260920)


def colored(lo_hz, hi_hz, slope=0.0, seed=0):
    """Шум с заданной полосой. Через спектр — чтобы буфер был периодичен."""
    r = np.random.default_rng(seed)
    spec = r.normal(size=N // 2 + 1) + 1j * r.normal(size=N // 2 + 1)
    f = np.fft.rfftfreq(N, 1 / SR)
    # Мягкие скаты по краям полосы: резкие срезы звучат как телефонный фильтр
    gain = np.ones_like(f)
    with np.errstate(divide="ignore"):
        gain *= 1.0 / (1.0 + (np.maximum(f, 1e-6) / hi_hz) ** 4)          # сверху
        gain *= 1.0 / (1.0 + (lo_hz / np.maximum(f, 1e-6)) ** 4)          # снизу
    if slope:
        gain *= (np.maximum(f, 20.0) / 1000.0) ** slope
    gain[0] = 0.0
    y = np.fft.irfft(spec * gain, n=N)
    return y / (np.max(np.abs(y)) + 1e-9)


def burst(center, attack, decay, sharp=1.0):
    """Всплеск: быстрый подъём, длинный хвост. К концу круга затухает в ноль."""
    e = np.zeros(N)
    a0, a1 = center - attack, center
    rise = (t >= a0) & (t < a1)
    e[rise] = ((t[rise] - a0) / attack) ** 2
    tail = t >= a1
    e[tail] = np.exp(-((t[tail] - a1) / decay) ** sharp)
    return e


def clatter(t0, t1, count, seed):
    """Галька, перекатываемая откатом: редкие короткие щелчки."""
    r = np.random.default_rng(seed)
    e = np.zeros(N)
    for _ in range(count):
        c = r.uniform(t0, t1)
        d = r.uniform(0.012, 0.045)
        i0 = int(c * SR)
        i1 = min(N, i0 + int(d * SR))
        if i1 <= i0:
            continue
        e[i0:i1] += np.exp(-np.linspace(0, 5, i1 - i0)) * r.uniform(0.3, 1.0)
    return np.clip(e, 0, 1.5)


# ── дыхание волны: один накат за цикл, минимум ровно на стыке ───────────────
swell = (0.5 - 0.5 * np.cos(2 * np.pi * t / DUR)) ** 1.6

# ── слои ────────────────────────────────────────────────────────────────────
rumble = colored(25, 240, seed=1) * (0.30 + 0.70 * swell) * 0.9      # тело воды
approach = colored(250, 1400, seed=2) * swell ** 1.4 * 0.55          # накат
# Удары в камни: главный на гребне и два поменьше — вода находит разные камни
hit_main = colored(400, 5200, seed=3) * burst(4.15, 0.10, 0.95) * 0.95
hit_2 = colored(600, 6500, seed=4) * burst(5.05, 0.05, 0.55) * 0.42
hit_3 = colored(500, 4200, seed=5) * burst(5.85, 0.06, 0.40) * 0.28
# Брызги и пена: живут дольше удара и медленно шипят на откате
foam = colored(2200, 9500, seed=6) * (burst(4.20, 0.14, 2.60, 0.8) * 0.34
                                      + swell ** 3 * 0.10)
gravel = colored(900, 3800, seed=7) * clatter(6.0, 8.4, 34, 8) * 0.22

mix = rumble + approach + hit_main + hit_2 + hit_3 + foam + gravel

# Лёгкое смягчение пиков, чтобы удар не резал ухо на максимальной громкости
mix = np.tanh(mix * 1.15) / np.tanh(1.15)
mix /= np.max(np.abs(mix)) + 1e-9
mix *= 0.89

# Страховка стыка: первые и последние 40 мс сводим к нулю по касательной.
# Подложки и так периодичны, но арифметика с плавающей точкой прощает не всё.
edge = int(0.04 * SR)
ramp = np.sin(np.linspace(0, np.pi / 2, edge)) ** 2
mix[:edge] *= ramp
mix[-edge:] *= ramp[::-1]

out = os.path.join(BASE, "waves.mp3")
sf.write(out, mix.astype(np.float32), SR, format="MP3", bitrate_mode="VARIABLE",
         compression_level=0.4)
print(f"{out}  {os.path.getsize(out) / 1024:.0f} КБ, {DUR:g} с, {SR} Гц")
print(f"пик {np.max(np.abs(mix)):.3f}, действующее значение {np.sqrt(np.mean(mix**2)):.3f}")
print(f"уровень в начале {np.sqrt(np.mean(mix[:SR//2]**2)):.4f}, "
      f"на гребне {np.sqrt(np.mean(mix[int(4.0*SR):int(4.5*SR)]**2)):.4f}")
