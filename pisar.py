#!/usr/bin/env python
"""Гига Писарь — распознавание русской речи через GigaAM v3 (ONNX, CPU).

    pisar запись.ogg              распознать файл, вывести текст
    pisar a.m4a b.wav c.mp3       несколько файлов подряд
    pisar --model-dir DIR файл    указать папку с моделью явно

Принимает любой формат, который понимает ffmpeg. Записи длиннее 25 секунд
режет на куски по паузам между фразами, а не посреди слова, и склеивает
результат. Работает целиком на своей машине — в сеть ничего не уходит.

Папка с моделью берётся из переменной PISAR_MODEL_DIR, иначе из
/opt/gigaam/onnx_int8, иначе из папки рядом со скриптом.
"""
import contextlib
import os
import subprocess
import sys
import tempfile
import warnings
import wave

warnings.filterwarnings("ignore")

MAX_CHUNK = 24.0          # предел одного прохода модели — 25 секунд
SILENCE_DB = -35          # порог тишины для нарезки
SILENCE_MIN = 0.3         # минимальная длина паузы, секунды
MODEL_NAME = "v3_e2e_rnnt"

DEFAULT_DIRS = [
    os.environ.get("PISAR_MODEL_DIR", ""),
    "/opt/gigaam/onnx_int8",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "model"),
]


def find_model_dir() -> str:
    for path in DEFAULT_DIRS:
        if path and os.path.exists(os.path.join(path, f"{MODEL_NAME}.yaml")):
            return path
    sys.exit(
        "Не нашёл модель. Укажите папку через PISAR_MODEL_DIR или --model-dir.\n"
        "Скачать: https://github.com/moznoazachem/giga-pisar/releases"
    )


def ffmpeg(*args) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def find_silences(path: str) -> list[float]:
    """Середины пауз — кандидаты в точки разреза."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-af",
         f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    points, start = [], None
    for line in out.stderr.splitlines():
        if "silence_start:" in line:
            start = float(line.split("silence_start:")[1].strip())
        elif "silence_end:" in line and start is not None:
            end = float(line.split("silence_end:")[1].split("|")[0].strip())
            points.append((start + end) / 2)
            start = None
    return points


def chunk_bounds(total: float, silences: list[float]) -> list[tuple[float, float]]:
    """Куски не длиннее предела, разрез — по последней паузе перед ним."""
    bounds, pos = [], 0.0
    while total - pos > MAX_CHUNK:
        candidates = [s for s in silences if pos + 3 < s <= pos + MAX_CHUNK]
        cut = candidates[-1] if candidates else pos + MAX_CHUNK
        bounds.append((pos, cut))
        pos = cut
    bounds.append((pos, total))
    return bounds


def read_wav(path: str):
    import numpy as np
    with wave.open(path, "rb") as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(path: str, sessions, cfg, tmpdir: str) -> str:
    from gigaam.onnx_utils import infer_onnx

    wav = os.path.join(tmpdir, "in.wav")
    ffmpeg("-i", path, "-ac", "1", "-ar", "16000", wav)

    total = duration(wav)
    if total <= MAX_CHUNK + 1:
        files = [wav]
    else:
        files = []
        for i, (a, b) in enumerate(chunk_bounds(total, find_silences(wav))):
            part = os.path.join(tmpdir, f"part{i}.wav")
            ffmpeg("-i", wav, "-ss", str(a), "-to", str(b), part)
            files.append(part)

    texts = infer_onnx([read_wav(f) for f in files], cfg, sessions,
                       batch_size=1, progress=False)
    return " ".join(t for t in texts if t).strip()


def main() -> None:
    args = sys.argv[1:]
    model_dir = ""
    if "--model-dir" in args:
        i = args.index("--model-dir")
        model_dir = args[i + 1]
        del args[i:i + 2]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__, file=sys.stderr)
        sys.exit(0 if args else 1)

    model_dir = model_dir or find_model_dir()
    real_stdout = sys.stdout

    # библиотека печатает служебное в stdout — уводим,
    # чтобы вызывающему достался только чистый текст
    with contextlib.redirect_stdout(sys.stderr):
        from gigaam.onnx_utils import load_onnx
        sessions, cfg = load_onnx(model_dir, MODEL_NAME)

        results = []
        for path in args:
            with tempfile.TemporaryDirectory() as tmpdir:
                results.append((path, transcribe(path, sessions, cfg, tmpdir)))

    for path, text in results:
        if len(args) > 1:
            print(f"── {os.path.basename(path)}", file=sys.stderr)
        print(text, file=real_stdout)


if __name__ == "__main__":
    main()
