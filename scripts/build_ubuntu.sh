#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
python="$project_root/.venv/bin/python"
if [[ ! -x "$python" ]]; then python="$(command -v python3)"; fi
"$python" -c 'import PyInstaller, PySide6, prompt_toolkit' || {
  echo '构建 Python 需要安装 .[all] 与 pyinstaller。' >&2
  exit 1
}
dest="$project_root/bin/ubuntu"
work="$project_root/build/pyinstaller-ubuntu"
"$python" -m PyInstaller --noconfirm --clean --onefile --console --name m3-reader --distpath "$dest" --workpath "$work" --specpath "$work" --paths "$project_root" --collect-submodules prts_tool.collectors --exclude-module PySide6 --exclude-module PIL --exclude-module numpy "$project_root/scripts/entry_cli.py"
"$python" -m PyInstaller --noconfirm --clean --onefile --windowed --name m3-reader-gui --add-data "$project_root/assets/icon.png:assets" --distpath "$dest" --workpath "$work" --specpath "$work" --paths "$project_root" --collect-submodules prts_tool.collectors --hidden-import PySide6.QtPdf --hidden-import PySide6.QtPdfWidgets "$project_root/scripts/entry_gui.py"
cat > "$dest/m3-reader-gui.desktop" <<EOF
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
chmod +x "$dest/m3-reader-gui" "$dest/m3-reader" "$dest/m3-reader-gui.desktop"
echo "程序位于 $dest。双击 m3-reader-gui；终端中直接运行 m3-reader。"

