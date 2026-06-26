# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project Overview

**Voice Typer** (`hotkey-voice-typer`) — push-to-talk voice typing for Windows. Hold a hotkey → speak → release → transcribed text is pasted. Uses Groq Whisper API for transcription (free tier: 28,800 min/day).

Single-file Python script (`voice_typer.py`) + Windows installer.

## Key Files

| File | Role |
|---|---|
| `voice_typer.py` | Main script — all logic in one file |
| `config.json` | Runtime config (gitignored — user creates from example) |
| `config.example.json` | Template with all supported fields |
| `icon.ico` | App icon (multi-size: 16–256px) |
| `build.ps1` | Build pipeline: PyInstaller → Inno Setup |
| `installer/setup.iss` | Inno Setup installer script |
| `requirements.txt` | Python dependencies |

## Config Fields

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

**Streaming mode** (`streaming: true`): detects pauses while the hotkey is held
and transcribes/pastes the audio in chunks as you speak, instead of only after
release. `pause_threshold` = seconds of silence that ends a chunk;
`max_chunk_seconds` = forced flush during long pause-free speech;
`silence_threshold` = normalized RMS (0..1) below which audio counts as silence.
Streaming flags are read fresh at key-down; per-chunk values (`paste_mode`,
`voice_replacements`, etc.) are read fresh per chunk. Trade-off: slightly lower
accuracy on short chunks and more API requests — hence opt-in.

All fields are hot-reloaded on every transcription — no restart needed. Hotkey changes require clicking "Перечитать конфиг" in the tray menu (triggers keyboard re-hook).

## Architecture

`voice_typer.py` structure:
- `_app_dir()` — resolves config path correctly in both frozen (.exe) and script modes
- `TrayIcon` class — pystray wrapper, manages icon state + menu
- `AudioRecorder` class — sounddevice-based push-to-talk recorder
- `apply_replacements()` — post-transcription text substitution
- `transcribe_groq()` — HTTP call to Groq Whisper API
- `main()` — wires everything together: cfg dict, keyboard hooks, hot-reload

**Critical pattern — frozen exe path:**
```python
def _app_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent  # real install dir, not PyInstaller temp
    return Path(__file__).parent
```
Never use `Path(__file__).parent` directly for user files — it points to `%TEMP%\_MEI*` in a frozen exe.

**Hot-reload architecture:**
- `cfg` dict holds only `trigger_key` + `modifiers` (needs keyboard re-hook on change)
- `process_audio()` calls `load_config()` fresh on every transcription for everything else

## Building

Prerequisites: `pip install pyinstaller`, Inno Setup 6 via winget.

```powershell
cd C:\Projects\hotkey-voice-typer
.\build.ps1
# → installer\hotkey-voice-typer-setup.exe
```

Note: winget installs Inno Setup to `%LOCALAPPDATA%\Programs\Inno Setup 6\` — `iscc` is NOT in PATH. `build.ps1` uses the full path.

## Releasing

```powershell
git tag vX.X.X
git push origin vX.X.X
gh release create vX.X.X --title "vX.X.X — description" --notes "..." installer\hotkey-voice-typer-setup.exe
```

Bump `MyAppVersion` in `installer/setup.iss` before building.

## Dependencies

```
sounddevice   # microphone recording
numpy         # audio array manipulation
keyboard      # global hotkey hook (requires admin on some setups)
pyperclip     # clipboard paste
requests      # Groq API HTTP call
pystray       # system tray icon
Pillow        # draw tray icon images
plyer         # Windows toast notifications
```

No `scipy` — WAV writing uses stdlib `wave` module.

## Common Issues

- **keyboard hook requires admin** on some Windows setups
- **iscc not in PATH** — use full path `$env:LOCALAPPDATA\Programs\Inno Setup 6\iscc.exe`
- **config.json lost on restart** — always use `_app_dir()` not `Path(__file__).parent`
- **Inno Setup `{commondesktop}`** requires UAC — use `{userdesktop}` with `PrivilegesRequired=lowest`
