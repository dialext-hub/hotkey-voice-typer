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
```

---

## Configuration / Настройка

Copy `config.example.json` to `config.json` and edit:

```json
{
  "groq_api_key": "gsk_...",
  "proxy": "",
  "voice_replacements": []
}
```

| Field | Description |
|---|---|
| `groq_api_key` | Your Groq API key |
| `proxy` | HTTP proxy URL, e.g. `http://127.0.0.1:2080` (optional) |
| `voice_replacements` | Auto-replacement rules, see below |

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

---

## License

MIT
