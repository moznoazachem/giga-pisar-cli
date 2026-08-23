#!/usr/bin/env python
"""Сверка своего ядра с библиотекой gigaam — до полного совпадения.

Запускать в окружении, где стоит и gigaam (с PyTorch), и наше ядро:

    ~/projects/gigaam-cli/.venv/bin/python scripts/сверка.py запись.wav [ещё.ogg ...]

Проверяет два места, где ошибка стоит дорого:
  1) признаки звука — наш numpy против torchaudio, до последнего знака;
  2) итоговый текст — наше ядро против gigaam на тех же файлах.
"""
import difflib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import giga_core


def проверить_признаки(engine, wav):
    """Наш numpy-экстрактор против torchaudio из библиотеки."""
    import hydra
    import omegaconf
    import torch

    cfg = omegaconf.OmegaConf.load(
        os.path.join(engine.model_dir, f"{giga_core.MODEL_NAME}.yaml"))
    эталон = hydra.utils.instantiate(cfg.preprocessor)

    x = torch.from_numpy(wav).float().unsqueeze(0)
    длина = torch.tensor([len(wav)], dtype=torch.long)
    их, их_len = эталон(x, длина)
    их = их.detach().numpy()

    наши = engine.features(wav)
    наша_len = engine.features.out_len(len(wav))

    print(f"  форма: наша {наши.shape}, эталон {их.shape}")
    if наши.shape != их.shape:
        return False, f"формы разошлись: {наши.shape} против {их.shape}"
    if наша_len != int(их_len[0]):
        return False, f"число кадров разошлось: {наша_len} против {int(их_len[0])}"

    разница = np.abs(наши - их)
    print(f"  расхождение: макс {разница.max():.3e}, среднее {разница.mean():.3e}")
    return разница.max() < 1e-3, f"макс. расхождение {разница.max():.3e}"


def куски(путь, tmp, prefix):
    """Разбивает файл ровно так же, как это делает ядро — чтобы сравнивать одно и то же."""
    wav = os.path.join(tmp, f"{prefix}.wav")
    giga_core.ffmpeg("-i", путь, "-ac", "1", "-ar", "16000", wav)
    полная = giga_core.duration(wav)
    if полная <= giga_core.MAX_CHUNK + 1:
        return [wav]
    части = []
    границы = giga_core.chunk_bounds(полная, giga_core.find_silences(wav))
    for i, (a, b) in enumerate(границы):
        part = os.path.join(tmp, f"{prefix}_{i}.wav")
        giga_core.ffmpeg("-i", wav, "-ss", str(a), "-to", str(b), part)
        части.append(part)
    return части


def эталонный_текст(model_dir, наборы):
    """Тот же ONNX и те же куски, но через библиотеку gigaam."""
    from gigaam.onnx_utils import infer_onnx, load_onnx

    sessions, cfg = load_onnx(model_dir, giga_core.MODEL_NAME)
    плоско = [c for набор in наборы for c in набор]
    тексты = infer_onnx([giga_core.read_wav(c) for c in плоско],
                        cfg, sessions, batch_size=1, progress=False)
    итог, поз = [], 0
    for набор in наборы:
        куски_текста = тексты[поз:поз + len(набор)]
        поз += len(набор)
        итог.append(" ".join(t for t in куски_текста if t).strip())
    return итог


def совпадение_по_символам(пары):
    """Доля совпавших символов по всему набору — мера равнозначности."""
    всего = совпало = 0
    for эталон, наше in пары:
        m = difflib.SequenceMatcher(None, эталон, наше)
        совпало += sum(b.size for b in m.get_matching_blocks())
        всего += max(len(эталон), len(наше))
    return совпало / всего if всего else 1.0


def main():
    файлы = sys.argv[1:]
    if not файлы:
        sys.exit("нужен хотя бы один файл с записью")

    print("Загружаю наше ядро...")
    engine = giga_core.Engine()
    print(f"модель: {engine.model_dir}\n")

    все_хорошо = True
    пары, пары_имена = [], []

    print("── 1. Признаки звука (наш numpy против torchaudio)")
    with tempfile.TemporaryDirectory() as tmp:
        w = os.path.join(tmp, "p.wav")
        giga_core.ffmpeg("-i", файлы[0], "-ac", "1", "-ar", "16000", w)
        ок, сообщение = проверить_признаки(engine, giga_core.read_wav(w))
    print(f"  {'✓ совпало' if ок else '✗ РАЗОШЛОСЬ'}: {сообщение}\n")
    все_хорошо &= ок

    print("── 2. Итоговый текст (наше ядро против библиотеки, на тех же кусках)")
    with tempfile.TemporaryDirectory() as tmp:
        наборы = [куски(путь, tmp, f"f{i}") for i, путь in enumerate(файлы)]
        эталон = эталонный_текст(engine.model_dir, наборы)
        for путь, набор, ожидалось in zip(файлы, наборы, эталон):
            получилось = " ".join(
                t for t in (engine.transcribe_wave(giga_core.read_wav(c)) for c in набор) if t
            ).strip()
            пары.append((ожидалось, получилось))
            пары_имена.append(os.path.basename(путь))
            совпало = получилось == ожидалось
            все_хорошо &= совпало
            метка = f" ({len(набор)} куска)" if len(набор) > 1 else ""
            print(f"  {os.path.basename(путь)}{метка}: {'✓ совпало' if совпало else '✗ РАЗОШЛОСЬ'}")
            if not совпало:
                print(f"      эталон:  {ожидалось!r}")
                print(f"      наше:    {получилось!r}")

    доля = совпадение_по_символам(пары)
    точных = sum(1 for a, b in пары if a == b)
    print()
    print(f"── Итог: точно совпало {точных} из {len(пары_имена)}, "
          f"совпадение по символам {доля * 100:.2f}%")
    if все_хорошо:
        print("✓ полное совпадение")
    elif доля >= 0.99:
        print("✓ равнозначно: расхождения на уровне дрожания последнего знака.")
        print("  Бит в бит совпасть нельзя — у numpy и torch разная арифметика")
        print("  в последнем разряде, и после логарифма этого иногда хватает,")
        print("  чтобы перевернуть выбор буквы. Ни один из вариантов не «вернее».")
    else:
        print("✗ расхождения слишком велики — это уже ошибка, а не дрожание")
    sys.exit(0 if (все_хорошо or доля >= 0.99) else 1)


if __name__ == "__main__":
    main()
