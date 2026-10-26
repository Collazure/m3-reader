#!/bin/sh
# Debian launcher: installed program files are separate from each user's data.
set -eu

if [ -z "${M3_READER_HOME:-}" ]; then
    legacy_link="$HOME/.local/bin/m3-reader"
    legacy_root=""
    if [ -L "$legacy_link" ]; then
        legacy_target=$(readlink -f "$legacy_link" || true)
        case "$legacy_target" in
            */bin/ubuntu/m3-reader) legacy_root=${legacy_target%/bin/ubuntu/m3-reader} ;;
            */.venv/bin/m3-reader) legacy_root=${legacy_target%/.venv/bin/m3-reader} ;;
            */scripts/m3-reader) legacy_root=${legacy_target%/scripts/m3-reader} ;;
        esac
    fi
    if [ -n "$legacy_root" ] && [ -d "$legacy_root/resources" ]; then
        M3_READER_HOME=$legacy_root
    else
        M3_READER_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/m3-reader"
    fi
fi
export M3_READER_HOME
mkdir -p "$M3_READER_HOME/resources/collected/prts_text" \
    "$M3_READER_HOME/resources/collected/terra" \
    "$M3_READER_HOME/resources/ocr/terra_text" \
    "$M3_READER_HOME/resources/local" \
    "$M3_READER_HOME/resources/updates/new" \
    "$M3_READER_HOME/workspace"

case "${0##*/}" in
    m3-reader-gui) exec /opt/m3-reader/bin/ubuntu/m3-reader-gui "$@" ;;
    *) exec /opt/m3-reader/bin/ubuntu/m3-reader "$@" ;;
esac
