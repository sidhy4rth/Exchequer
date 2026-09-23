"""The film's own score: a dark bed built on the beat grid the cuts are locked to.

The bundled "Happy Beats / Business Moves" track was the most generic thing in
the video -- corporate optimism under a cyber-crime film -- and its licence
would have to be cleared before the video is posted anywhere. This replaces it
with a bed written for this cut: a D-minor drone, a pad that changes chord on
each scene cut, a half-time pulse on the music's own beats, and a sub drop on
every hard cut. No samples, no licence, nothing to clear.

The beat times come from the same cue preset the composition's cuts were locked
to, so a pulse never drifts away from a reveal.

    python score.py            # writes composition/assets/music/bed.wav

Deterministic: fixed seed, no clock, same bytes every run.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48_000
DUR = 38.4                      # the film is 37.94s; the tail rings past the end
N = int(SR * DUR)
T = np.arange(N) / SR

HERE = Path(__file__).resolve().parent
CUES = Path.home() / ".claude/plugins/marketplaces/brag/skills/brag/assets/music/cues" \
    / "happy-beats-business-moves-vol-11-by-ende-dot-app.music-cues.json"
OUT = HERE / "composition/assets/music/bed.wav"
TARGET_LUFS = -14.3            # the loudness of the bundled track this replaces

# The scene cuts, in seconds. Each one gets a sub drop and a chord change.
CUTS = [5.28, 12.95, 17.39, 21.60, 28.44, 33.71]
RISERS = [17.39, 33.71]         # the two biggest turns

# The investigating figure: a four-note ostinato on eighth notes that follows
# the chord under it. It enters when the trace starts -- the search -- tightens
# under the sanctions sweep, thins to downbeats once the answer is found, stops
# dead under the stance so those three lines land in the clear, and returns to
# resolve under the mark.
OSTINATO = [
    (0.00,  5.28, None),                                     # before the search
    (5.28, 12.95, [146.83, 220.00, 174.61, 220.00]),         # Dm  - the trace
    (12.95, 17.39, [110.00, 164.81, 220.00, 164.81]),        # Am  - the map opens
    (17.39, 21.60, [116.54, 174.61, 146.83, 174.61]),        # Bb  - screening
    (21.60, 28.44, [174.61, 261.63, 220.00, 261.63]),        # F   - the report
    (28.44, 33.71, None),                                    # the stance: silence
    (33.71, 38.40, [146.83, 220.00, 174.61, 293.66]),        # Dm  - the mark
]
SPARSE = (21.60, 28.44)        # once it is found, the figure stops hunting
PICKUP = [4.76, 5.02]          # two plucks lead into the first cut

# D minor. Root movement per section: Dm - Dm(add C) - Bb - F - D5 - Dm(add9).
# The Bb under "screened" is the darkest chord in the piece; the F under the
# report is the only lift; the stance strips to root and fifth.
SECTIONS = [
    (0.00,  5.28, [73.42, 146.83, 174.61, 220.00]),
    (5.28, 12.95, [73.42, 146.83, 174.61, 220.00, 261.63]),
    (12.95, 17.39, [110.00, 164.81, 220.00, 261.63]),
    (17.39, 21.60, [58.27, 116.54, 146.83, 174.61]),
    (21.60, 28.44, [87.31, 130.81, 174.61, 220.00]),
    (28.44, 33.71, [73.42, 110.00, 146.83]),
    (33.71, DUR, [73.42, 146.83, 174.61, 220.00, 329.63]),
]

rng = np.random.default_rng(20260920)


def sl(start: float, dur: float):
    """Sample slice for [start, start+dur), clipped to the buffer."""
    i0 = max(0, int(start * SR))
    i1 = min(N, i0 + int(dur * SR))
    return i0, i1


def one_pole(x: np.ndarray, cutoff: float) -> np.ndarray:
    """Cheap low-pass; enough to take the edge off saw harmonics and noise."""
    a = math.exp(-2.0 * math.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(x.size):                      # vectorised via lfilter would
        acc = (1 - a) * x[i] + a * acc           # need scipy; this is fast
        y[i] = acc                               # enough for 33s at 48k
    return y


def voice(freq: float, i0: int, i1: int, amp: float, fade: float, detune: float = 0.0) -> np.ndarray:
    """A pad voice: fundamental plus two quiet harmonics, cosine-faded."""
    n = i1 - i0
    if n <= 0:
        return np.zeros(0)
    t = np.arange(n) / SR
    f = freq * (1.0 + detune)
    # a slow, shallow drift keeps the sustain from sounding like a test tone
    drift = 1.0 + 0.0016 * np.sin(2 * math.pi * 0.07 * t + freq)
    sig = (np.sin(2 * math.pi * f * drift * t)
           + 0.46 * np.sin(2 * math.pi * 2 * f * drift * t)
           + 0.30 * np.sin(2 * math.pi * 3 * f * drift * t)
           + 0.17 * np.sin(2 * math.pi * 4 * f * drift * t)
           + 0.10 * np.sin(2 * math.pi * 5 * f * drift * t)
           + 0.05 * np.sin(2 * math.pi * 7 * f * drift * t))
    k = max(1, int(fade * SR))
    env = np.ones(n)
    k = min(k, n // 2)
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, math.pi, k))
    env[:k] = ramp
    env[-k:] = ramp[::-1]
    return amp * env * sig


def pluck(freq: float, t0: float, amp: float, decay: float = 7.0):
    """A short plucked note: fast attack, quick decay, a metallic top."""
    i0, i1 = sl(t0, 0.62)
    n = i1 - i0
    if n <= 0:
        return None
    t = np.arange(n) / SR
    env = np.exp(-t * decay) * (1.0 - np.exp(-t * 900.0))
    sig = (np.sin(2 * math.pi * freq * t)
           + 0.55 * np.sin(2 * math.pi * 2 * freq * t) * np.exp(-t * 12)
           + 0.30 * np.sin(2 * math.pi * 3 * freq * t) * np.exp(-t * 20)
           + 0.14 * np.sin(2 * math.pi * 4.7 * freq * t) * np.exp(-t * 34))
    return i0, i1, amp * env * sig


def main() -> None:
    beats = [b["time"] for b in json.loads(CUES.read_text())["beats"] if b["time"] < DUR]

    # eighth notes: the music's own beats, plus the midpoint of each pair
    eighths = []
    for i in range(len(beats) - 1):
        eighths.append((beats[i], True))
        eighths.append(((beats[i] + beats[i + 1]) / 2.0, False))
    eighths.append((beats[-1], True))

    left = np.zeros(N)
    right = np.zeros(N)

    # --- the drone: D1 and D2 under the whole piece, breathing slowly
    swell = 0.55 + 0.45 * (0.5 - 0.5 * np.cos(2 * math.pi * T / 9.0))
    drone = (0.105 * np.sin(2 * math.pi * 36.71 * T)
             + 0.085 * np.sin(2 * math.pi * 73.42 * T)
             + 0.042 * np.sin(2 * math.pi * 110.0 * T))
    drone *= swell
    # ease the drone in over the first bar so the film does not start on a hum
    intro = np.clip(T / 1.6, 0, 1)
    drone *= intro
    left += drone
    right += drone

    # --- the pad: one chord per section, crossfaded across the cut
    for (s0, s1, chord) in SECTIONS:
        i0, i1 = sl(s0 - 0.55, (s1 - s0) + 1.1)
        for k, f in enumerate(chord):
            amp = 0.11 if f < 100 else 0.21 / (1 + 0.55 * k)
            left[i0:i1] += voice(f, i0, i1, amp, 0.55, detune=-0.0013 * (k + 1))
            right[i0:i1] += voice(f, i0, i1, amp, 0.55, detune=+0.0013 * (k + 1))
            if f >= 100 and k < 4:      # an octave above keeps the chord audible small
                left[i0:i1] += voice(f * 2, i0, i1, amp * 0.45, 0.7, detune=+0.0022)
                right[i0:i1] += voice(f * 2, i0, i1, amp * 0.45, 0.7, detune=-0.0022)
            if f >= 140 and k < 3:      # and a shimmer two octaves up, barely there
                left[i0:i1] += voice(f * 4, i0, i1, amp * 0.15, 0.9, detune=-0.0031)
                right[i0:i1] += voice(f * 4, i0, i1, amp * 0.15, 0.9, detune=+0.0031)

    # --- the pulse: half-time, on the music's own beats, stronger on the downbeat
    for bi, bt in enumerate(beats):
        if bt < 1.4 or bi % 2:
            continue
        strong = (bi % 8 == 0)
        i0, i1 = sl(bt, 0.34)
        n = i1 - i0
        if n <= 0:
            continue
        t = np.arange(n) / SR
        decay = np.exp(-t * 26)
        # a short sine thump with a falling pitch, plus a whisper of noise
        pitch = 78 - 26 * np.clip(t / 0.05, 0, 1)
        body = np.sin(2 * math.pi * np.cumsum(pitch) / SR) * decay
        tick = rng.normal(0, 1, n) * np.exp(-t * 70) * 0.13
        amp = 0.30 if strong else 0.17
        left[i0:i1] += amp * (body + tick)
        right[i0:i1] += amp * (body + tick)

    # --- the investigating figure
    counters = {}
    for (et, on_beat) in eighths:
        notes = None
        for (s0, s1, chord) in OSTINATO:
            if s0 <= et < s1:
                notes, key = chord, s0
                break
        if notes is None:
            continue
        idx = counters.get(key, 0)
        counters[key] = idx + 1
        if (s0, s1) == SPARSE and idx % 4:      # downbeats only once it is found
            continue
        amp = 0.42 if (idx % 4 == 0) else (0.28 if on_beat else 0.20)
        hit = pluck(notes[idx % len(notes)], et, amp)
        if hit:
            i0, i1, sig = hit
            left[i0:i1] += sig
            right[i0:i1] += sig * 0.94
    for pt in PICKUP:                            # two notes leading into the cut
        hit = pluck(220.00, pt, 0.26)
        if hit:
            i0, i1, sig = hit
            left[i0:i1] += sig
            right[i0:i1] += sig

    # --- the figure's own off-beat tick, while the search is running
    for (et, on_beat) in eighths:
        if on_beat or not (5.28 <= et < 28.44):
            continue
        i0, i1 = sl(et, 0.05)
        n = i1 - i0
        if n <= 0:
            continue
        t = np.arange(n) / SR
        nz = rng.normal(0, 1, n)
        click = (nz - one_pole(nz, 2400)) * np.exp(-t * 150) * 0.075
        left[i0:i1] += click
        right[i0:i1] += click * 0.88

    # --- telemetry: sixteenth ticks while the sanctions bar sweeps the ledger
    tick_t = 17.59
    while tick_t < 19.05:
        i0, i1 = sl(tick_t, 0.035)
        n = i1 - i0
        if n > 0:
            t = np.arange(n) / SR
            nz = rng.normal(0, 1, n)
            click = (nz - one_pole(nz, 3200)) * np.exp(-t * 240) * 0.10
            left[i0:i1] += click
            right[i0:i1] += click * 0.9
        tick_t += 0.1306                          # sixteenths at 114.84 BPM

    # --- sub drops on the hard cuts
    for ct in CUTS:
        i0, i1 = sl(ct, 1.4)
        n = i1 - i0
        t = np.arange(n) / SR
        pitch = 64 * np.exp(-t * 2.4) + 32
        sub = np.sin(2 * math.pi * np.cumsum(pitch) / SR) * np.exp(-t * 3.0)
        left[i0:i1] += 0.19 * sub
        right[i0:i1] += 0.19 * sub

    # --- risers into the two big turns
    for rt in RISERS:
        i0, i1 = sl(rt - 1.15, 1.15)
        n = i1 - i0
        t = np.arange(n) / SR
        x = t / max(t[-1], 1e-9)
        noise = rng.normal(0, 1, n)
        swept = one_pole(noise, 200) * (1 - x) + one_pole(noise, 3000) * x
        riser = swept * (x ** 2.2) * 0.30
        left[i0:i1] += riser
        right[i0:i1] += riser * 0.92

    # --- air: a thin band of noise across the whole piece, barely there, so the
    # mix has a top end on a phone speaker instead of dying above 400 Hz
    air = rng.normal(0, 1, N)
    air = air - one_pole(air, 2200)                 # high-passed by subtraction
    air *= 0.030 * (0.6 + 0.4 * np.sin(2 * math.pi * T / 6.5))
    left += air
    right += np.roll(air, 211)                      # decorrelated for width

    # --- air above the mark, for the last beat only
    i0, i1 = sl(28.97, DUR - 28.97)
    for f, a in ((587.33, 0.055), (880.00, 0.034), (1174.66, 0.016)):
        left[i0:i1] += voice(f, i0, i1, a, 1.2, detune=-0.002)
        right[i0:i1] += voice(f, i0, i1, a, 1.2, detune=+0.002)

    # --- a little room: convolve with a short exponential-decay impulse
    ir_n = int(1.6 * SR)
    ir = rng.normal(0, 1, ir_n) * np.exp(-np.linspace(0, 7.5, ir_n))
    ir = one_pole(ir, 2600)
    ir /= np.abs(ir).sum() / 24.0
    wet_l = np.convolve(left, ir)[:N]
    wet_r = np.convolve(right, ir)[:N]
    left = 0.84 * left + 0.16 * wet_l
    right = 0.84 * right + 0.16 * wet_r

    # The fade at the end belongs to the composition's volume lane, not to this
    # file: fading here too would cancel the swell the lane rides under the mark.

    stereo = np.stack([left, right], axis=1)
    peak = float(np.abs(stereo).max())
    stereo = np.tanh(stereo / max(peak, 1e-9) * 1.25) * 0.88   # soft limit
    OUT.parent.mkdir(parents=True, exist_ok=True)
    raw = OUT.with_name("bed-raw.wav")
    sf.write(raw, stereo, SR, subtype="PCM_16")

    # Match the loudness of the track this replaces (-14.3 LUFS), so the
    # composition's ducking lane keeps the values it was tuned with.
    measure = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(raw), "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True)
    integrated = float(re.findall(r"I:\s+(-?\d+\.\d+) LUFS", measure.stderr)[-1])
    gain = TARGET_LUFS - integrated
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                    "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", str(OUT)], check=True)
    raw.unlink()
    print(f"wrote {OUT}  {DUR:.1f}s  peak {peak:.2f}  beats {len(beats)}  "
          f"{integrated:+.1f} -> {TARGET_LUFS:+.1f} LUFS ({gain:+.2f} dB)")


if __name__ == "__main__":
    main()
