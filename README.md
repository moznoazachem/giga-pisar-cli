# Гига Писарь

*[English](#english) · [Русский](#русский)*

---

## English

Russian speech-to-text on your own machine. Fast, CPU-only, offline.

```
$ pisar recording.ogg
Так, значит, я могу уже говорить, да? Ну, буду говорить всякую фигню или как.
```

Under the hood — [GigaAM v3](https://github.com/salute-developers/GigaAM) by the
GigaChat team, the best open model for Russian to date. It ships here converted
to ONNX and quantized to int8, so it runs on an ordinary server with no GPU
and weighs 309 MB instead of a gigabyte (204 MB archived).

### One core, three shells

All the work lives in `giga_core.py`: audio preprocessing, model inference,
decoding. Three ways to call it:

| Shell | How | When |
|---|---|---|
| command line | `pisar file.ogg` | one-off transcriptions, scripts |
| server | `pisar --serve` | a stream of recordings: the model stays in memory |
| dictation | hold right Ctrl | typing by voice on a Linux desktop (X11 only) |

The server speaks the OpenAI dialect, so third-party tools work too:

```
POST /v1/audio/transcriptions   multipart, field "file" → {"text": "..."}
GET  /health                    liveness check
```

Listens on `127.0.0.1:8737` — local machine only, nothing exposed.

### Why, if GigaAM already exists

The library does exactly one thing: takes properly prepared audio and returns
text. Everything else is on you. Pisar takes care of it:

- **any format** — ogg, m4a, mp3, wav; anything ffmpeg understands;
- **long recordings** — the model takes at most 25 seconds, so Pisar splits
  on pauses between phrases (not mid-word) and stitches the results;
- **clean output** — stdout carries only the text, diagnostics go to stderr;
  pipe-friendly;
- **ready-made model files** — no torch, no manual ONNX export;
- **modest dependencies** — `onnxruntime`, `numpy`, `sentencepiece`, `pyyaml`,
  that's it. No `gigaam`, no PyTorch: ~150 MB instead of a gigabyte.

Nothing is sent anywhere: the model is a file on disk, recognition happens
on the same machine.

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/moznoazachem/giga-pisar-cli/main/install.sh | bash
```

Ubuntu 22.04 and 24.04. Sets up `/opt/giga-pisar`, downloads the model from
the release, puts the `pisar` command into `/usr/local/bin`.

As a server too, managed by systemd:

```bash
curl -fsSL .../install.sh | bash -s -- --service
```

Different folder — `bash install.sh ~/giga-pisar`.

### Usage

```bash
pisar запись.ogg                  # one file
pisar *.m4a                       # several
pisar --serve                     # start the server
pisar --serve --port 9000         # different port
pisar --model-dir ~/model a.wav   # custom model folder
```

From your own code: if recordings come in a stream, run the server and use
HTTP — several times faster, the model isn't reloaded.

```python
async with session.post(
    "http://127.0.0.1:8737/v1/audio/transcriptions", data=form
) as r:
    text = (await r.json())["text"]
```

For one-off jobs a subprocess is fine:

```python
text = subprocess.run(
    ["pisar", path], capture_output=True, text=True, check=True
).stdout.strip()
```

### Dictation on a hotkey (Linux, X11 only)

The same thing the macOS app does, for a Linux desktop. Hold right Ctrl,
speak, release, and the text lands in the active window.

```bash
curl -fsSL .../install.sh | bash -s -- --hotkey
```

This adds `xclip`, `pulseaudio-utils` and `pynput`, puts `pisar-hotkey` into
`/usr/local/bin`, starts it and registers it in `~/.config/autostart`, so it
comes back after login.

- right Ctrl: dictate, the text is pasted with a trailing space;
- right Ctrl + Shift: dictate and press Enter after pasting, handy for chats;
- the text goes through the clipboard, and 300 ms later the clipboard gets
  back what was there before. Only one format comes back (text as text,
  otherwise the first one offered, so an image survives, rich text from a
  browser loses its formatting). A slow window may need more time:
  `PISAR_CLIPBOARD_MS=800`, and `0` leaves the dictated text in the clipboard;
- history of what was dictated: `$XDG_RUNTIME_DIR/pisar-history.log`. It lives
  in memory, rotates at 256 KB and is gone after shutdown. Without
  `XDG_RUNTIME_DIR` no history is kept;
- a different key: `PISAR_KEY=alt_r` (any `pynput.keyboard.Key` name);
- log: `$XDG_RUNTIME_DIR/pisar-hotkey.log` (or `~/.cache/pisar-hotkey.log`);
- to turn it off, remove `~/.config/autostart/giga-pisar.desktop`.

The microphone is opened only while the key is held. Between dictations
nothing listens.

X11 only. Under Wayland an app can't see other windows' key presses or paste
into them this way, so `pisar-hotkey` exits with a message. Tested on
Ubuntu 24.04 with KDE Plasma.

If the first fraction of a second gets cut off, add `--no-mic-sleep` (see
pitfalls below):

```bash
curl -fsSL .../install.sh | bash -s -- --hotkey --no-mic-sleep
```

If the server is installed as well, the dictation daemon still loads its own
copy of the model, about 500 MB more memory.

### Performance

Measured on 2 CPU cores, Ubuntu 24.04, a 13-second recording:

| Called as | Time |
|---|---|
| via the server (model already in memory) | **~1.4 s** |
| the `pisar` command (loads the model every time) | ~3.7 s |
| the previous build, via `gigaam` + PyTorch | ~8.7 s |

The gap between the first two rows is model loading. For a stream of
recordings, keep the server running.

The server holds about 500 MB of memory and does not grow.

### Pitfalls we've already stepped on

**The `gigaam` library pulls in PyTorch it never computes with.** The package
imports `torch` and `torchaudio` at load time while inference runs on
`onnxruntime` — a quarter-gigabyte of dead weight. `giga_core.py` reimplements
exactly what inference needs, so the library isn't required at all — along
with its rigid version pins (`onnxruntime` strictly 1.23.x and so on).

**Audio features must match to the last digit.** Before the model, audio is
turned into a log-mel spectrogram. Diverge here and you get garbage, not
"slightly worse". Our implementation is verified against the original:
`scripts/сверка.py` runs both on the same recordings and compares features
and text. Bit-for-bit equality is impossible — numpy and torch round the last
digit differently — but the divergence stays at about one character in a thousand.

**The tokenizer lives apart from the model.** ONNX export writes an absolute
tokenizer path into `v3_e2e_rnnt.yaml` — a path from the machine where the
export was done. The core therefore looks for the tokenizer next to the model
first, and only then trusts the yaml.

**Cutting by time doesn't work.** Slice a long recording into 24-second
chunks and the cut lands mid-word. Pisar finds pauses via `silencedetect`
and cuts there.

**`gigaam` from PyPI won't do** (if you decide to install the library anyway).
It ships 0.1.0 with the old API: no `load_onnx` / `infer_onnx` needed for v3
models. Sources from GitHub only.

**The sound card takes a while to wake up.** Starting `pw-record` on every key
press lost about a second at the start of a phrase. `parec` with
`--latency-msec=50` delivers sound much sooner, but a suspended sound card
still needs about 240 ms to wake (measured on Intel SOF), and the first
syllable goes with it. With the card awake the first audio arrives in about
25 ms. `--no-mic-sleep` adds a WirePlumber rule that keeps microphones from
suspending. Nobody reads the sound until the key is held, and no "microphone
in use" indicator shows up, but the card stays powered, which costs some
battery. Delete `~/.config/wireplumber/*/51-pisar-mic-nosuspend.*` to undo.

### Related project

[Giga Pisar for macOS](https://github.com/moznoazachem/giga-pisar) — dictation on
a hotkey: hold right ⌘, speak, release, the text lands in the active window.
Same core inside, ported to Swift. The Linux counterpart is `pisar-hotkey`
from this repo, see above.

### License

MIT. The GigaAM v3 model is MIT as well, by the GigaChat team.
Details in [LICENSE](LICENSE).

---

## Русский

Распознавание русской речи на своей машине. Быстро, на процессоре, без интернета.

```
$ pisar запись.ogg
Так, значит, я могу уже говорить, да? Ну, буду говорить всякую фигню или как.
```

Под капотом — [GigaAM v3](https://github.com/salute-developers/GigaAM) от команды
GigaChat, лучшая на сегодня открытая модель для русского языка. Она переведена
в формат ONNX и сжата до int8, поэтому работает на обычном сервере без видеокарты
и весит 309 МБ вместо гигабайта (204 МБ в архиве).

### Одно ядро, три оболочки

Вся работа — в `giga_core.py`: подготовка звука, запуск модели, декодирование.
Сверху три способа обратиться:

| Оболочка | Как звать | Когда |
|---|---|---|
| командная строка | `pisar файл.ogg` | разовая расшифровка, скрипты |
| сервер | `pisar --serve` | поток записей: модель живёт в памяти |
| диктовка | зажать правый Ctrl | набор голосом на рабочем столе Linux (только X11) |

Сервер отвечает по-OpenAI'ному, поэтому годится и для чужих программ:

```
POST /v1/audio/transcriptions   multipart, поле file → {"text": "..."}
GET  /health                    жив ли
```

Слушает `127.0.0.1:8737` — только свою машину, наружу ничего не торчит.

### Зачем, если есть сама GigaAM

Библиотека умеет ровно одно: взять правильно подготовленный звук и выдать текст.
Всё остальное приходится делать самому. Писарь берёт это на себя:

- **любой формат** — ogg, m4a, mp3, wav; всё, что понимает ffmpeg;
- **длинные записи** — модель не принимает больше 25 секунд, а Писарь режет запись
  по паузам между фразами, а не посреди слова, и склеивает результат;
- **чистый вывод** — в stdout уходит только текст, служебное в stderr;
  результат можно сразу пускать по конвейеру;
- **готовые файлы модели** — не нужно ставить torch и экспортировать ONNX самому;
- **скромные зависимости** — `onnxruntime`, `numpy`, `sentencepiece`, `pyyaml`,
  и всё. Ни самой `gigaam`, ни PyTorch: окружение весит около 150 МБ вместо гигабайта.

Ничего никуда не отправляется: модель лежит файлом на диске, распознавание идёт
на той же машине.

### Установка

```bash
curl -fsSL https://raw.githubusercontent.com/moznoazachem/giga-pisar-cli/main/install.sh | bash
```

Ubuntu 22.04 и 24.04. Ставит окружение в `/opt/giga-pisar`, скачивает модель
из релиза и кладёт команду `pisar` в `/usr/local/bin`.

Сразу и сервером, службой systemd:

```bash
curl -fsSL .../install.sh | bash -s -- --service
```

Другая папка — `bash install.sh ~/giga-pisar`.

### Использование

```bash
pisar запись.ogg                  # один файл
pisar *.m4a                       # несколько
pisar --serve                     # поднять сервер
pisar --serve --port 9000         # на другом порту
pisar --model-dir ~/model а.wav   # своя папка с моделью
```

Из своей программы: если записей много — поднимите сервер и ходите по HTTP,
это в несколько раз быстрее, потому что модель не перезагружается.

```python
async with session.post(
    "http://127.0.0.1:8737/v1/audio/transcriptions", data=form
) as r:
    text = (await r.json())["text"]
```

Для разовых задач хватит и подпроцесса:

```python
text = subprocess.run(
    ["pisar", path], capture_output=True, text=True, check=True
).stdout.strip()
```

### Диктовка по горячей клавише (Linux, только X11)

То же, что делает приложение для macOS, только для Linux. Зажал правый Ctrl,
сказал, отпустил — текст вставился в активное окно.

```bash
curl -fsSL .../install.sh | bash -s -- --hotkey
```

Доставит `xclip`, `pulseaudio-utils` и `pynput`, положит `pisar-hotkey`
в `/usr/local/bin`, запустит и пропишет в `~/.config/autostart`, чтобы
поднимался после входа в систему.

- правый Ctrl — диктовка, текст вставляется с пробелом в конце;
- правый Ctrl + Shift — после вставки ещё нажмётся Enter, удобно для чатов;
- текст идёт через буфер обмена, и через 300 мс в буфер возвращается то, что
  там было. Возвращается один формат (текст как текст, иначе первый
  предложенный, так что картинка не пропадёт, а у текста из браузера
  потеряется оформление). Медленному окну может не хватить времени —
  `PISAR_CLIPBOARD_MS=800`, а `0` оставляет в буфере надиктованное;
- история надиктованного — `$XDG_RUNTIME_DIR/pisar-history.log`. Живёт
  в памяти, ротируется по 256 КБ и пропадает при выключении. Без
  `XDG_RUNTIME_DIR` история не ведётся;
- другая клавиша — `PISAR_KEY=alt_r` (любое имя из `pynput.keyboard.Key`);
- лог — `$XDG_RUNTIME_DIR/pisar-hotkey.log` (или `~/.cache/pisar-hotkey.log`);
- выключить — удалить `~/.config/autostart/giga-pisar.desktop`.

Микрофон открывается только пока зажата клавиша. Между диктовками его
никто не слушает.

Только X11. Под Wayland программа не видит чужих нажатий и не может так
вставлять текст в чужие окна, поэтому `pisar-hotkey` там выходит с сообщением.
Проверено на Ubuntu 24.04 с KDE Plasma.

Если обрезается начало фразы, добавьте `--no-mic-sleep` (см. грабли ниже):

```bash
curl -fsSL .../install.sh | bash -s -- --hotkey --no-mic-sleep
```

Если стоит ещё и сервер, демон диктовки всё равно грузит свою копию модели —
это плюс около 500 МБ памяти.

### Сколько работает

Замеры на 2 ядрах, Ubuntu 24.04, запись 13 секунд:

| Как звали | Время |
|---|---|
| через сервер (модель уже в памяти) | **~1,4 с** |
| командой `pisar` (грузит модель каждый раз) | ~3,7 с |
| прежняя сборка, через `gigaam` и PyTorch | ~8,7 с |

Разница между первой и второй строкой — это и есть загрузка модели. Если записи
идут потоком, держите сервер.

Сервер занимает около 500 МБ памяти и больше не растёт.

### Грабли, на которые мы уже наступили

**Библиотека `gigaam` тянет PyTorch, хотя считает не им.** Пакет импортирует
`torch` и `torchaudio` при загрузке, а считает `onnxruntime` — четверть гигабайта
мёртвым грузом. Поэтому в `giga_core.py` повторено ровно то, что нужно для счёта,
и сама библиотека больше не требуется. Заодно отпали её жёсткие требования
к версиям (`onnxruntime` строго 1.23.x и прочее).

**Признаки звука должны совпадать до последнего знака.** Перед моделью запись
превращается в лог-мел-спектрограмму. Разойтись здесь — получить не «чуть хуже»,
а бессмыслицу. Наш вариант сверен с оригинальным: `scripts/сверка.py` гоняет оба
на одних записях и сравнивает и признаки, и текст. Совпасть бит в бит нельзя —
у numpy и torch разная арифметика в последнем разряде, — но расхождение остаётся
на уровне одной буквы из тысячи.

**Токенизатор живёт отдельно от модели.** При экспорте ONNX в `v3_e2e_rnnt.yaml`
записывается абсолютный путь к файлу токенизатора — с той машины, где делали
экспорт. На любой другой он не существует. Ядро поэтому сперва ищет токенизатор
рядом с моделью и только потом смотрит в yaml.

**Резать по времени нельзя.** Если просто нарезать длинную запись кусками
по 24 секунды, разрез попадёт в середину слова и оно потеряется. Писарь
ищет паузы через `silencedetect` и режет по ним.

**gigaam из PyPI не подойдёт** (если всё-таки решите ставить саму библиотеку).
Там лежит 0.1.0 со старым API: функций `load_onnx` и `infer_onnx`, нужных
для модели v3, в ней просто нет. Только из исходников с GitHub.

**Звуковая карта просыпается не сразу.** Запуск `pw-record` на каждое нажатие
съедал около секунды начала фразы. `parec` с `--latency-msec=50` отдаёт звук
гораздо раньше, но уснувшей звуковой карте всё равно нужно ~240 мс, чтобы
проснуться (замер на Intel SOF), и первый слог пропадает. С проснувшейся
картой первый звук приходит через ~25 мс. `--no-mic-sleep` ставит правило
WirePlumber, которое не даёт микрофонам засыпать. Звук никто не читает, пока
не зажата клавиша, и значка «микрофон используется» нет, но карта не спит —
это немного батареи. Вернуть как было — удалить
`~/.config/wireplumber/*/51-pisar-mic-nosuspend.*`.

### Родственный проект

[Giga Pisar для macOS](https://github.com/moznoazachem/giga-pisar) — диктовка
по горячей клавише: зажал правый ⌘, сказал, отпустил, текст вставился
в активное окно. Внутри то же самое ядро, перенесённое на Swift. Аналог для
Linux — `pisar-hotkey` из этого репозитория, см. выше.

### Лицензия

MIT. Модель GigaAM v3 — тоже MIT, авторство команды GigaChat.
Подробности в [LICENSE](LICENSE).
