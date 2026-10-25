#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"

venv_python="$project_root/.venv/bin/python"
if python3 -m venv "$project_root/.venv" 2>/dev/null \
   && "$venv_python" -m pip --version >/dev/null 2>&1; then
    "$venv_python" -m pip install --upgrade pip
    "$venv_python" -m pip install -e "$project_root[all]"
    ln -sfn "$project_root/.venv/bin/m3-reader" "$HOME/.local/bin/m3-reader"
    ln -sfn "$project_root/.venv/bin/m3-reader-gui" "$HOME/.local/bin/m3-reader-gui"
    gui_exec="$project_root/.venv/bin/m3-reader-gui"
else
    # 系统 Python 没有 venv/pip（例如 Debian/Ubuntu 的 PEP 668 环境）：
    # 直接用系统解释器 + 免安装启动器，资料与代码都不复制。
    rm -rf "$project_root/.venv"
    echo "未找到可用的 venv/pip，改用免安装启动器。"
    M3_READER_BIN_DIR="$HOME/.local/bin" bash "$project_root/scripts/install_cli.sh"
    gui_exec="$project_root/scripts/m3-reader-gui"
fi

cat > "$HOME/.local/share/applications/m3-reader.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=M3 Reader
Comment=阅读和更新剧情资料
Exec="$gui_exec"
Path=$project_root
Terminal=false
Categories=Office;Utility;
EOF
echo "安装完成。应用菜单可启动 M3 Reader；终端可运行 m3-reader（确保 ~/.local/bin 在 PATH 中）。"
