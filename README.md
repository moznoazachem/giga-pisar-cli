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

### One core, two shells

All the work lives in `giga_core.py`: audio preprocessing, model inference,
decoding. Two ways to call it:

| Shell | How | When |
|---|---|---|
| command line | `pisar file.ogg` | one-off transcriptions, scripts |
| server | `pisar --serve` | a stream of recordings: the model stays in memory |

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
curl -fsSL https://raw.githubusercontent.com/moznoazachem/giga-pisar/main/install.sh | bash
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

### Related project

[Giga Pisar for macOS](https://github.com/moznoazachem/giga) — dictation on
a hotkey: hold right ⌘, speak, release, the text lands in the active window.
Same core inside, ported to Swift.

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

### Одно ядро, две оболочки

Вся работа — в `giga_core.py`: подготовка звука, запуск модели, декодирование.
Сверху два способа обратиться:

| Оболочка | Как звать | Когда |
|---|---|---|
| командная строка | `pisar файл.ogg` | разовая расшифровка, скрипты |
| сервер | `pisar --serve` | поток записей: модель живёт в памяти |

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
curl -fsSL https://raw.githubusercontent.com/moznoazachem/giga-pisar/main/install.sh | bash
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

### Родственный проект

[Giga Pisar для macOS](https://github.com/moznoazachem/giga) — диктовка
по горячей клавише: зажал правый ⌘, сказал, отпустил, текст вставился
в активное окно. Внутри то же самое ядро, перенесённое на Swift.

### Лицензия

MIT. Модель GigaAM v3 — тоже MIT, авторство команды GigaChat.
Подробности в [LICENSE](LICENSE).
