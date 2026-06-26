# hotkey-voice-typer

**Hold a key → speak → release → text is pasted automatically.**  
**Зажми клавишу → говори → отпусти → текст вставляется автоматически.**

Uses [Groq Whisper](https://console.groq.com) for fast cloud transcription.  
Free tier: 28,800 minutes/day.

Использует [Groq Whisper](https://console.groq.com) для быстрой облачной транскрибации.  
Бесплатный тариф: 28 800 минут/день.

---

## How it works / Как работает

Hold the hotkey (default: `F9`) → microphone records → release → audio is sent to Groq Whisper → transcribed text is pasted via clipboard.

Удерживай хоткей (по умолчанию: `F9`) → микрофон записывает → отпускай → аудио отправляется в Groq Whisper → расшифрованный текст вставляется через буфер обмена.

---

## Requirements / Требования

- **Windows 10/11**
- **Python 3.10+**
- **Groq API key** (free) — [console.groq.com/keys](https://console.groq.com/keys)
- Microphone / Микрофон

---

## Installation / Установка

### Option A: Windows Installer (no Python required)

Download `hotkey-voice-typer-setup.exe` from [Releases](https://github.com/dialext-hub/hotkey-voice-typer/releases) and run it.
The installer creates a shortcut on your desktop and optionally adds the app to Windows startup.
`config.json` is created automatically — open it from the tray menu (right-click → Открыть config.json) and add your API key.

Скачай `hotkey-voice-typer-setup.exe` из [Releases](https://github.com/dialext-hub/hotkey-voice-typer/releases) и запусти.
Установщик создаёт ярлык на рабочем столе и опционально добавляет в автозапуск.
`config.json` создаётся автоматически — открой его через меню трея (правая кнопка → Открыть config.json) и добавь API ключ.

### Option B: Python (from source)

```bash
git clone https://github.com/dialext-hub/hotkey-voice-typer.git
cd hotkey-voice-typer
pip install -r requirements.txt
cp config.example.json config.json
```

Edit `config.json` and paste your Groq API key.  
Открой `config.json` и вставь свой Groq API ключ.

---

## Usage / Использование

```bash
python voice_typer.py              # default hotkey: F9 | хоткей по умолчанию: F9
python voice_typer.py --key f8     # use F8 instead
python voice_typer.py --key ctrl+windows  # modifier combo
python voice_typer.py --lang en    # English transcription | транскрибация на английском
python voice_typer.py --type       # type text instead of clipboard | печатать вместо вставки
python voice_typer.py --notify     # show toast with transcribed text | уведомление с расшифровкой
```

---

## Configuration / Настройка

Copy `config.example.json` to `config.json` and edit:

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

| Field | Default | Description |
|---|---|---|
| `groq_api_key` | required | Your Groq API key |
| `hotkey` | `f9` | Recording hotkey — single key or combo (e.g. `ctrl+windows`, `f8`) |
| `paste_mode` | `clipboard` | How to insert text: `clipboard` (Ctrl+V) or `type` (keyboard emulation) |
| `proxy` | `""` | HTTP proxy URL, e.g. `http://127.0.0.1:2080` (optional) |
| `streaming` | `false` | Transcribe/paste in chunks while hotkey is held (opt-in; slightly lower accuracy) |
| `pause_threshold` | `0.8` | Seconds of silence that ends a chunk (streaming mode only) |
| `max_chunk_seconds` | `15` | Forced chunk flush after this many seconds of continuous speech (streaming mode only) |
| `silence_threshold` | `0.01` | Normalized RMS (0..1) below which audio counts as silence (streaming mode only) |
| `voice_replacements` | `[]` | Auto-replacement rules, see below |

---

## Auto-replacements / Автозамены

Fix recurring transcription errors by adding rules to `config.json`.  
Исправляй частые ошибки транскрибации, добавляя правила в `config.json`.

```json
"voice_replacements": [
  {"from": "Cloud Code", "to": "Claude Code"},
  {"from": "Codorg[ao]s", "to": "CodOrgOS", "regex": true},
  {"from": "my company", "to": "MyCompany Inc.", "case_insensitive": false}
]
```

| Field | Default | Description |
|---|---|---|
| `from` | required | Pattern to match |
| `to` | required | Replacement string (supports `\1` backreferences for regex) |
| `regex` | `false` | Enable regex matching |
| `case_insensitive` | `true` | Ignore case |

Rules are applied in order. Config is re-read on every transcription — **no restart needed after editing**.  
Правила применяются по порядку. Конфиг перечитывается при каждой расшифровке — **перезапуск после редактирования не нужен**.

---

## Troubleshooting / Решение проблем

**`keyboard` requires admin rights / требует прав администратора**  
Run the script as Administrator (right-click → Run as administrator).  
Запусти скрипт от имени администратора.

**`groq_api_key not found`**  
Make sure `config.json` exists in the same directory as `voice_typer.py`.  
Убедись, что `config.json` находится в той же папке, что и `voice_typer.py`.

**No audio recorded / Нет записи**  
Check that your default microphone is working and not muted in Windows Sound settings.  
Проверь, что микрофон по умолчанию работает и не заглушён в настройках звука Windows.

**Tray icon does not appear / Иконка в трее не появляется**  
Make sure `pystray` and `Pillow` are installed: `pip install pystray Pillow`.  
Убедись, что установлены `pystray` и `Pillow`: `pip install pystray Pillow`.

---

## License

MIT
