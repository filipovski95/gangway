# Makes Plume's notification sounds (short, gentle, original) as 16-bit mono WAV files.
# Usage: python3 tools/make_sounds.py   -> brand/res/raw/plume_chime.wav, brand/res/raw/plume_water.wav
import math, struct, wave, os
RATE = 44100
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "brand", "res", "raw")

def write(name, samples):
    os.makedirs(OUT, exist_ok=True)
    peak = max(1e-9, max(abs(s) for s in samples))
    with wave.open(os.path.join(OUT, name), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(s / peak * 0.85 * 32767)) for s in samples))

def bell(freq, start, dur, total, amp=1.0):
    """A soft bell partial: sine with a few harmonics and an exponential decay."""
    out = [0.0] * total
    for i in range(int(start * RATE), min(total, int((start + dur) * RATE))):
        t = i / RATE - start
        env = min(1, t / 0.006) * math.exp(-t * 5.5)
        v = math.sin(2 * math.pi * freq * t) + 0.35 * math.sin(2 * math.pi * freq * 2.01 * t) * math.exp(-t * 3) + 0.12 * math.sin(2 * math.pi * freq * 3.02 * t)
        out[i] = amp * env * v
    return out

# Chime: two rising notes (E6 then B6), warm and short. Used for shot day and other reminders.
total = int(1.1 * RATE)
a = bell(1318.5, 0.00, 1.0, total, 1.0)
b = bell(1975.5, 0.14, 0.95, total, 0.8)
write("plume_chime.wav", [x + y for x, y in zip(a, b)])

# Water drop: a quick falling "bloop" plus a tiny second drop.
def drop(start, f0, f1, dur, amp, total):
    out = [0.0] * total; ph = 0.0
    for i in range(int(start * RATE), min(total, int((start + dur) * RATE))):
        t = i / RATE - start
        f = f1 + (f0 - f1) * math.exp(-t * 28)   # pitch sweeps quickly, like a droplet
        ph += 2 * math.pi * f / RATE
        env = min(1, t / 0.003) * math.exp(-t * 18)
        out[i] = amp * env * math.sin(ph)
    return out
total = int(0.6 * RATE)
d1 = drop(0.00, 600, 1500, 0.35, 1.0, total)
d2 = drop(0.17, 800, 1900, 0.30, 0.55, total)
write("plume_water.wav", [x + y for x, y in zip(d1, d2)])
print("sounds written")
