"""Offline check of the bandwidth measure and gate in audiopipe.analyse (no network, no data/).

    uv run --project pipeline/audio python -I pipeline/audio/tests/test_bandwidth.py
    (also collected by pytest, if installed)

Regression for the zero-padded smoothing bug: np.convolve(mode="same") padded the dB spectrum
with 0 dB, which lifted the bins under Nyquist so every file's content edge read as Nyquist and
the 18 kHz floor never fired.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from audiopipe import analyse

SR = 48000
NYQ = SR / 2
FMT = {"codec": "pcm_s24le", "sample_rate": SR, "bit_depth": 24}
CLEAN = {"clipped_fraction": 0.0, "clipped_samples": 0, "snr_proxy_db": 60.0, "digital_silence_fraction": 0.0}


def noise(seconds: float = 20.0, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(int(seconds * SR)) * 0.1


def with_floor(y: np.ndarray, db: float = -100.0, seed: int = 2) -> np.ndarray:
    """Add a full-band analogue-style noise floor `db` below the signal, as any real recording has."""
    rms = np.sqrt(np.mean(y ** 2))
    return y + np.random.default_rng(seed).standard_normal(len(y)) * rms * 10 ** (db / 20)


def measure(y: np.ndarray) -> dict:
    return analyse.spectral(y[:, None].astype(np.float32), SR)


def gate(sp: dict) -> tuple[str, str]:
    return analyse.gate("ambience", FMT, {"dc_offset": 0.0}, CLEAN, sp)


def lowpass(y: np.ndarray, hz: float) -> np.ndarray:
    """Steep linear-phase FIR low-pass (a codec/resampler-style wall)."""
    h = signal.firwin(1023, hz, fs=SR, window=("kaiser", 12.0))
    return signal.fftconvolve(y, h, mode="same")


def rolloff(y: np.ndarray, hz: float) -> np.ndarray:
    """Gentle 2nd-order roll-off |H| = 1 / sqrt(1 + (f/hz)^4), no zero at Nyquist."""
    f = np.fft.rfftfreq(len(y), 1 / SR)
    return np.fft.irfft(np.fft.rfft(y) / np.sqrt(1 + (f / hz) ** 4), len(y))


def test_smoothing_is_edge_safe():
    pdb = np.full(1000, -100.0)
    sm = analyse.smooth_db(pdb, 34)
    assert sm.shape == pdb.shape
    assert np.allclose(sm, -100.0), "a flat spectrum must stay flat at the edges (zero padding lifts them)"


def test_full_band_noise_reaches_nyquist():
    sp = measure(with_floor(noise()))
    assert sp["content_edge_hz"] >= 0.95 * NYQ, sp
    assert not sp["brick_wall"], sp
    assert gate(sp)[0] == "accepted"
    assert "flag" not in gate(sp)[1]


def test_full_band_noise_through_an_adc_filter():
    # an ADC anti-alias wall at 22 kHz: content edge just under it, accepted (not lossy)
    sp = measure(with_floor(lowpass(noise(), 22000)))
    assert sp["content_edge_hz"] >= 0.9 * NYQ, sp
    assert gate(sp)[0] == "accepted"
    assert "flag" not in gate(sp)[1]


def test_noise_lowpassed_at_15k_reports_15k_and_is_rejected():
    sp = measure(with_floor(lowpass(noise(), 15000)))
    assert abs(sp["content_edge_hz"] - 15000) <= 600, sp
    assert sp["effective_bandwidth_hz"] < analyse.FLOOR["min_bandwidth_hz"]
    status, reason = gate(sp)
    assert status == "rejected", reason


def test_upsampled_from_16k_rate_is_rejected():
    # an 8 kHz wall sat below the old 8 kHz start of the wall search
    sp = measure(with_floor(lowpass(noise(), 7600)))
    assert abs(sp["content_edge_hz"] - 7600) <= 600, sp
    assert sp["brick_wall"], sp
    assert gate(sp)[0] == "rejected"


def test_dark_source_with_gentle_rolloff_is_flagged_not_rejected():
    # a natural roll-off (2nd-order at 3 kHz, 12 dB/octave, applied in the frequency domain so
    # there is no bilinear zero at Nyquist) over a full-band recording chain
    y = with_floor(rolloff(noise(), 3000), db=-70.0)
    sp = measure(y)
    assert sp["effective_bandwidth_hz"] < analyse.FLOOR["min_bandwidth_hz"], sp
    assert not sp["brick_wall"], sp
    status, reason = gate(sp)
    assert status == "accepted" and "bandwidth flag" in reason and "FLAG" in reason, reason


def test_sparse_events_use_the_loud_frames():
    # bright clicks over a quiet dark background: the median frame is the background,
    # the content edge must come from the events
    bg = rolloff(noise(seed=3), 2000) * 0.01
    y = with_floor(bg, db=-60.0)
    ev = with_floor(noise(0.05, seed=4), db=-100.0)
    for t in range(0, len(y) - len(ev), SR):
        y[t:t + len(ev)] += ev
    sp = measure(y)
    assert sp["content_edge_mean_hz"] >= 0.95 * NYQ, sp
    assert sp["content_edge_median_hz"] < sp["content_edge_mean_hz"], sp
    assert sp["content_edge_hz"] == sp["content_edge_mean_hz"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
