#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
source_version="$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$project_root/prts_tool/__init__.py")"
if [[ -x "$project_root/bin/ubuntu/m3-reader" && -x "$project_root/bin/ubuntu/m3-reader-gui" &&
      -f "$project_root/scripts/install_ubuntu_portable.sh" &&
      "$("$project_root/bin/ubuntu/m3-reader" --version 2>/dev/null)" == "m3-reader, version $source_version" ]]; then
    exec bash "$project_root/scripts/install_ubuntu_portable.sh"
fi
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"

# An older source/portable installation may live in a different extracted folder.
legacy_link="$HOME/.local/bin/m3-reader"
if [[ -L "$legacy_link" ]]; then
    legacy_target="$(readlink -f "$legacy_link" || true)"
    legacy_root=""
    case "$legacy_target" in
        */bin/ubuntu/m3-reader) legacy_root="${legacy_target%/bin/ubuntu/m3-reader}" ;;
        */.venv/bin/m3-reader) legacy_root="${legacy_target%/.venv/bin/m3-reader}" ;;
        */scripts/m3-reader) legacy_root="${legacy_target%/scripts/m3-reader}" ;;
    esac
    if [[ -n "$legacy_root" && "$legacy_root" != "$project_root" ]]; then
        for name in resources workspace; do
            if [[ -d "$legacy_root/$name" ]]; then
                mkdir -p "$project_root/$name"
                cp -an "$legacy_root/$name/." "$project_root/$name/"
            fi
        done
    fi
fi

venv_python="$project_root/.venv/bin/python"
if python3 -m venv "$project_root/.venv" 2>/dev/null \
   && "$venv_python" -m pip --version >/dev/null 2>&1; then
    "$venv_python" -m pip install --upgrade pip
    "$venv_python" -m pip install -e "$project_root[all]"
    ln -sfn "$project_root/.venv/bin/m3-reader" "$HOME/.local/bin/m3-reader"
    ln -sfn "$project_root/.venv/bin/m3-reader-gui" "$HOME/.local/bin/m3-reader-gui"
    source "$project_root/scripts/ensure_user_path.sh"
    ensure_m3_user_path "$HOME/.local/bin"
    gui_exec="$project_root/.venv/bin/m3-reader-gui"
else
    # 系统 Python 没有 venv/pip（例如 Debian/Ubuntu 的 PEP 668 环境）：
    # 直接用系统解释器 + 免安装启动器，资料与代码都不复制。
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
Icon=$project_root/assets/icon.png
Terminal=false
Categories=Office;Utility;
EOF
echo "安装完成。应用菜单可启动 M3 Reader；终端可运行 m3-reader（确保 ~/.local/bin 在 PATH 中）。"
