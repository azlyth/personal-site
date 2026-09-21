#!/usr/bin/env bash
# Build the site into public/ atomically.
#
# zola build wipes its output directory first, so building straight into what
# nginx serves means a failed build leaves a half-empty site -- the exact
# failure that pinned 404s in Cloudflare's cache for meetup.astoria.app.
# Build into a scratch dir, then swap only on success.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-https://cloudy.nyc}"
TMP_REL=".build-tmp"
TMP_ABS="$REPO/$TMP_REL"

rm -rf "$TMP_ABS"

docker run --rm \
  -v "$REPO:/project" \
  -w /project \
  personal-site-zola \
  zola build --base-url "$BASE_URL" --output-dir "/project/$TMP_REL" --force

# Swap: move the old aside, promote the new, then discard the old.
if [ -d "$REPO/public" ]; then
  rm -rf "$REPO/public.old"
  mv "$REPO/public" "$REPO/public.old"
fi
mv "$TMP_ABS" "$REPO/public"
rm -rf "$REPO/public.old"

echo "built $REPO/public"
