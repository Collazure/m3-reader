#!/usr/bin/env bash
# Install or upgrade the Linux portable build without replacing user resources.
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
source_cli="$project_root/bin/ubuntu/m3-reader"
source_gui="$project_root/bin/ubuntu/m3-reader-gui"
for source_file in "$source_cli" "$source_gui"; do
  if [[ ! -f "$source_file" ]]; then echo "安装包不完整：$source_file" >&2; exit 1; fi
done

install_home="$HOME/.local"
legacy_root=""
legacy_link="$install_home/bin/m3-reader"
if [[ -L "$legacy_link" ]]; then
  legacy_target="$(readlink -f "$legacy_link" || true)"
  case "$legacy_target" in
    */bin/ubuntu/m3-reader) legacy_root="${legacy_target%/bin/ubuntu/m3-reader}" ;;
    */.venv/bin/m3-reader) legacy_root="${legacy_target%/.venv/bin/m3-reader}" ;;
    */scripts/m3-reader) legacy_root="${legacy_target%/scripts/m3-reader}" ;;
  esac
fi
install_root="${M3_READER_INSTALL_DIR:-${legacy_root:-$install_home/opt/m3-reader}}"
mkdir -p "$install_root/bin/ubuntu" "$install_root/assets" \
  "$install_root/resources/collected/prts_text" "$install_root/resources/collected/terra" \
  "$install_root/resources/ocr/terra_text" "$install_root/resources/local" \
  "$install_root/resources/updates/new" "$install_root/workspace" \
  "$install_home/bin" "$install_home/share/applications"
install_root="$(cd "$install_root" && pwd)"

# Moving to an explicitly chosen directory copies missing data, never overwriting it.
if [[ -n "$legacy_root" && "$legacy_root" != "$install_root" ]]; then
  for name in resources workspace; do
    if [[ -d "$legacy_root/$name" ]]; then
      cp -an "$legacy_root/$name/." "$install_root/$name/"
    fi
  done
fi

staging="$(mktemp -d "$install_root/.install-XXXXXX")"
trap 'rm -rf "$staging"' EXIT
cp "$source_cli" "$staging/m3-reader"
cp "$source_gui" "$staging/m3-reader-gui"
cp "$project_root/assets/icon.png" "$staging/icon.png"
chmod 755 "$staging/m3-reader" "$staging/m3-reader-gui"
installed=()
names=(m3-reader m3-reader-gui)
restore_previous() {
  for name in "${installed[@]}"; do rm -f "$install_root/bin/ubuntu/$name"; done
  for name in "${names[@]}"; do
    if [[ -e "$staging/old-$name" ]]; then
      mv -f "$staging/old-$name" "$install_root/bin/ubuntu/$name"
    fi
  done
}
for name in "${names[@]}"; do
  if [[ -e "$install_root/bin/ubuntu/$name" ]] && \
     ! mv -f "$install_root/bin/ubuntu/$name" "$staging/old-$name"; then
    restore_previous
    exit 1
  fi
done
for name in "${names[@]}"; do
  if mv -f "$staging/$name" "$install_root/bin/ubuntu/$name"; then
    installed+=("$name")
  else
    restore_previous
    exit 1
  fi
done
mv -f "$staging/icon.png" "$install_root/assets/icon.png"
for name in "${names[@]}"; do
  link="$install_home/bin/$name"
  if [[ -e "$link" && ! -L "$link" ]]; then
    echo "不能替换已有的普通文件：$link" >&2
    exit 1
  fi
  ln -sfn "$install_root/bin/ubuntu/$name" "$link"
done
source "$project_root/scripts/ensure_user_path.sh"
ensure_m3_user_path "$install_home/bin"
cat > "$install_home/share/applications/m3-reader.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=M3 Reader
Comment=阅读和更新 PRTS 资料
Exec="$install_root/bin/ubuntu/m3-reader-gui"
Path=$install_root
Icon=$install_root/assets/icon.png
Terminal=false
Categories=Office;Utility;
DESKTOP
echo "安装完成：$install_root。再次运行此脚本会更新程序并保留 resources/ 与 workspace/。"
