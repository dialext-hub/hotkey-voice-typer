#!/usr/bin/env python3
"""
Voice Typer — держи клавишу, говори, отпускай → текст вставляется в буфер обмена.
Использует Groq Whisper для расшифровки (быстро, бесплатно).

Использование:
    python voice_typer.py              # запись по F9
    python voice_typer.py --key f8     # другая клавиша
    python voice_typer.py --type       # автопечатать вместо буфера обмена
    python voice_typer.py --lang en    # английский
    python voice_typer.py --notify     # toast-уведомления с расшифровкой

Настройки берутся из config.json (groq_api_key, proxy).
Зависимости:
    pip install sounddevice numpy keyboard pyperclip requests pystray Pillow plyer
"""

import os
import re
import sys
import json
import time
import tempfile
import threading
import argparse
from pathlib import Path

try:
    import sounddevice as sd
    import numpy as np
    import keyboard
    import pyperclip
    import requests
    import pystray
    from PIL import Image, ImageDraw
except ImportError as e:
    print(f"Не хватает зависимостей: {e}")
    print("Установи: pip install sounddevice numpy keyboard pyperclip requests pystray Pillow plyer")
    sys.exit(1)

# --- Конфиг ---

def _app_dir() -> Path:
    # PyInstaller --onefile extracts to a temp dir; sys.executable points to the real .exe
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

CONFIG_FILE = _app_dir() / "config.json"

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# --- Системный трей ---

ICON_COLORS = {
    "idle":       (136, 136, 136),
    "recording":  (229,  57,  53),
    "processing": (249, 168,  37),
    "error":      (229,  57,  53),
}

def hide_console():
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

def make_icon(state, size=64):
    color = ICON_COLORS.get(state, ICON_COLORS["idle"])
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    return img

# --- Запись ---

SAMPLE_RATE = 16000  # Groq хорошо работает с 16kHz
_processing_lock = threading.Lock()

class AudioRecorder:
    def __init__(self):
        self.frames = []
        self.recording = False
        self._stream = None

    def start(self):
        self.frames = []
        self.recording = True
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status):
        if self.recording:
            self.frames.append(indata.copy())

    def stop(self):
        self.recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def save_wav(self, path):
        if not self.frames:
            return False
        import wave
        audio = np.concatenate(self.frames, axis=0)
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16 = 2 bytes
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        return True

# --- Автозамены ---

def apply_replacements(text, rules):
    """Применяет правила автозамены к распознанному тексту.

    Каждое правило — dict с полями:
      from  — строка или regex-паттерн
      to    — строка замены (поддерживает backreferences \\1 для regex)
      regex — bool, по умолчанию false
      case_insensitive — bool, по умолчанию true
    """
    for rule in rules:
        pattern = rule.get("from", "")
        replacement = rule.get("to", "")
        if not pattern:
            continue
        flags = re.IGNORECASE if rule.get("case_insensitive", True) else 0
        if rule.get("regex", False):
            text = re.sub(pattern, replacement, text, flags=flags)
        else:
            text = re.sub(re.escape(pattern), replacement, text, flags=flags)
    return text


# --- Системный трей (иконка) ---

class TrayIcon:
    def __init__(self, notify_enabled=False):
        self._notify_enabled = notify_enabled
        self._error_timer = None
        self._reload_callback = None
        self._icon = pystray.Icon(
            "hotkey-voice-typer",
            make_icon("idle"),
            "hotkey-voice-typer",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "Открыть config.json",
                    lambda icon, item: self._open_config(),
                ),
                pystray.MenuItem(
                    "Перечитать конфиг",
                    lambda icon, item: self._on_reload(),
                ),
                pystray.MenuItem(
                    "Выход",
                    lambda icon, item: self._exit(),
                ),
            ),
        )

    def set_reload_callback(self, callback):
        self._reload_callback = callback

    def _on_reload(self):
        if self._reload_callback:
            self._reload_callback()

    def run_detached(self):
        self._icon.run_detached()

    def set_state(self, state):
        if self._error_timer is not None:
            self._error_timer.cancel()
            self._error_timer = None
        self._icon.icon = make_icon(state)
        if state == "error":
            self._error_timer = threading.Timer(2.0, lambda: self.set_state("idle"))
            self._error_timer.start()

    def notify(self, title, message, force=False):
        if self._notify_enabled or force:
            try:
                from plyer import notification
                notification.notify(title=title, message=message, timeout=4)
            except Exception:
                pass

    def stop(self):
        self._icon.stop()

    def _open_config(self):
        config_path = _app_dir() / "config.json"
        if not config_path.exists():
            example = config_path.parent / "config.example.json"
            if example.exists():
                import shutil
                shutil.copy(example, config_path)
            else:
                config_path.write_text('{"groq_api_key": ""}', encoding="utf-8")
        os.startfile(str(config_path))

    def _exit(self):
        if self._error_timer is not None:
            self._error_timer.cancel()
        self._icon.stop()
        os._exit(0)


# --- Groq транскрипция ---

def transcribe_groq(wav_path, api_key, language="ru", proxy=None):
    proxies = {"https": proxy, "http": proxy} if proxy else None

    with open(wav_path, "rb") as f:
        response = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (Path(wav_path).name, f, "audio/wav")},
            data={"model": "whisper-large-v3", "language": language, "response_format": "text"},
            proxies=proxies,
            timeout=30,
        )

    response.raise_for_status()
    return response.text.strip()

# --- Вставка текста ---

def paste_text(text, auto_type=False):
    if auto_type:
        keyboard.write(text, delay=0.01)
    else:
        pyperclip.copy(text)
        keyboard.send("ctrl+v")

# --- Основной цикл ---

def main():
    parser = argparse.ArgumentParser(description="Voice Typer — говори, получай текст")
    parser.add_argument("--key", default=None,
                        help="Клавиша или комбинация для записи. "
                             "Примеры: f9, ctrl+windows, ctrl+alt+f8. "
                             "Если не указано — берётся из config.json (hotkey), дефолт f9")
    parser.add_argument("--lang", default="ru", help="Язык (default: ru)")
    parser.add_argument("--type", action="store_true", dest="auto_type",
                        help="Печатать текст вместо вставки из буфера (override для paste_mode)")
    parser.add_argument("--notify", action="store_true",
                        help="Показывать toast-уведомление с расшифрованным текстом")
    parser.add_argument("--debug", action="store_true", help="Показывать отладочные сообщения")
    args = parser.parse_args()

    hide_console()

    # CLI overrides: if --key was passed, it always wins over config.
    # If --type was passed, it always wins over paste_mode in config.
    _cli_key = args.key       # None = "read from config"
    _cli_auto_type = args.auto_type  # True = --type was explicitly passed

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

    tray = TrayIcon(notify_enabled=args.notify)
    tray.run_detached()

    initial_api_key = initial_config.get("groq_api_key") or os.environ.get("GROQ_API_KEY")
    if not initial_api_key or initial_api_key == "gsk_your_key_here":
        tray._icon.title = "Voice Typer — нет API ключа (меню → Открыть config.json)"
        tray.notify(
            "Voice Typer — нет API ключа",
            "Открой config.json через меню трея и добавь groq_api_key",
            force=True,
        )

    recorder = AudioRecorder()
    is_recording = threading.Event()

    if args.debug:
        print(f"[debug] Voice Typer ready. Key: {initial_hotkey.upper()}")

    def process_audio():
        if not _processing_lock.acquire(blocking=False):
            tray.set_state("idle")
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
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

            if recorder.save_wav(tmp_path):
                text = transcribe_groq(tmp_path, current_api_key, args.lang, current_proxy)
                if text:
                    rules = fresh.get("voice_replacements", [])
                    if rules:
                        text = apply_replacements(text, rules)
                    tray.set_state("idle")
                    tray.notify("Voice Typer", text)
                    if args.debug:
                        print(f"[debug] {text}")
                    paste_text(text, current_auto_type)
                else:
                    tray.set_state("idle")
            else:
                tray.set_state("idle")
        except Exception as ex:
            tray.set_state("error")
            tray.notify("Voice Typer — Ошибка", str(ex), force=True)
            if args.debug:
                print(f"[debug] error: {ex}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            _processing_lock.release()

    def modifiers_held():
        return all(keyboard.is_pressed(m) for m in cfg["modifiers"])

    def on_key_event(e):
        if args.debug:
            print(f"[debug] {e.event_type}: name={e.name!r} scan_code={e.scan_code}", flush=True)
        if e.name != cfg["trigger_key"]:
            return
        if e.event_type == keyboard.KEY_DOWN and not is_recording.is_set() and modifiers_held():
            is_recording.set()
            recorder.start()
            tray.set_state("recording")
        elif e.event_type == keyboard.KEY_UP and is_recording.is_set():
            is_recording.clear()
            recorder.stop()
            tray.set_state("processing")
            threading.Thread(target=process_audio, daemon=True).start()

    def reload_config():
        new_cfg = load_config()

        # Update hotkey (unless CLI --key was explicitly passed)
        new_hotkey_str = _cli_key if _cli_key is not None else new_cfg.get("hotkey", "f9")
        new_trigger, new_modifiers = _parse_hotkey(new_hotkey_str)
        if new_trigger != cfg["trigger_key"] or new_modifiers != cfg["modifiers"]:
            cfg["trigger_key"] = new_trigger
            cfg["modifiers"] = new_modifiers
            keyboard.unhook_all()
            keyboard.hook(on_key_event)

        # Update tray title based on api_key status
        new_api_key = new_cfg.get("groq_api_key") or os.environ.get("GROQ_API_KEY")
        if new_api_key and new_api_key != "gsk_your_key_here":
            tray._icon.title = "hotkey-voice-typer"
        else:
            tray._icon.title = "Voice Typer — нет API ключа (меню → Открыть config.json)"

        tray.notify("Voice Typer", "Конфиг обновлён", force=True)

    tray.set_reload_callback(reload_config)

    keyboard.hook(on_key_event)

    try:
        keyboard.wait()
    except KeyboardInterrupt:
        tray.stop()

if __name__ == "__main__":
    main()
