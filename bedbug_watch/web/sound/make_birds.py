"""Генератор звука тревоги: цвириканье птицы.

Почему синтез, а не запись: чужие записи птиц почти все под лицензией, а
здесь нужна петля, которая замыкается без склейки и начинается с тишины.

Как устроена птичья трель. Отдельный слог — это почти чистый тон, частота
которого быстро едет вверх или вверх-вниз за сотню миллисекунд. Поэтому
слог строится как синус, фаза которого есть накопленный интеграл от кривой
частоты; гармоники добавляются слабо — птицы звучат чище любого синтезатора.

Петля замыкается сама собой: фраза начинается и заканчивается тишиной, а
первый слог — далёкий и тихий, так что вход получается мягким.

Запуск:  python3 make_birds.py
Результат: birds.mp3 (моно, 32 кГц) рядом с этим файлом.
"""
import os

import numpy as np
import soundfile as sf

SR = 32000          # птичьи обертоны живут до 10 кГц, выше не нужно
DUR = 9.0           # длина цикла, с
BASE = os.path.dirname(os.path.abspath(__file__))

N = int(SR * DUR)
out = np.zeros(N)
rng = np.random.default_rng(20260921)


def syllable(dur, path, amp=1.0, harm=0.22, warble=0.0):
    """Один слог: тон с едущей частотой. path — опорные точки частоты в Гц."""
    n = max(int(dur * SR), 8)
    u = np.linspace(0.0, 1.0, n)
    f = np.interp(u, np.linspace(0.0, 1.0, len(path)), path)
    if warble:                                  # лёгкая дрожь голоса
        f = f * (1.0 + warble * np.sin(2 * np.pi * 95 * u * dur))
    ph = 2 * np.pi * np.cumsum(f) / SR
    y = np.sin(ph) + harm * np.sin(2 * ph) + 0.07 * np.sin(3 * ph)
    env = np.sin(np.pi * u) ** 0.55             # быстрый вход, мягкий спад
    return y * env * amp


def far(y, mix=0.55):
    """Птица подальше: глуше и с коротким отражением от стен двора."""
    b = np.zeros_like(y)
    acc = 0.0
    for i, v in enumerate(y):                   # однополюсный фильтр верха
        acc += 0.28 * (v - acc)
        b[i] = acc
    d = int(0.035 * SR)
    echo = np.zeros(len(y) + d)
    echo[:len(y)] += b
    echo[d:] += b * 0.35
    return echo[:len(y)] * mix


def place(y, t0, distant=False):
    i0 = int(t0 * SR)
    seg = far(y) if distant else y
    i1 = min(N, i0 + len(seg))
    if i1 > i0:
        out[i0:i1] += seg[:i1 - i0]


def trill(t0, count, step, path, amp, jitter=0.15, distant=False):
    """Очередь коротких слогов — то самое «цвирь-цвирь-цвирь»."""
    t = t0
    for k in range(count):
        wobble = 1.0 + rng.uniform(-0.05, 0.05)
        p = [f * wobble for f in path]
        place(syllable(0.045 + rng.uniform(0, 0.02), p, amp * rng.uniform(0.8, 1.0)),
              t, distant)
        t += step * (1.0 + rng.uniform(-jitter, jitter))


# ── фраза на девять секунд: входит тихо, к середине оживает, к концу стихает ──
place(syllable(0.13, [3100, 4300, 3500], 0.30, warble=0.01), 0.85, distant=True)
place(syllable(0.10, [3400, 4600], 0.34), 1.95, distant=True)

place(syllable(0.12, [2900, 4500, 3800], 0.62, warble=0.012), 2.95)
trill(3.30, 5, 0.105, [4200, 5400], 0.52)

place(syllable(0.15, [3200, 5100, 4000], 0.85, warble=0.015), 4.10)
trill(4.45, 7, 0.095, [4500, 5800], 0.72)
place(syllable(0.09, [5200, 3900], 0.58), 5.25)

place(syllable(0.14, [2800, 4200, 3300], 0.55, warble=0.01), 5.85, distant=True)
trill(6.25, 4, 0.115, [3900, 5000], 0.46)

place(syllable(0.11, [3300, 4400, 3600], 0.34), 7.35, distant=True)
place(syllable(0.10, [3000, 4100], 0.24), 8.30, distant=True)

# Едва слышный воздух двора: без него слоги висят в вакууме
air = rng.normal(size=N)
spec = np.fft.rfft(air)
f = np.fft.rfftfreq(N, 1 / SR)
spec *= 1.0 / (1.0 + (np.maximum(f, 1e-6) / 2400.0) ** 3)
spec *= 1.0 / (1.0 + (700.0 / np.maximum(f, 1e-6)) ** 3)
air = np.fft.irfft(spec, n=N)
out += air / (np.max(np.abs(air)) + 1e-9) * 0.012

out = np.tanh(out * 1.1) / np.tanh(1.1)
out /= np.max(np.abs(out)) + 1e-9
out *= 0.89

edge = int(0.04 * SR)                          # страховка стыка петли
ramp = np.sin(np.linspace(0, np.pi / 2, edge)) ** 2
out[:edge] *= ramp
out[-edge:] *= ramp[::-1]

path = os.path.join(BASE, "birds.mp3")
sf.write(path, out.astype(np.float32), SR, format="MP3",
         bitrate_mode="VARIABLE", compression_level=0.4)
rms = lambda a: float(np.sqrt(np.mean(a ** 2)))
print(f"{path}  {os.path.getsize(path) / 1024:.0f} КБ, {DUR:g} с, {SR} Гц")
print(f"пик {np.max(np.abs(out)):.3f}, начало {rms(out[:int(1.5*SR)]):.4f}, "
      f"середина {rms(out[int(4.0*SR):int(5.5*SR)]):.4f}")
