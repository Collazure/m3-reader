#!/usr/bin/env bash
# Make per-user launchers available in new Bash/login shells.
ensure_m3_user_path() {
  local bin_dir="$1" profile
  if [[ "$bin_dir" != "$HOME/.local/bin" ]]; then
    printf '请把 %s 加入 PATH。\n' "$bin_dir"
    return
  fi
  for profile in "$HOME/.profile" "$HOME/.bashrc"; do
    if [[ -f "$profile" ]] && grep -Fq '# M3 Reader command path' "$profile"; then
      continue
    fi
    cat >> "$profile" <<'PROFILE'

# M3 Reader command path
if [ -d "$HOME/.local/bin" ]; then
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) export PATH="$HOME/.local/bin:$PATH" ;;
    esac
fi
PROFILE
  done
}
