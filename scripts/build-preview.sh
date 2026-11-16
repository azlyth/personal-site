#!/usr/bin/env bash
# Build the working tree WITH drafts into a scratch dir, for the editor's
# Preview button. Usage: build-preview.sh BASE_URL OUT_DIR
#
# Same container, same --user and same pre-0.19 legacy-config handling as
# build-site.sh, but it never touches public/, the live web container, git or
# Cloudflare: the output dir is the editor's own gitignored editor/.preview.
# OUT_DIR is wiped by zola's --force, so never point this at anything else.
set -euo pipefail

BASE_URL="${1:?usage: build-preview.sh BASE_URL OUT_DIR}"
OUT_DIR="${2:?usage: build-preview.sh BASE_URL OUT_DIR}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEGACY_CONFIG_REL=".build-preview-legacy-config.toml"
LEGACY_CONFIG_ABS="$REPO/$LEGACY_CONFIG_REL"
trap 'rm -f "$LEGACY_CONFIG_ABS"' EXIT

case "$OUT_DIR" in "$REPO"/*) ;; *) echo "OUT_DIR must be inside the repo" >&2; exit 2;; esac
mkdir -p "$OUT_DIR"
OUT_REL="${OUT_DIR#"$REPO"/}"

ZOLA_VERSION="$(docker run --rm --entrypoint zola personal-site-zola --version | awk '{print $2}')"
ZOLA_MINOR="$(echo "$ZOLA_VERSION" | cut -d. -f2)"
CONFIG_ARGS=()
if [ "$ZOLA_MINOR" -lt 19 ]; then
  # Mirrors build-site.sh: a copy of config.toml carrying the old feed keys too.
  python3 - "$REPO/config.toml" "$LEGACY_CONFIG_ABS" <<'PY'
import sys, tomllib
src, dst = sys.argv[1], sys.argv[2]
cfg = tomllib.load(open(src, "rb"))
lines = open(src, encoding="utf-8").read().splitlines(keepends=True)
extra = []
if "generate_feeds" in cfg:
    extra.append(f"generate_feed = {str(cfg['generate_feeds']).lower()}\n")
if cfg.get("feed_filenames"):
    extra.append(f'feed_filename = "{cfg["feed_filenames"][0]}"\n')
at = next((i for i, l in enumerate(lines) if l.lstrip().startswith("[")), len(lines))
lines[at:at] = extra + ["\n"]
open(dst, "w", encoding="utf-8").writelines(lines)
PY
  CONFIG_ARGS=(--config "/project/$LEGACY_CONFIG_REL")
fi

docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "$REPO:/project" \
  -w /project \
  --entrypoint zola \
  personal-site-zola \
  "${CONFIG_ARGS[@]}" build --drafts --base-url "$BASE_URL" --output-dir "/project/$OUT_REL" --force
