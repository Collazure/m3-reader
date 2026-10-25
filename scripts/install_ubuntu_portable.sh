#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
desktop_dir="$HOME/.local/share/applications"
mkdir -p "$desktop_dir" "$HOME/.local/bin"
cat > "$desktop_dir/m3-reader.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=M3 Reader
Comment=阅读和更新剧情资料
Exec=$project_root/bin/ubuntu/m3-reader-gui
Path=$project_root
Icon=$project_root/assets/icon.png
Terminal=false
Categories=Office;Utility;
EOF
ln -sfn "$project_root/bin/ubuntu/m3-reader" "$HOME/.local/bin/m3-reader"
ln -sfn "$project_root/bin/ubuntu/m3-reader-gui" "$HOME/.local/bin/m3-reader-gui"
echo "安装完成。应用菜单可启动 M3 Reader；终端可运行 m3-reader。"
