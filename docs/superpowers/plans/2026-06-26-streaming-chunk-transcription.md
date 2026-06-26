# Streaming Chunk Transcription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in mode where pauses in speech are detected while the hotkey is held, so accumulated audio is transcribed and pasted in chunks as the user speaks, instead of only after release.

**Architecture:** Two new testable units in `voice_typer.py` — `ChunkDetector` (pure voice-activity logic: feed audio blocks, get back completed chunks at pause/max-length boundaries) and `ChunkTranscriber` (a single-worker FIFO queue that transcribes and pastes chunks strictly in order). The existing non-streaming path is left untouched; streaming is selected at key-down based on a config flag.

**Tech Stack:** Python 3, numpy, sounddevice, requests, keyboard, pyperclip, pystray; pytest for unit tests.

## Global Constraints

- Single-file script: all production code goes in `voice_typer.py` (root). No new runtime modules.
- No new runtime dependencies — `pytest` is dev-only (already installed; not added to `requirements.txt`).
- Config path resolution must keep using `_app_dir()` / `load_config()` — never `Path(__file__).parent` for user files.
- Hot-reload contract: per-chunk values (`groq_api_key`, `proxy`, `paste_mode`, `voice_replacements`) read fresh via `load_config()` at transcription time; per-utterance values (`streaming`, `pause_threshold`, `max_chunk_seconds`, `silence_threshold`) read fresh at key-down.
- Audio format is fixed: `SAMPLE_RATE = 16000`, mono, int16.
- Config defaults (exact): `streaming` = `false`, `pause_threshold` = `0.8`, `max_chunk_seconds` = `15`, `silence_threshold` = `0.01`. Internal `min_voice_seconds` = `0.3`.
- Run tests with `python -m pytest` from the repo root (puts root on `sys.path` so `import voice_typer` resolves).

---

### Task 1: `rms_normalized()` + `ChunkDetector` (pure VAD logic)

**Files:**
- Modify: `voice_typer.py` (add after `AudioRecorder`, around line 128, before `# --- Автозамены ---`)
- Test: `tests/test_chunk_detector.py` (create)

**Interfaces:**
- Consumes: `SAMPLE_RATE` (module constant, `16000`), `numpy as np` (already imported).
- Produces:
  - `rms_normalized(block: np.ndarray) -> float` — normalized RMS (0..1) of an int16 block; `0.0` for empty.
  - `class ChunkDetector` with:
    - `__init__(self, sample_rate, pause_threshold, max_chunk_seconds, silence_threshold, min_voice_seconds=0.3)`
    - `feed(self, block: np.ndarray) -> np.ndarray | None` — append a block; return a completed chunk (concatenated int16 array) at a pause or max-length boundary, else `None`.
    - `flush(self) -> np.ndarray | None` — return the trailing chunk if it contains enough voice, else `None`; always resets internal state.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chunk_detector.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chunk_detector.py -v`
Expected: FAIL — `ImportError: cannot import name 'ChunkDetector' from 'voice_typer'`.

- [ ] **Step 3: Write the implementation**

In `voice_typer.py`, insert this block immediately after the `AudioRecorder` class (after its `save_wav` method, before the `# --- Автозамены ---` comment):

```python
# --- Детекция пауз (VAD) ---

def rms_normalized(block):
    """RMS-громкость int16-блока, нормализованная в 0..1 (32768 = максимум)."""
    if block.size == 0:
        return 0.0
    x = block.astype(np.float64)
    return float(np.sqrt(np.mean(x * x))) / 32768.0


class ChunkDetector:
    """Накапливает аудио-блоки и отдаёт готовый чанк на границе паузы или
    по достижении максимальной длины. Чистая логика, без звука и сети."""

    def __init__(self, sample_rate, pause_threshold, max_chunk_seconds,
                 silence_threshold, min_voice_seconds=0.3):
        self._sample_rate = sample_rate
        self._pause_threshold = pause_threshold
        self._max_chunk_seconds = max_chunk_seconds
        self._silence_threshold = silence_threshold
        self._min_voice_seconds = min_voice_seconds
        self._reset()

    def _reset(self):
        self._frames = []
        self._silence_run = 0.0
        self._voice_seconds = 0.0

    def _emit(self):
        chunk = np.concatenate(self._frames, axis=0)
        self._reset()
        return chunk

    def feed(self, block):
        block_seconds = len(block) / self._sample_rate
        self._frames.append(block)
        if rms_normalized(block) >= self._silence_threshold:
            self._voice_seconds += block_seconds
            self._silence_run = 0.0
        else:
            self._silence_run += block_seconds

        if self._voice_seconds < self._min_voice_seconds:
            return None
        total = sum(len(f) for f in self._frames) / self._sample_rate
        if self._silence_run >= self._pause_threshold:
            return self._emit()
        if total >= self._max_chunk_seconds:
            return self._emit()
        return None

    def flush(self):
        if self._voice_seconds >= self._min_voice_seconds:
            return self._emit()
        self._reset()
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chunk_detector.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add voice_typer.py tests/test_chunk_detector.py
git commit -m "feat: add ChunkDetector VAD logic for streaming transcription"
```

---

### Task 2: `ChunkTranscriber` (ordered single-worker queue)

**Files:**
- Modify: `voice_typer.py` (add after `ChunkDetector`, before `# --- Автозамены ---`)
- Modify: `voice_typer.py` top imports — add `import queue`
- Test: `tests/test_chunk_transcriber.py` (create)

**Interfaces:**
- Consumes: `threading` (already imported), `queue` (added this task).
- Produces:
  - `class ChunkTranscriber` with:
    - `__init__(self, handle_chunk)` — `handle_chunk` is `callable(chunk, is_first: bool) -> None`.
    - `start(self) -> None` — launch the daemon worker (idempotent: no-op if already started).
    - `submit(self, chunk, is_first) -> None` — enqueue a chunk; matches `AudioRecorder`'s `on_chunk` signature.
    - `wait_idle(self) -> None` — block until the queue is fully drained.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chunk_transcriber.py`:

```python
import time
from voice_typer import ChunkTranscriber


def test_chunks_processed_in_order_despite_latency():
    results = []

    def handle(chunk, is_first):
        # Earlier items "take longer" — a single worker must still keep order.
        time.sleep(0.05 if chunk == "a" else 0.0)
        results.append(chunk)

    t = ChunkTranscriber(handle)
    t.start()
    t.submit("a", True)
    t.submit("b", False)
    t.submit("c", False)
    t.wait_idle()
    assert results == ["a", "b", "c"]


def test_is_first_flag_passed_through():
    seen = []

    def handle(chunk, is_first):
        seen.append((chunk, is_first))

    t = ChunkTranscriber(handle)
    t.start()
    t.submit("x", True)
    t.submit("y", False)
    t.wait_idle()
    assert seen == [("x", True), ("y", False)]


def test_handler_exception_does_not_stall_queue():
    results = []

    def handle(chunk, is_first):
        if chunk == "boom":
            raise RuntimeError("transcription failed")
        results.append(chunk)

    t = ChunkTranscriber(handle)
    t.start()
    t.submit("boom", True)
    t.submit("ok", False)
    t.wait_idle()
    assert results == ["ok"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chunk_transcriber.py -v`
Expected: FAIL — `ImportError: cannot import name 'ChunkTranscriber' from 'voice_typer'`.

- [ ] **Step 3: Write the implementation**

In `voice_typer.py`, add `import queue` to the stdlib import block at the top (near `import threading`):

```python
import queue
import threading
```

Then insert this class immediately after `ChunkDetector` (before `# --- Автозамены ---`):

```python
class ChunkTranscriber:
    """Один фоновый поток + FIFO-очередь. Чанки обрабатываются строго по
    порядку, даже если расшифровка по сети возвращается вразнобой."""

    def __init__(self, handle_chunk):
        self._handle = handle_chunk
        self._queue = queue.Queue()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, chunk, is_first):
        self._queue.put((chunk, is_first))

    def wait_idle(self):
        self._queue.join()

    def _run(self):
        while True:
            chunk, is_first = self._queue.get()
            try:
                self._handle(chunk, is_first)
            except Exception:
                pass
            finally:
                self._queue.task_done()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chunk_transcriber.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add voice_typer.py tests/test_chunk_transcriber.py
git commit -m "feat: add ChunkTranscriber ordered worker queue"
```

---

### Task 3: Wire streaming into AudioRecorder and main()

**Files:**
- Modify: `voice_typer.py` — `AudioRecorder` (lines ~89-127), `main()` recorder/transcriber setup and `on_key_event` (lines ~304-378)

**Interfaces:**
- Consumes: `ChunkDetector`, `ChunkTranscriber` (Tasks 1-2); `transcribe_groq`, `apply_replacements`, `paste_text`, `load_config`, `tray`, `args`, `_cli_auto_type` (existing).
- Produces (new `AudioRecorder` members):
  - `self.streaming: bool` attribute (default `False`).
  - `start_streaming(self, detector, on_chunk) -> None` — start an `InputStream` that feeds `detector` and calls `on_chunk(chunk, is_first)` for each emitted chunk.
  - `flush_final(self) -> None` — emit the detector's trailing chunk (no-op when not streaming).
  - module-level `write_wav(path, audio) -> None` — write an int16 mono array to a WAV file.

This task is integration wiring around real audio I/O and keyboard hooks, so it is verified manually rather than by unit test. Make the edits, then run the manual checks in Step 5.

- [ ] **Step 1: Add `write_wav` and refactor `save_wav` to use it**

Replace the existing `save_wav` method (lines ~117-127) so the WAV-writing logic is shared. First add a module-level helper just above the `AudioRecorder` class (after the `_hook_lock = threading.Lock()` line, ~line 87):

```python
def write_wav(path, audio):
    import wave
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16 = 2 bytes
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
```

Then change `AudioRecorder.save_wav` to delegate:

```python
    def save_wav(self, path):
        if not self.frames:
            return False
        audio = np.concatenate(self.frames, axis=0)
        write_wav(path, audio)
        return True
```

- [ ] **Step 2: Extend `AudioRecorder` for streaming**

Replace `AudioRecorder.__init__`, `start`, and `_callback` and add the two new methods. The class becomes:

```python
class AudioRecorder:
    def __init__(self):
        self.frames = []
        self.recording = False
        self.streaming = False
        self._stream = None
        self._detector = None
        self._on_chunk = None
        self._chunk_index = 0

    def start(self):
        self.frames = []
        self.recording = True
        self.streaming = False
        self._detector = None
        self._on_chunk = None
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def start_streaming(self, detector, on_chunk):
        self.frames = []
        self.recording = True
        self.streaming = True
        self._detector = detector
        self._on_chunk = on_chunk
        self._chunk_index = 0
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def _emit_chunk(self, chunk):
        is_first = (self._chunk_index == 0)
        self._chunk_index += 1
        self._on_chunk(chunk, is_first)

    def _callback(self, indata, frames, time_info, status):
        if not self.recording:
            return
        if self._detector is not None:
            chunk = self._detector.feed(indata.copy())
            if chunk is not None:
                self._emit_chunk(chunk)
        else:
            self.frames.append(indata.copy())

    def stop(self):
        self.recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def flush_final(self):
        if self._detector is None:
            return
        chunk = self._detector.flush()
        if chunk is not None:
            self._emit_chunk(chunk)

    def save_wav(self, path):
        if not self.frames:
            return False
        audio = np.concatenate(self.frames, axis=0)
        write_wav(path, audio)
        return True
```

- [ ] **Step 3: Add the chunk handler and transcriber in `main()`**

In `main()`, immediately after the existing `recorder = AudioRecorder()` line (~line 304), add the per-chunk handler and start the transcriber. The handler mirrors `process_audio`'s config reads but pastes a single chunk and never sets the tray to idle (recording is still in progress):

```python
    def handle_chunk(chunk, is_first):
        fresh = load_config()
        current_api_key = fresh.get("groq_api_key") or os.environ.get("GROQ_API_KEY")
        if current_api_key == "gsk_your_key_here":
            current_api_key = None
        if not current_api_key:
            tray.set_state("error")
            tray.notify(
                "Voice Typer — нет API ключа",
                "Открой config.json через меню трея и добавь groq_api_key",
                force=True,
            )
            return
        current_proxy = fresh.get("proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        current_auto_type = _cli_auto_type or (fresh.get("paste_mode", "clipboard") == "type")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            write_wav(tmp_path, chunk)
            text = transcribe_groq(tmp_path, current_api_key, args.lang, current_proxy)
            if text:
                rules = fresh.get("voice_replacements", [])
                if rules:
                    text = apply_replacements(text, rules)
                if not is_first:
                    text = " " + text
                if args.debug:
                    print(f"[debug] chunk: {text}")
                paste_text(text, current_auto_type)
        except Exception as ex:
            tray.set_state("error")
            tray.notify("Voice Typer — Ошибка", str(ex), force=True)
            if args.debug:
                print(f"[debug] chunk error: {ex}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    transcriber = ChunkTranscriber(handle_chunk)
    transcriber.start()
```

- [ ] **Step 4: Branch `on_key_event` on streaming mode**

Replace the body of `on_key_event` (the `KEY_DOWN`/`KEY_UP` branch, lines ~370-378) with a version that selects streaming at key-down and drains the queue at key-up:

```python
    def on_key_event(e):
        if args.debug:
            print(f"[debug] {e.event_type}: name={e.name!r} scan_code={e.scan_code}", flush=True)
        if e.name != cfg["trigger_key"]:
            return
        if e.event_type == keyboard.KEY_DOWN and not is_recording.is_set() and modifiers_held():
            is_recording.set()
            fresh = load_config()
            if fresh.get("streaming", False):
                detector = ChunkDetector(
                    SAMPLE_RATE,
                    float(fresh.get("pause_threshold", 0.8)),
                    float(fresh.get("max_chunk_seconds", 15)),
                    float(fresh.get("silence_threshold", 0.01)),
                )
                recorder.start_streaming(detector, transcriber.submit)
            else:
                recorder.start()
            tray.set_state("recording")
        elif e.event_type == keyboard.KEY_UP and is_recording.is_set():
            is_recording.clear()
            if recorder.streaming:
                recorder.stop()
                recorder.flush_final()
                tray.set_state("processing")

                def _drain():
                    transcriber.wait_idle()
                    tray.set_state("idle")

                threading.Thread(target=_drain, daemon=True).start()
            else:
                recorder.stop()
                tray.set_state("processing")
                threading.Thread(target=process_audio, daemon=True).start()
```

- [ ] **Step 5: Verify existing unit tests still pass, then manual smoke test**

Run: `python -m pytest -v`
Expected: PASS (all tests from Tasks 1-2 still green).

Manual (requires a configured `config.json` with a valid `groq_api_key`):

1. Set `"streaming": false` (or omit). Hold hotkey, say one phrase, release → text pastes once after release (unchanged behavior).
2. Set `"streaming": true`. Click "Перечитать конфиг" is not needed (read at key-down). Hold hotkey, say "первая фраза" — pause ~1s — "вторая фраза", release → first phrase pastes mid-hold, second pastes after, separated by a space, in order.
3. With `"streaming": true`, hold and speak continuously >15s without pausing → text appears in ~15s chunks without releasing.
4. Confirm tray icon: red while held, amber after release until the last chunk pastes, then grey.

- [ ] **Step 6: Commit**

```bash
git add voice_typer.py
git commit -m "feat: wire streaming chunk transcription into recorder and hotkey loop"
```

---

### Task 4: Config example + documentation

**Files:**
- Modify: `config.example.json`
- Modify: `CLAUDE.md` (Config Fields section, ~lines 40-52)
- Modify: `README.md` (config/usage section)

**Interfaces:**
- Consumes: field names and defaults from Global Constraints.
- Produces: documented config fields `streaming`, `pause_threshold`, `max_chunk_seconds`, `silence_threshold`.

- [ ] **Step 1: Add the new fields to `config.example.json`**

Replace the file contents with:

```json
{
  "groq_api_key": "gsk_your_key_here",
  "hotkey": "f9",
  "paste_mode": "type",
  "proxy": "",
  "streaming": false,
  "pause_threshold": 0.8,
  "max_chunk_seconds": 15,
  "silence_threshold": 0.01,
  "voice_replacements": [
    {"from": "Cloud Code", "to": "Claude Code"},
    {"from": "Codorg[ao]s", "to": "CodOrgOS", "regex": true}
  ]
}
```

- [ ] **Step 2: Document the fields in `CLAUDE.md`**

In the "Config Fields" section, replace the JSON block and add a note. The JSON block becomes:

```json
{
  "groq_api_key": "gsk_...",
  "hotkey": "f9",
  "paste_mode": "clipboard",
  "proxy": "",
  "streaming": false,
  "pause_threshold": 0.8,
  "max_chunk_seconds": 15,
  "silence_threshold": 0.01,
  "voice_replacements": []
}
```

Directly below that block, add:

```markdown
**Streaming mode** (`streaming: true`): detects pauses while the hotkey is held
and transcribes/pastes the audio in chunks as you speak, instead of only after
release. `pause_threshold` = seconds of silence that ends a chunk;
`max_chunk_seconds` = forced flush during long pause-free speech;
`silence_threshold` = normalized RMS (0..1) below which audio counts as silence.
Streaming flags are read fresh at key-down; per-chunk values (`paste_mode`,
`voice_replacements`, etc.) are read fresh per chunk. Trade-off: slightly lower
accuracy on short chunks and more API requests — hence opt-in.
```

- [ ] **Step 3: Document streaming in `README.md`**

Find the section listing `config.json` fields in `README.md` and add the four new fields with a one-line description each, matching the wording in `CLAUDE.md` (streaming mode, pause_threshold, max_chunk_seconds, silence_threshold). Keep the existing formatting style of that section.

- [ ] **Step 4: Commit**

```bash
git add config.example.json CLAUDE.md README.md
git commit -m "docs: document streaming chunk transcription config fields"
```

---

## Notes for the implementer

- **Why a single-worker queue (Task 2):** chunks must paste in the order they were spoken. Spawning a thread per chunk would race — a later chunk could finish transcription first and paste out of order. The single worker guarantees order at the cost of serial (but short) transcriptions.
- **Why `min_voice_seconds` (Task 1):** prevents a single cough/click from becoming its own chunk. It is internal (not config-exposed) to avoid config bloat; change the default in `ChunkDetector.__init__` if needed.
- **`is_first` and spacing:** the first chunk of each hotkey-hold pastes with no leading space; subsequent chunks get a leading space so words don't slip together. `AudioRecorder` resets `_chunk_index` to 0 in `start_streaming`, so each utterance starts fresh.
- **Replacements across chunk boundaries** won't match (a phrase split between two chunks) — accepted limitation of streaming mode, called out in the spec.
