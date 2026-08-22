#!/bin/bash
# Установка Гига Писаря. Проверено на Ubuntu 22.04 и 24.04.
#   bash install.sh [папка]       по умолчанию /opt/giga-pisar
set -euo pipefail

DEST="${1:-/opt/giga-pisar}"
REPO="https://github.com/moznoazachem/giga-pisar"
MODEL_URL="$REPO/releases/latest/download/gigaam-v3-onnx-int8.tar.gz"

echo "── системные пакеты"
if command -v apt-get >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3 python3-venv ffmpeg curl >/dev/null
else
  echo "   не Debian/Ubuntu — поставьте python3, python3-venv и ffmpeg сами"
fi

sudo mkdir -p "$DEST"
sudo chown "$(id -u):$(id -g)" "$DEST"

echo "── окружение"
python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install -q --upgrade pip

# Версии подобраны опытным путём и важны:
#  * gigaam ставится ТОЛЬКО из исходников — в PyPI лежит 0.1.0 со старым API,
#    в котором нет load_onnx/infer_onnx, нужных для модели v3;
#  * onnxruntime строго 1.23.x — этого требует сам gigaam 0.2.0;
#  * numpy 2.x — с первой веткой onnxruntime падает на импорте.
# torch ставим отдельно и в версии для процессора: gigaam импортирует его
# при загрузке пакета, но для самого распознавания он не нужен — считает
# onnxruntime. Сборка под видеокарту весит около двух гигабайт, эта — двести мегабайт.
echo "── torch для процессора (~200 МБ)"
"$DEST/.venv/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu

echo "── gigaam из исходников"
"$DEST/.venv/bin/pip" install -q "git+https://github.com/salute-developers/GigaAM.git"
"$DEST/.venv/bin/pip" install -q "onnxruntime==1.23.*" "numpy>=2"

echo "── модель (204 МБ архив, 309 МБ на диске)"
mkdir -p "$DEST/model"
curl -fL --progress-bar "$MODEL_URL" | tar xz -C "$DEST/model" --strip-components=1

# В yaml прописан путь к токенизатору. В архиве он оставлен заглушкой,
# подставляем настоящий — иначе модель не запустится.
sed -i "s|model_path: .*|model_path: $DEST/model/v3_e2e_rnnt_tokenizer.model|" \
    "$DEST/model/v3_e2e_rnnt.yaml"

echo "── скрипт"
curl -fsSL "$REPO/raw/main/pisar.py" -o "$DEST/pisar.py"

sudo tee /usr/local/bin/pisar >/dev/null <<LAUNCHER
#!/bin/bash
PISAR_MODEL_DIR="$DEST/model" exec "$DEST/.venv/bin/python" "$DEST/pisar.py" "\$@"
LAUNCHER
sudo chmod +x /usr/local/bin/pisar

echo
echo "Готово. Проверка:  pisar запись.ogg"
