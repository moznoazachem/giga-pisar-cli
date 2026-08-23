#!/bin/bash
# Установка Гига Писаря. Проверено на Ubuntu 22.04 и 24.04.
#   bash install.sh [папка]            по умолчанию /opt/giga-pisar
#   bash install.sh --service [папка]  ещё и поднять сервер службой
set -euo pipefail

SERVICE=0
if [ "${1:-}" = "--service" ]; then SERVICE=1; shift; fi

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

# Всё, что нужно для счёта, и ничего лишнего.
# Раньше здесь ставились пакет gigaam и PyTorch на четверть гигабайта:
# gigaam импортирует torch при загрузке, хотя считает не им, а onnxruntime.
# Теперь распознавание живёт в giga_core.py рядом, и ни то ни другое не нужно —
# окружение похудело примерно с гигабайта до полутора сотен мегабайт.
echo "── зависимости (около 150 МБ)"
"$DEST/.venv/bin/pip" install -q onnxruntime numpy sentencepiece pyyaml

echo "── модель (204 МБ архив, 309 МБ на диске)"
mkdir -p "$DEST/model"
curl -fL --progress-bar "$MODEL_URL" | tar xz -C "$DEST/model" --strip-components=1
# Путь к токенизатору в yaml прописан с той машины, где делали экспорт.
# Править его больше не нужно: ядро сперва ищет токенизатор рядом с моделью.

echo "── скрипты"
curl -fsSL "$REPO/raw/main/giga_core.py" -o "$DEST/giga_core.py"
curl -fsSL "$REPO/raw/main/pisar.py" -o "$DEST/pisar.py"

sudo tee /usr/local/bin/pisar >/dev/null <<LAUNCHER
#!/bin/bash
PISAR_MODEL_DIR="$DEST/model" exec "$DEST/.venv/bin/python" "$DEST/pisar.py" "\$@"
LAUNCHER
sudo chmod +x /usr/local/bin/pisar

if [ "$SERVICE" = "1" ]; then
  # Под кем крутить сервер. По умолчанию — тот, кто ставит; если ставят
  # от root, лучше назвать отдельного пользователя: PISAR_USER=имя.
  # Прав ему нужно немного — только читать папку с моделью.
  RUN_AS="${PISAR_USER:-$(id -un)}"
  if [ "$RUN_AS" = "root" ]; then
    echo "   сервер будет работать от root — лучше указать PISAR_USER=имя"
  fi
  echo "── служба (сервер держит модель в памяти), пользователь $RUN_AS"
  sudo tee /etc/systemd/system/pisar.service >/dev/null <<UNIT
[Unit]
Description=Гига Писарь — сервер распознавания речи
After=network.target

[Service]
Type=simple
User=$RUN_AS
Environment=PISAR_MODEL_DIR=$DEST/model
ExecStart=$DEST/.venv/bin/python $DEST/pisar.py --serve
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload
  sudo systemctl enable -q pisar
  sudo systemctl restart pisar
  echo "   сервер: http://127.0.0.1:8737"
fi

echo
echo "Готово. Проверка:  pisar запись.ogg"
# без «|| true» set -e счёл бы обычную установку неудачной
[ "$SERVICE" = "1" ] && echo "           и:      curl http://127.0.0.1:8737/health" || true
