#!/usr/bin/env bash
# 安装 m3-reader 命令（无需 pip / 虚拟环境）。
#
# 在 ${M3_READER_BIN_DIR:-~/.local/bin} 建立指向本项目 scripts/ 的软链接。
# 项目移动或重新挂载后，重新运行本脚本即可。
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
bin_dir="${M3_READER_BIN_DIR:-$HOME/.local/bin}"

mkdir -p "$bin_dir"
for name in m3-reader m3-reader-gui; do
    chmod +x "$project_root/scripts/$name"
    ln -sfn "$project_root/scripts/$name" "$bin_dir/$name"
    printf '已链接 %s -> %s\n' "$bin_dir/$name" "$project_root/scripts/$name"
done

case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) printf '\n注意：%s 不在 PATH 中，请把它加入 shell 配置。\n' "$bin_dir" ;;
esac

printf '\n验证：\n'
"$bin_dir/m3-reader" --version
