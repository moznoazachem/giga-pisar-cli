#!/bin/bash
# Установка Гига Писаря. Проверено на Ubuntu 22.04 и 24.04.
#   bash install.sh [папка]            по умолчанию /opt/giga-pisar
#   bash install.sh --service [папка]  ещё и поднять сервер службой
#   bash install.sh --hotkey [папка]   диктовка по правому Ctrl (Linux, X11)
#   bash install.sh --hotkey --no-mic-sleep   и не усыплять микрофон
set -euo pipefail

SERVICE=0
HOTKEY=0
NO_MIC_SLEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --service) SERVICE=1 ;;
    --hotkey) HOTKEY=1 ;;
    --no-mic-sleep) NO_MIC_SLEEP=1 ;;
    --*) echo "не знаю флага $1"; exit 1 ;;
    *) break ;;
  esac
  shift
done
if [ "$NO_MIC_SLEEP" = "1" ] && [ "$HOTKEY" = "0" ]; then
  echo "--no-mic-sleep имеет смысл только вместе с --hotkey"; exit 1
fi

DEST="${1:-/opt/giga-pisar}"
REPO="https://github.com/moznoazachem/giga-pisar-cli"
MODEL_URL="$REPO/releases/latest/download/gigaam-v3-onnx-int8.tar.gz"

echo "── системные пакеты"
if command -v apt-get >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3 python3-venv ffmpeg curl >/dev/null
  # Для диктовки: xclip вставляет текст, parec из pulseaudio-utils пишет звук.
  [ "$HOTKEY" = "1" ] && sudo apt-get install -y -qq xclip pulseaudio-utils >/dev/null
else
  echo "   не Debian/Ubuntu — поставьте python3, python3-venv и ffmpeg сами"
  [ "$HOTKEY" = "1" ] && echo "   для диктовки ещё xclip и parec (pulseaudio-utils)"
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
# pynput тянет evdev, а тот собирается из исходников и просит заголовки
# ядра и компилятор. Под X11 он не нужен: там хватает python-xlib.
[ "$HOTKEY" = "1" ] && "$DEST/.venv/bin/pip" install -q --no-deps pynput python-xlib six

echo "── модель (204 МБ архив, 309 МБ на диске)"
mkdir -p "$DEST/model"
curl -fL --progress-bar "$MODEL_URL" | tar xz -C "$DEST/model" --strip-components=1
# Путь к токенизатору в yaml прописан с той машины, где делали экспорт.
# Править его больше не нужно: ядро сперва ищет токенизатор рядом с моделью.

echo "── скрипты"
curl -fsSL "$REPO/raw/main/giga_core.py" -o "$DEST/giga_core.py"
curl -fsSL "$REPO/raw/main/pisar.py" -o "$DEST/pisar.py"
[ "$HOTKEY" = "1" ] && curl -fsSL "$REPO/raw/main/hotkey.py" -o "$DEST/hotkey.py"

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

if [ "$HOTKEY" = "1" ]; then
  echo "── диктовка по правому Ctrl"
  sudo tee /usr/local/bin/pisar-hotkey >/dev/null <<LAUNCHER
#!/bin/bash
export PISAR_MODEL_DIR="$DEST/model"
# Без XDG_RUNTIME_DIR лог в ~/.cache, а не в общий /tmp под известным именем.
LOG="\${XDG_RUNTIME_DIR:-\$HOME/.cache}"
mkdir -p "\$LOG"
exec "$DEST/.venv/bin/python" "$DEST/hotkey.py" > "\$LOG/pisar-hotkey.log" 2>&1
LAUNCHER
  sudo chmod +x /usr/local/bin/pisar-hotkey

  # Автозапуск при входе в систему — свой у каждого пользователя.
  mkdir -p "$HOME/.config/autostart"
  cat > "$HOME/.config/autostart/giga-pisar.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Giga Pisar
Comment=Dictation on right Ctrl
Exec=/usr/local/bin/pisar-hotkey
DESKTOP

  if [ "$NO_MIC_SLEEP" = "1" ]; then
    # Звуковая карта просыпается ~0,2 с, и начало фразы пропадает.
    # Не даём микрофонам засыпать. Звук при этом никто не читает,
    # пока не зажата клавиша, но карта не спит — это батарея.
    echo "── микрофон не засыпает (WirePlumber)"
    if wireplumber --version 2>/dev/null | grep -q "libwireplumber 0\.4"; then
      mkdir -p "$HOME/.config/wireplumber/main.lua.d"
      cat > "$HOME/.config/wireplumber/main.lua.d/51-pisar-mic-nosuspend.lua" <<'WP'
-- Гига Писарь: не усыплять микрофоны. Удалить файл, чтобы вернуть.
table.insert(alsa_monitor.rules, {
  matches = { { { "node.name", "matches", "alsa_input.*" } } },
  apply_properties = { ["session.suspend-timeout-seconds"] = 0 },
})
WP
    else
      mkdir -p "$HOME/.config/wireplumber/wireplumber.conf.d"
      cat > "$HOME/.config/wireplumber/wireplumber.conf.d/51-pisar-mic-nosuspend.conf" <<'WP'
# Гига Писарь: не усыплять микрофоны. Удалить файл, чтобы вернуть.
monitor.alsa.rules = [
  {
    matches = [ { node.name = "~alsa_input.*" } ]
    actions = { update-props = { session.suspend-timeout-seconds = 0 } }
  }
]
WP
    fi
    systemctl --user restart wireplumber 2>/dev/null || true
  fi

  if [ "${XDG_SESSION_TYPE:-}" = "x11" ]; then
    pkill -f "$DEST/hotkey.py" 2>/dev/null || true
    setsid -f /usr/local/bin/pisar-hotkey
    echo "   запущена: держите правый Ctrl и говорите"
  else
    echo "   диктовка работает только в сеансе X11, а здесь ${XDG_SESSION_TYPE:-не графический сеанс}"
  fi
fi

echo
echo "Готово. Проверка:  pisar запись.ogg"
# без «|| true» set -e счёл бы обычную установку неудачной
[ "$SERVICE" = "1" ] && echo "           и:      curl http://127.0.0.1:8737/health" || true
