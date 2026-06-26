import numpy as np
from voice_typer import ChunkDetector, rms_normalized, SAMPLE_RATE


def _silence(seconds):
    n = int(SAMPLE_RATE * seconds)
    return np.zeros((n, 1), dtype=np.int16)


def _voice(seconds, amp=3000):
    n = int(SAMPLE_RATE * seconds)
    return np.full((n, 1), amp, dtype=np.int16)


def test_rms_normalized_silence_below_voice():
    assert rms_normalized(_silence(0.1)) == 0.0
    assert rms_normalized(_voice(0.1)) > 0.01


def test_rms_normalized_empty_is_zero():
    assert rms_normalized(np.zeros((0, 1), dtype=np.int16)) == 0.0


def test_emits_chunk_after_pause():
    d = ChunkDetector(SAMPLE_RATE, pause_threshold=0.8,
                      max_chunk_seconds=15, silence_threshold=0.01)
    assert d.feed(_voice(0.5)) is None          # voice, no pause yet
    assert d.feed(_silence(0.5)) is None         # silence_run 0.5 < 0.8
    chunk = d.feed(_silence(0.5))                # silence_run 1.0 >= 0.8 -> emit
    assert chunk is not None
    assert abs(len(chunk) / SAMPLE_RATE - 1.5) < 0.01  # 0.5 + 0.5 + 0.5


def test_no_emit_on_pure_silence():
    d = ChunkDetector(SAMPLE_RATE, 0.8, 15, 0.01)
    assert d.feed(_silence(1.0)) is None
    assert d.feed(_silence(1.0)) is None


def test_max_chunk_flush_without_pause():
    d = ChunkDetector(SAMPLE_RATE, 0.8, max_chunk_seconds=2.0, silence_threshold=0.01)
    assert d.feed(_voice(1.0)) is None
    chunk = d.feed(_voice(1.0))                  # total 2.0 >= max -> emit
    assert chunk is not None
    assert abs(len(chunk) / SAMPLE_RATE - 2.0) < 0.01


def test_resets_after_emit():
    d = ChunkDetector(SAMPLE_RATE, 0.8, 15, 0.01)
    d.feed(_voice(0.5))
    d.feed(_silence(0.5))
    d.feed(_silence(0.5))                        # emit here, state resets
    # new utterance: trailing silence alone must not emit
    assert d.feed(_silence(1.0)) is None


def test_flush_returns_trailing_voice():
    d = ChunkDetector(SAMPLE_RATE, 0.8, 15, 0.01)
    d.feed(_voice(0.5))
    chunk = d.flush()
    assert chunk is not None
    assert abs(len(chunk) / SAMPLE_RATE - 0.5) < 0.01


def test_flush_returns_none_when_no_voice():
    d = ChunkDetector(SAMPLE_RATE, 0.8, 15, 0.01)
    d.feed(_silence(0.5))
    assert d.flush() is None
