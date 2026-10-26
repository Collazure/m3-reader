#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
python="${M3_READER_PYTHON:-$project_root/.venv/bin/python}"
if [[ ! -x "$python" ]]; then python="$(command -v python3)"; fi
"$python" -c 'import PyInstaller, PySide6, prompt_toolkit' || {
  echo '构建 Python 需要安装 .[all] 与 pyinstaller。' >&2
  exit 1
}
dest="$project_root/bin/ubuntu"
work="$project_root/build/pyinstaller-ubuntu"
mkdir -p "$dest" "$work"
staging="$(mktemp -d "$work/staging.XXXXXX")"
trap 'rm -rf "$staging"' EXIT
excludes=(
  --exclude-module PySide6.Qt3DAnimation
  --exclude-module PySide6.Qt3DCore
  --exclude-module PySide6.Qt3DExtras
  --exclude-module PySide6.Qt3DInput
  --exclude-module PySide6.Qt3DLogic
  --exclude-module PySide6.Qt3DRender
  --exclude-module PySide6.QtBluetooth
  --exclude-module PySide6.QtCharts
  --exclude-module PySide6.QtDataVisualization
  --exclude-module PySide6.QtGraphs
  --exclude-module PySide6.QtGraphsWidgets
  --exclude-module PySide6.QtHelp
  --exclude-module PySide6.QtHttpServer
  --exclude-module PySide6.QtLocation
  --exclude-module PySide6.QtMultimedia
  --exclude-module PySide6.QtMultimediaWidgets
  --exclude-module PySide6.QtNetworkAuth
  --exclude-module PySide6.QtNfc
  --exclude-module PySide6.QtPositioning
  --exclude-module PySide6.QtQml
  --exclude-module PySide6.QtQuick
  --exclude-module PySide6.QtQuick3D
  --exclude-module PySide6.QtQuickControls2
  --exclude-module PySide6.QtQuickWidgets
  --exclude-module PySide6.QtRemoteObjects
  --exclude-module PySide6.QtScxml
  --exclude-module PySide6.QtSensors
  --exclude-module PySide6.QtSerialBus
  --exclude-module PySide6.QtSerialPort
  --exclude-module PySide6.QtSpatialAudio
  --exclude-module PySide6.QtSql
  --exclude-module PySide6.QtStateMachine
  --exclude-module PySide6.QtTest
  --exclude-module PySide6.QtTextToSpeech
  --exclude-module PySide6.QtUiTools
  --exclude-module PySide6.QtWebChannel
  --exclude-module PySide6.QtWebEngineCore
  --exclude-module PySide6.QtWebEngineQuick
  --exclude-module PySide6.QtWebEngineWidgets
  --exclude-module PySide6.QtWebSockets
  --exclude-module PySide6.QtWebView
  --exclude-module tkinter
  --exclude-module unittest
  --exclude-module pydoc
  --exclude-module PIL
  --exclude-module numpy
)
"$python" -m PyInstaller --noconfirm --clean --onefile --strip --optimize 2 --console --name m3-reader --distpath "$staging" --workpath "$work" --specpath "$work" --paths "$project_root" --collect-submodules prts_tool.collectors --exclude-module PySide6 "${excludes[@]}" "$project_root/scripts/entry_cli.py"
"$python" -m PyInstaller --noconfirm --clean --onefile --strip --optimize 2 --windowed --name m3-reader-gui --add-data "$project_root/assets/icon.png:assets" --distpath "$staging" --workpath "$work" --specpath "$work" --paths "$project_root" --collect-submodules prts_tool.collectors --hidden-import PySide6.QtPdf --hidden-import PySide6.QtPdfWidgets "${excludes[@]}" "$project_root/scripts/entry_gui.py"
cat > "$staging/m3-reader-gui.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=M3 Reader 资料终端
Comment=阅读与更新 PRTS 资料
Exec="$dest/m3-reader-gui"
Path=$project_root
Icon=$project_root/assets/icon.png
Terminal=false
Categories=Office;Utility;
EOF
backup="$(mktemp -d "$work/backup.XXXXXX")"
names=(m3-reader m3-reader-gui m3-reader-gui.desktop)
installed=()
restore_previous() {
  for name in "${installed[@]}"; do rm -f "$dest/$name"; done
  for name in "${names[@]}"; do
    if [[ -e "$backup/$name" ]]; then mv -f "$backup/$name" "$dest/$name"; fi
  done
}
for name in "${names[@]}"; do
  if [[ -e "$dest/$name" ]] && ! mv -f "$dest/$name" "$backup/$name"; then
    restore_previous
    exit 1
  fi
done
for name in "${names[@]}"; do
  if mv -f "$staging/$name" "$dest/$name"; then
    installed+=("$name")
  else
    restore_previous
    exit 1
  fi
done
rm -rf "$backup"
chmod +x "$dest/m3-reader-gui" "$dest/m3-reader" "$dest/m3-reader-gui.desktop"
echo "程序位于 $dest。双击 m3-reader-gui；终端中直接运行 m3-reader。"

