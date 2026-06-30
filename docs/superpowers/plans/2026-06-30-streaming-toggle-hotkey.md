# Streaming Toggle Hotkey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework streaming transcription to run on a separate, config-only toggle hotkey (press to start, press to stop — no holding), so chunks paste cleanly while the activation key is NOT held; default off, enabled by one config line.

**Architecture:** Reuse the existing `ChunkDetector` and `ChunkTranscriber` and `AudioRecorder.start_streaming`/`flush_final` (key-agnostic). Extract the now-branchier key handling into a pure, unit-tested `decide_key_action(event_type, key_name, modifiers_ok, state) -> action`; `on_key_event` becomes a thin wrapper that snapshots state, calls the decider, and runs the action. Fix the `pystray` cross-thread crash by serializing `TrayIcon.set_state` with a lock.

**Tech Stack:** Python 3, sounddevice, numpy, keyboard, pyperclip, requests, pystray; pytest for unit tests.

## Global Constraints

- Single-file script: all production code in `voice_typer.py` (root). No new runtime modules or dependencies. `pytest` stays dev-only (not in `requirements.txt`).
- Config: `streaming_hotkey` present and non-empty → streaming enabled on that key; absent/empty (default) → disabled. Parsed by the same `_parse_hotkey` as the main hotkey (supports modifiers, e.g. `"ctrl+f10"`). The old `streaming` boolean field and the "stream while holding F9" path are REMOVED.
- If `streaming_hotkey` resolves to the same trigger+modifiers as the main `hotkey`, streaming is treated as disabled (never hijack the push-to-talk key).
- Interaction: streaming key is TOGGLE on first `KEY_DOWN`; autorepeat `down` while the key is physically held is ignored. Mutual exclusion: while a streaming session is active, main-hotkey presses are ignored; while push-to-talk is recording, the streaming key is ignored.
- Push-to-talk (hold main hotkey → speak → release → one transcription) behavior is unchanged.
- Config defaults: `pause_threshold` = 1.0 (raised from 0.8), `max_chunk_seconds` = 15, `silence_threshold` = 0.01. Streaming params read fresh at session start (toggle-on).
- `keyboard.KEY_DOWN == "down"`, `keyboard.KEY_UP == "up"`.
- Tests run with `python -m pytest` from repo root.

---

### Task 1: `decide_key_action` pure decision function

**Files:**
- Modify: `voice_typer.py` — add module-level function just before `def main():`
- Test: `tests/test_decide_key_action.py` (create)

**Interfaces:**
- Consumes: nothing (pure function, stdlib only).
- Produces:
  - `decide_key_action(event_type: str, key_name: str, modifiers_ok: bool, state: dict) -> str`
    - `event_type`: `"down"` or `"up"`.
    - `state` keys: `"ptt_key"` (str), `"stream_key"` (str | None), `"ptt_recording"` (bool), `"stream_active"` (bool), `"stream_key_held"` (bool).
    - returns one of `"start_ptt"`, `"stop_ptt"`, `"start_stream"`, `"stop_stream"`, `"ignore"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_decide_key_action.py`:

```python
from voice_typer import decide_key_action


def _state(ptt_recording=False, stream_active=False, stream_key_held=False,
           stream_key="f10"):
    return {
        "ptt_key": "f9",
        "stream_key": stream_key,
        "ptt_recording": ptt_recording,
        "stream_active": stream_active,
        "stream_key_held": stream_key_held,
    }


# --- streaming toggle key ---

def test_tap_stream_key_from_idle_starts_stream():
    assert decide_key_action("down", "f10", True, _state()) == "start_stream"


def test_tap_stream_key_during_session_stops_stream():
    assert decide_key_action("down", "f10", True,
                             _state(stream_active=True)) == "stop_stream"


def test_stream_key_autorepeat_is_ignored():
    # physically held -> repeated downs must not toggle
    assert decide_key_action("down", "f10", True,
                             _state(stream_key_held=True)) == "ignore"
    assert decide_key_action("down", "f10", True,
                             _state(stream_active=True, stream_key_held=True)) == "ignore"


def test_stream_key_up_is_ignored():
    assert decide_key_action("up", "f10", True, _state(stream_active=True)) == "ignore"


def test_stream_key_ignored_while_ptt_recording():
    assert decide_key_action("down", "f10", True,
                             _state(ptt_recording=True)) == "ignore"


def test_stream_start_requires_modifiers():
    assert decide_key_action("down", "f10", False, _state()) == "ignore"


def test_stream_stop_does_not_require_modifiers():
    # toggling OFF works even if modifiers aren't held
    assert decide_key_action("down", "f10", False,
                             _state(stream_active=True)) == "stop_stream"


def test_stream_key_none_disables_streaming_branch():
    st = _state(stream_key=None)
    assert decide_key_action("down", "f10", True, st) == "ignore"


# --- push-to-talk key (unchanged behavior) ---

def test_ptt_down_from_idle_starts_ptt():
    assert decide_key_action("down", "f9", True, _state()) == "start_ptt"


def test_ptt_up_while_recording_stops_ptt():
    assert decide_key_action("up", "f9", True, _state(ptt_recording=True)) == "stop_ptt"


def test_ptt_autorepeat_is_ignored():
    assert decide_key_action("down", "f9", True, _state(ptt_recording=True)) == "ignore"


def test_ptt_ignored_while_stream_active():
    assert decide_key_action("down", "f9", True, _state(stream_active=True)) == "ignore"


def test_ptt_down_requires_modifiers():
    assert decide_key_action("down", "f9", False, _state()) == "ignore"


def test_ptt_up_while_not_recording_is_ignored():
    assert decide_key_action("up", "f9", True, _state()) == "ignore"


def test_unrelated_key_is_ignored():
    assert decide_key_action("down", "x", True, _state()) == "ignore"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_decide_key_action.py -v`
Expected: FAIL — `ImportError: cannot import name 'decide_key_action' from 'voice_typer'`.

- [ ] **Step 3: Write the implementation**

In `voice_typer.py`, add this function immediately before `def main():`:

```python
def decide_key_action(event_type, key_name, modifiers_ok, state):
    """Pure decision for a key event. No side effects, no keyboard/audio access.

    event_type: "down" or "up" (== keyboard.KEY_DOWN / keyboard.KEY_UP)
    key_name:   the event's key name (e.name)
    modifiers_ok: required modifiers for the matched key are currently held
    state: dict with ptt_key, stream_key (str|None), ptt_recording,
           stream_active, stream_key_held (bools)
    Returns one of: "start_ptt", "stop_ptt", "start_stream", "stop_stream", "ignore".
    """
    stream_key = state["stream_key"]
    if stream_key is not None and key_name == stream_key:
        if event_type == "down":
            if state["stream_key_held"]:
                return "ignore"          # autorepeat while physically held
            if state["stream_active"]:
                return "stop_stream"     # toggle off
            if state["ptt_recording"]:
                return "ignore"          # mutual exclusion
            if not modifiers_ok:
                return "ignore"
            return "start_stream"        # toggle on
        return "ignore"                  # up — caller clears stream_key_held

    if key_name == state["ptt_key"]:
        if event_type == "down":
            if state["ptt_recording"]:
                return "ignore"          # autorepeat
            if state["stream_active"]:
                return "ignore"          # mutual exclusion
            if not modifiers_ok:
                return "ignore"
            return "start_ptt"
        if state["ptt_recording"]:
            return "stop_ptt"
        return "ignore"

    return "ignore"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_decide_key_action.py -v`
Expected: PASS (15 passed).

- [ ] **Step 5: Commit**

```bash
git add voice_typer.py tests/test_decide_key_action.py
git commit -m "feat: add decide_key_action pure key-routing logic for toggle streaming"
```

---

### Task 2: Wire toggle streaming into main() and fix tray thread-safety

**Files:**
- Modify: `voice_typer.py` — `TrayIcon.__init__` + `set_state`; `main()` hotkey parsing, `cfg`, events, `on_key_event`, `reload_config`.

**Interfaces:**
- Consumes: `decide_key_action` (Task 1); existing `ChunkDetector`, `ChunkTranscriber`, `AudioRecorder.start_streaming/flush_final/start/stop`, `handle_chunk`, `process_audio`, `_parse_hotkey`, `load_config`, `cfg`, `is_recording`.
- Produces (internal): `cfg["stream_trigger"]`/`cfg["stream_modifiers"]`; `stream_active` and `stream_key_held` `threading.Event`s; `TrayIcon._state_lock`.

This task is keyboard/audio/tray wiring with no unit test of its own. Verify via the regression suite and an import check (Step 8). The real mic/tray smoke test needs hardware and is deferred to the human — list the manual steps in the report; do not run them.

- [ ] **Step 1: Serialize `TrayIcon.set_state` with a lock**

In `TrayIcon.__init__`, add the lock. Change:

```python
    def __init__(self, notify_enabled=False):
        self._notify_enabled = notify_enabled
        self._error_timer = None
```

to:

```python
    def __init__(self, notify_enabled=False):
        self._notify_enabled = notify_enabled
        self._error_timer = None
        self._state_lock = threading.Lock()
```

Then wrap the body of `set_state`. Change:

```python
    def set_state(self, state):
        if self._error_timer is not None:
            self._error_timer.cancel()
            self._error_timer = None
        self._icon.icon = make_icon(state)
        if state == "error":
            self._error_timer = threading.Timer(2.0, lambda: self.set_state("idle"))
            self._error_timer.start()
```

to:

```python
    def set_state(self, state):
        with self._state_lock:
            if self._error_timer is not None:
                self._error_timer.cancel()
                self._error_timer = None
            self._icon.icon = make_icon(state)
            if state == "error":
                self._error_timer = threading.Timer(2.0, lambda: self.set_state("idle"))
                self._error_timer.start()
```

(The 2 s error timer fires after `set_state` returns and the lock is free, so there is no re-entrant deadlock — it just serializes against concurrent updates.)

- [ ] **Step 2: Add streaming-hotkey parsing and extend `cfg`**

In `main()`, find:

```python
    def _parse_hotkey(hotkey_str):
        parts = [k.strip().lower() for k in hotkey_str.split("+")]
        return parts[-1], set(parts[:-1])  # trigger_key, modifiers

    initial_config = load_config()
    initial_hotkey = _cli_key if _cli_key is not None else initial_config.get("hotkey", "f9")
    trigger_key, modifiers = _parse_hotkey(initial_hotkey)

    # cfg holds only what affects the keyboard hook (needs re-hook on change)
    cfg = {
        "trigger_key": trigger_key,
        "modifiers":   modifiers,
    }
```

Replace it with:

```python
    def _parse_hotkey(hotkey_str):
        parts = [k.strip().lower() for k in hotkey_str.split("+")]
        return parts[-1], set(parts[:-1])  # trigger_key, modifiers

    def _parse_stream_hotkey(hotkey_str, main_trigger, main_modifiers):
        # Presence + non-empty enables streaming; sharing the main hotkey disables it.
        s = (hotkey_str or "").strip()
        if not s:
            return None, set()
        trig, mods = _parse_hotkey(s)
        if trig == main_trigger and mods == main_modifiers:
            return None, set()
        return trig, mods

    initial_config = load_config()
    initial_hotkey = _cli_key if _cli_key is not None else initial_config.get("hotkey", "f9")
    trigger_key, modifiers = _parse_hotkey(initial_hotkey)
    stream_trigger, stream_modifiers = _parse_stream_hotkey(
        initial_config.get("streaming_hotkey", ""), trigger_key, modifiers)

    # cfg holds only what affects the keyboard hook (read fresh in on_key_event)
    cfg = {
        "trigger_key":      trigger_key,
        "modifiers":        modifiers,
        "stream_trigger":   stream_trigger,
        "stream_modifiers": stream_modifiers,
    }
```

- [ ] **Step 3: Add the streaming state events**

In `main()`, find:

```python
    recorder = AudioRecorder()
    is_recording = threading.Event()
```

Replace with:

```python
    recorder = AudioRecorder()
    is_recording = threading.Event()
    stream_active = threading.Event()
    stream_key_held = threading.Event()
```

- [ ] **Step 4: Replace `on_key_event` with the decider-driven version**

In `main()`, replace the whole existing `on_key_event` function (the one that reads `fresh.get("streaming", False)` and branches on `recorder.streaming`) with these action helpers plus the new thin handler:

```python
    def _start_ptt():
        is_recording.set()
        recorder.start()
        tray.set_state("recording")

    def _stop_ptt():
        is_recording.clear()
        recorder.stop()
        tray.set_state("processing")
        threading.Thread(target=process_audio, daemon=True).start()

    def _start_stream():
        fresh = load_config()
        detector = ChunkDetector(
            SAMPLE_RATE,
            float(fresh.get("pause_threshold", 1.0)),
            float(fresh.get("max_chunk_seconds", 15)),
            float(fresh.get("silence_threshold", 0.01)),
        )
        stream_active.set()
        recorder.start_streaming(detector, transcriber.submit)
        tray.set_state("recording")

    def _stop_stream():
        stream_active.clear()
        recorder.stop()
        recorder.flush_final()
        tray.set_state("processing")

        def _drain():
            transcriber.wait_idle()
            if not is_recording.is_set() and not stream_active.is_set():
                tray.set_state("idle")

        threading.Thread(target=_drain, daemon=True).start()

    def on_key_event(e):
        if args.debug:
            print(f"[debug] {e.event_type}: name={e.name!r} scan_code={e.scan_code}", flush=True)

        stream_key = cfg["stream_trigger"]
        if stream_key and e.name == stream_key:
            mods = cfg["stream_modifiers"]
        elif e.name == cfg["trigger_key"]:
            mods = cfg["modifiers"]
        else:
            return

        modifiers_ok = all(keyboard.is_pressed(m) for m in mods)
        state = {
            "ptt_key":         cfg["trigger_key"],
            "stream_key":      stream_key,
            "ptt_recording":   is_recording.is_set(),
            "stream_active":   stream_active.is_set(),
            "stream_key_held": stream_key_held.is_set(),
        }
        action = decide_key_action(e.event_type, e.name, modifiers_ok, state)

        if action == "start_ptt":
            _start_ptt()
        elif action == "stop_ptt":
            _stop_ptt()
        elif action == "start_stream":
            _start_stream()
        elif action == "stop_stream":
            _stop_stream()

        # Track physical state of the streaming key to suppress autorepeat toggles.
        if stream_key and e.name == stream_key:
            if e.event_type == keyboard.KEY_DOWN:
                stream_key_held.set()
            elif e.event_type == keyboard.KEY_UP:
                stream_key_held.clear()
```

- [ ] **Step 5: Update `reload_config` to re-read both hotkeys**

In `main()`, replace the existing `reload_config` hotkey block. Change:

```python
    def reload_config():
        new_cfg = load_config()

        # Update hotkey (unless CLI --key was explicitly passed)
        new_hotkey_str = _cli_key if _cli_key is not None else new_cfg.get("hotkey", "f9")
        new_trigger, new_modifiers = _parse_hotkey(new_hotkey_str)
        if new_trigger != cfg["trigger_key"] or new_modifiers != cfg["modifiers"]:
            with _hook_lock:
                if is_recording.is_set():
                    is_recording.clear()
                    recorder.stop()
                    tray.set_state("idle")
                cfg["trigger_key"] = new_trigger
                cfg["modifiers"] = new_modifiers
                keyboard.unhook_all()
                keyboard.hook(on_key_event)
```

to:

```python
    def reload_config():
        new_cfg = load_config()

        # Update hotkeys (main unless CLI --key was explicitly passed)
        new_hotkey_str = _cli_key if _cli_key is not None else new_cfg.get("hotkey", "f9")
        new_trigger, new_modifiers = _parse_hotkey(new_hotkey_str)
        new_stream_trigger, new_stream_modifiers = _parse_stream_hotkey(
            new_cfg.get("streaming_hotkey", ""), new_trigger, new_modifiers)
        with _hook_lock:
            rehook = (new_trigger != cfg["trigger_key"] or new_modifiers != cfg["modifiers"])
            if rehook and is_recording.is_set():
                is_recording.clear()
                recorder.stop()
                tray.set_state("idle")
            cfg["trigger_key"] = new_trigger
            cfg["modifiers"] = new_modifiers
            cfg["stream_trigger"] = new_stream_trigger
            cfg["stream_modifiers"] = new_stream_modifiers
            if rehook:
                keyboard.unhook_all()
                keyboard.hook(on_key_event)
```

(The single global hook dispatches by key name, so a changed `streaming_hotkey` takes effect via the `cfg` update alone — no re-hook needed for it.)

- [ ] **Step 6: Verify the old streaming-flag path is fully gone**

Confirm there is no remaining reference to the old `streaming` config flag in `on_key_event`/`main`. Run:

`grep -n 'get("streaming"' voice_typer.py`
Expected: no output (the only streaming references now are `streaming_hotkey`, `start_streaming`, `stream_active`, `stream_trigger`, etc.). `recorder.streaming` may remain as a harmless attribute set by `start_streaming`/`start`; leave it.

- [ ] **Step 7: Run the full unit suite (regression)**

Run: `python -m pytest -v`
Expected: PASS — Task 1's 15 `decide_key_action` tests plus the existing `ChunkDetector` (8) and `ChunkTranscriber` (3) tests, all green.

- [ ] **Step 8: Import/compile check, then commit**

Run: `python -c "import voice_typer"` (expect no error) and `python -m py_compile voice_typer.py`.

Then commit:

```bash
git add voice_typer.py
git commit -m "feat: streaming on a separate toggle hotkey; serialize tray.set_state"
```

**Manual smoke test (deferred to human — requires mic, API key, desktop session). List these in the report, do not run:**
1. Set `"streaming_hotkey": "f10"` in `config.json`. Tap F10, speak "первая фраза" — pause ~1.5 s — "вторая фраза", tap F10 again. Text pastes cleanly in chunks (no dropped/tripled letters), in order.
2. Hold F10 (autorepeat) briefly: session must start once, not flicker start/stop.
3. While a streaming session is active, press F9 — ignored (no second recording).
4. Remove/empty `streaming_hotkey`: F9 push-to-talk works exactly as before; F10 does nothing.
5. Trigger several chunk transcriptions in a row — tray icon never crashes (no `WinError 1402`).

---

### Task 3: Update config example and documentation

**Files:**
- Modify: `config.example.json`
- Modify: `CLAUDE.md` (Config Fields section)
- Modify: `README.md` (config fields section)

**Interfaces:**
- Consumes: field names/defaults from Global Constraints.
- Produces: documented `streaming_hotkey`; removal of the old `streaming` field.

- [ ] **Step 1: Update `config.example.json`**

The branch's current `config.example.json` contains the old streaming fields. Replace its contents with:

```json
{
  "groq_api_key": "gsk_your_key_here",
  "hotkey": "f9",
  "paste_mode": "type",
  "proxy": "",
  "streaming_hotkey": "",
  "pause_threshold": 1.0,
  "max_chunk_seconds": 15,
  "silence_threshold": 0.01,
  "voice_replacements": [
    {"from": "Cloud Code", "to": "Claude Code"},
    {"from": "Codorg[ao]s", "to": "CodOrgOS", "regex": true}
  ]
}
```

- [ ] **Step 2: Update `CLAUDE.md` Config Fields**

In the "Config Fields" section, replace the JSON block's streaming lines so the block reads:

```json
{
  "groq_api_key": "gsk_...",
  "hotkey": "f9",
  "paste_mode": "clipboard",
  "proxy": "",
  "streaming_hotkey": "",
  "pause_threshold": 1.0,
  "max_chunk_seconds": 15,
  "silence_threshold": 0.01,
  "voice_replacements": []
}
```

Then replace the existing "Streaming mode" paragraph with:

```markdown
**Streaming mode (experimental, opt-in)** — set `streaming_hotkey` to a key
(e.g. `"f10"`, supports modifiers like `"ctrl+f10"`) to enable a separate
TOGGLE hotkey: tap it to start a streaming session, speak with pauses (text is
transcribed and pasted in chunks as you go), tap again to stop. The key is NOT
held during typing, so injected text isn't corrupted. Empty/absent (default) =
disabled; the main `hotkey` stays a plain hold-to-talk. Only one recording at a
time (streaming and push-to-talk are mutually exclusive). `pause_threshold` =
seconds of silence that ends a chunk; `max_chunk_seconds` = forced flush during
long pause-free speech; `silence_threshold` = normalized RMS (0..1) below which
audio counts as silence. Streaming params are read fresh at session start.
Trade-off: lower accuracy on short chunks and more API requests — hence opt-in.
```

- [ ] **Step 3: Update `README.md`**

Find the section of `README.md` that lists `config.json` fields. Remove any old `streaming` boolean entry and add `streaming_hotkey` (with the four streaming params) described in one line each, matching that section's existing formatting (table row or bullet — match what's there), using wording consistent with `CLAUDE.md`.

- [ ] **Step 4: Verify JSON and commit**

Run: `python -c "import json; json.load(open('config.example.json'))"` (expect no error).

```bash
git add config.example.json CLAUDE.md README.md
git commit -m "docs: document streaming_hotkey toggle config, drop old streaming flag"
```

---

## Notes for the implementer

- **Why `decide_key_action` is pure (Task 1):** the key handler now juggles two keys, a toggle, autorepeat suppression, and mutual exclusion. Keeping the decision pure makes every branch unit-testable with plain dicts — no keyboard, audio, or threads.
- **Autorepeat suppression (`stream_key_held`):** `stream_active` stays True for the whole session even after you release the key, so it can't tell "key physically down". `stream_key_held` (set on the streaming key's `down`, cleared on its `up`) is what makes the toggle fire once per physical press.
- **Mutual exclusion** lives entirely in `decide_key_action` — the caller never needs to special-case it.
- **Reuse:** `ChunkDetector`, `ChunkTranscriber`, `AudioRecorder.start_streaming`/`flush_final`, and `handle_chunk` are unchanged from the earlier streaming work — this plan only changes *how a session is started/stopped* and fixes the tray race.
