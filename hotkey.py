#!/usr/bin/env python
"""Гига Писарь для Linux — диктовка по горячей клавише. Только X11.

Держите правый Ctrl, говорите, отпустите — текст вставится в активное окно.
С Shift (правый Ctrl + Shift) после вставки ещё нажмётся Enter: наговорил
и сразу отправил в чат.

Текст вставляется через буфер обмена, а через PISAR_CLIPBOARD_MS миллисекунд
(по умолчанию 300) в буфер возвращается то, что там было. 0 — не возвращать.

История диктовок пишется в $XDG_RUNTIME_DIR/pisar-history.log. Эта папка
живёт в памяти и пропадает при выключении. Ротация по размеру: два файла
по 256 КБ. Без XDG_RUNTIME_DIR истории нет.

Клавиша меняется через PISAR_KEY (имя из pynput.keyboard.Key: ctrl_r, alt_r, ...).
Папка с моделью ищется так же, как у pisar: PISAR_MODEL_DIR, потом model рядом.
"""
import glob
import logging.handlers
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave

# Под Wayland программа не видит чужих нажатий и не может вставлять текст
# в чужие окна так, как в X11, — молча висеть без толку хуже, чем сказать.
if os.environ.get("XDG_SESSION_TYPE") != "x11":
    sys.exit("hotkey.py работает только в сеансе X11, а здесь "
             f"{os.environ.get('XDG_SESSION_TYPE') or 'неизвестно что'}")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import giga_core
from pynput import keyboard
from Xlib import X, display

KEY = getattr(keyboard.Key, os.environ.get("PISAR_KEY", "ctrl_r"))
MIN_HOLD = 0.4  # короче — случайное нажатие, не диктовка
CLIPBOARD_DELAY = max(0.0, float(os.environ.get("PISAR_CLIPBOARD_MS", "300"))) / 1000
SOUNDS = "/usr/share/sounds/freedesktop/stereo/"
SOUND_START = SOUNDS + "audio-volume-change.oga"
SOUND_DONE = SOUNDS + "message.oga"

# В памяти (tmpfs): запись и история не переживают выключения. Без
# XDG_RUNTIME_DIR записи идут в системную временную папку через mkstemp
# (права 0600, имя случайное), а историю не ведём: класть её в общий /tmp
# под известным именем нельзя.
RUNTIME = os.environ.get("XDG_RUNTIME_DIR")

history = logging.getLogger("history")
history.setLevel(logging.INFO)
history.propagate = False
if RUNTIME:
    _h = logging.handlers.RotatingFileHandler(
        os.path.join(RUNTIME, "pisar-history.log"),
        maxBytes=256 * 1024, backupCount=1, encoding="utf-8",
    )
    _h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
    history.addHandler(_h)
else:
    history.addHandler(logging.NullHandler())


def scratch(suffix: str) -> str:
    fd, path = tempfile.mkstemp(prefix="pisar-", suffix=suffix, dir=RUNTIME)
    os.close(fd)
    return path


# Записи, оставшиеся от прошлого запуска (выключили посреди очереди,
# не запустился parec), подчищаем при старте. Только давно не менявшиеся:
# свежие могут быть у второго запущенного экземпляра.
_tmp = RUNTIME or tempfile.gettempdir()
for _old in glob.glob(os.path.join(_tmp, "pisar-*.raw")) + glob.glob(os.path.join(_tmp, "pisar-*.wav")):
    try:
        if time.time() - os.path.getmtime(_old) > 60:
            os.remove(_old)
    except OSError:
        pass

engine = giga_core.Engine()
kbd = keyboard.Controller()
rec = None   # (parec, файл записи), пока клавиша зажата
jobs = queue.Queue()  # распознаём по одной и по порядку
started = 0.0
other_key = False  # Ctrl нажат вместе с другой клавишей: это сочетание, а не диктовка
send = False       # во время записи был нажат Shift: после вставки жмём Enter
# Отпускание Shift отслеживать нельзя: при grp:ctrl_shift_toggle X присылает
# его как ISO_Next_Group, и флаг залипал. Спрашиваем у X текущее состояние.
xroot = display.Display().screen().root


def shift_held() -> bool:
    return bool(xroot.query_pointer().mask & X.ShiftMask)


SHIFTS = (keyboard.Key.shift, keyboard.Key.shift_r)
# Слушатель видит и наши собственные Shift+Insert и Enter (флаг injected
# в X11 ненадёжен). Если в это время держат Ctrl для следующей диктовки,
# чужой Shift превращал её в отправку. Пока вставляем, прочие клавиши глушим.
quiet_until = 0.0


def hush() -> None:
    global quiet_until
    quiet_until = time.monotonic() + 0.2


def beep(path: str) -> None:
    if os.path.exists(path):
        subprocess.Popen(["paplay", path], stderr=subprocess.DEVNULL)


EMPTY = ("UTF8_STRING", b"")


def xclip_out(sel: str, target: str):
    try:
        return subprocess.run(["xclip", "-o", "-selection", sel, "-t", target],
                              capture_output=True, timeout=1)
    except subprocess.TimeoutExpired:
        return None


def grab(sel: str):
    """Что лежит в буфере: (формат, данные). Текст берём как текст, иначе
    первый настоящий формат, чтобы вернуть и картинку. Один формат: xclip
    больше не умеет. None, если прочитать не вышло: тогда буфер не трогаем."""
    r = xclip_out(sel, "TARGETS")
    if r is None:
        return None
    if r.returncode != 0:
        # У буфера нет владельца, то есть он пуст. Прочие ошибки — не знаем.
        return EMPTY if b"not available" in r.stderr else None
    targets = [t for t in r.stdout.decode(errors="ignore").split()
               if t not in ("TARGETS", "TIMESTAMP", "MULTIPLE", "SAVE_TARGETS")]
    if not targets:
        return EMPTY
    target = "UTF8_STRING" if "UTF8_STRING" in targets else targets[0]
    r = xclip_out(sel, target)
    return (target, r.stdout) if r is not None and r.returncode == 0 else None


def paste(text: str) -> dict:
    """Вставляет текст и возвращает прежнее содержимое буферов для restore()."""
    old = {sel: grab(sel) for sel in ("clipboard", "primary")} if CLIPBOARD_DELAY else {}
    # Кладём в оба буфера и жмём Shift+Insert: так вставляют и терминалы
    # (берут PRIMARY), и Qt/GTK/браузеры (берут CLIPBOARD).
    for sel in ("clipboard", "primary"):
        subprocess.run(["xclip", "-selection", sel], input=text.encode(), check=True)
    hush()
    with kbd.pressed(keyboard.Key.shift):
        kbd.tap(keyboard.Key.insert)
    return old


def restore(old: dict) -> None:
    if not old:
        return
    # Окно забирает буфер не сразу: вернём прежний чуть погодя.
    time.sleep(CLIPBOARD_DELAY)
    # CLIPBOARD последним: если менеджер буфера синхронизирует его
    # с PRIMARY, пусть победит то, что вставят по Ctrl+V.
    for sel in ("primary", "clipboard"):
        if old[sel] is not None:
            target, data = old[sel]
            subprocess.run(["xclip", "-selection", sel, "-t", target], input=data)


def finish(proc, raw: str, held: float, enter: bool) -> None:
    proc.wait()
    wav = None
    try:
        if held >= MIN_HOLD:
            wav = scratch(".wav")
            transcribe(raw, wav, held, enter)
    finally:
        for path in (raw, wav):
            if path and os.path.exists(path):
                os.remove(path)


def worker() -> None:
    # Упавшая диктовка не должна останавливать очередь: иначе все
    # следующие молча копились бы в ней.
    while True:
        try:
            finish(*jobs.get())
        except Exception:
            traceback.print_exc()


def transcribe(raw: str, wav: str, held: float, enter: bool) -> None:
    with open(raw, "rb") as f, wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(f.read())
    text = engine.transcribe(wav)
    print(f"{held:.1f}s, {len(text)} симв.", flush=True)
    if not text:
        return
    history.info(text)
    if enter:
        old = paste(text)
        time.sleep(0.05)  # дать вставке дойти до окна раньше Enter
        hush()
        kbd.tap(keyboard.Key.enter)
    else:
        old = paste(text + " ")
    beep(SOUND_DONE)
    restore(old)


def on_press(key):
    global rec, started, other_key, send
    if key != KEY and time.monotonic() < quiet_until:
        return
    if key in SHIFTS:
        send = True
        return
    if key != KEY:
        other_key = True
        return
    if rec is None:
        other_key = False
        send = shift_held()
        beep(SOUND_START)
        started = time.monotonic()
        # Микрофон открываем только на время нажатия: между диктовками
        # он закрыт. pw-record раскачивался около секунды, parec с малой
        # задержкой — нет. Остаётся пробуждение звуковой карты, ~0,2 с;
        # его убирает install.sh --no-mic-sleep.
        raw = scratch(".raw")
        with open(raw, "wb") as f:
            rec = subprocess.Popen(
                ["parec", "--format=s16le", "--rate=16000", "--channels=1", "--latency-msec=50"],
                stdout=f,
            ), raw


def on_release(key):
    global rec
    if key != KEY or rec is None:
        return
    (proc, raw), rec = rec, None
    proc.terminate()  # здесь, а не в очереди: иначе запись шла бы, пока ждёт
    held = 0.0 if other_key else time.monotonic() - started
    jobs.put((proc, raw, held, send))


# После загрузки микрофон спит, пока его не откроют, и правило
# --no-mic-sleep начинает действовать только с этого момента. Будим сразу.
subprocess.run(["timeout", "0.3", "parec"], stdout=subprocess.DEVNULL)

threading.Thread(target=worker, daemon=True).start()
print("готов, держите", KEY, flush=True)
with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
    l.join()
