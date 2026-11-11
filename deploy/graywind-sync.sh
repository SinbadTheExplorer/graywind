#!/bin/bash
# Run by graywind-sync.service as user mavis. Fetches the newest Graywind
# state (public repo, shallow) and rewrites the facts file the API reloads.
# Pages the owner once after 3 failures in a row, not on every blip.
set -uo pipefail

STATE=/var/lib/mavis
REPO="$STATE/graywind-state"
FAILS="$STATE/graywind-sync.failures"
URL="https://github.com/SinbadTheExplorer/graywind.git"

fresh_clone() {
    rm -rf "$REPO"
    git clone --quiet --depth 1 --branch main "$URL" "$REPO"
}

sync_once() {
    if [ -d "$REPO/.git" ]; then
        # A damaged checkout (an interrupted fetch) heals by re-cloning.
        { git -C "$REPO" fetch --quiet --depth 1 origin main &&
          git -C "$REPO" reset --quiet --hard origin/main; } || fresh_clone || return 1
    else
        fresh_clone || return 1
    fi
    /opt/mavis/mavis/.venv/bin/python /opt/mavis/mavis/scripts/extract_graywind_grounding.py \
        --repo "$REPO" --out "$STATE/graywind_grounding.json"
}

if sync_once; then
    rm -f "$FAILS"
    exit 0
fi

n=$(( $(cat "$FAILS" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$FAILS"
echo "graywind-sync: failed ($n in a row)" >&2
if [ "$n" -eq 3 ]; then
    case "${MAVIS_NTFY_TOPIC:-}" in
        ""|*[!A-Za-z0-9_-]*) ;;
        *) curl -fsS -m 10 -H "Title: Johnny data stale" -H "Tags: warning" \
               -d "Graywind sync failed 3 times in a row; Johnny's trading facts are going stale." \
               "https://ntfy.sh/$MAVIS_NTFY_TOPIC" >/dev/null || true ;;
    esac
fi
exit 1
