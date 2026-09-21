#!/usr/bin/env bash
# Build the site into public/ atomically.
#
# zola build wipes its output directory first, so building straight into what
# nginx serves means a failed build leaves a half-empty site -- the exact
# failure that pinned 404s in Cloudflare's cache for meetup.astoria.app.
# Build into a scratch dir, then promote only on success.
#
# The zola container runs as the host user (--user) so build output belongs
# to peter, not root -- otherwise cleanup on the *next* build fails trying to
# remove root-owned files (same pattern http-routing uses for cloudflared).
#
# Promotion is an in-place rsync into public/, not a directory swap: nginx's
# bind mount is pinned to public/'s inode at container start, so replacing
# the whole directory (e.g. via mv) leaves a running container serving the
# old, now-orphaned inode until it's force-recreated. Syncing contents into
# the same stable directory means a running container picks up the change
# immediately, with no outage and no recreate.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-https://cloudy.nyc}"
TMP_REL=".build-tmp"
TMP_ABS="$REPO/$TMP_REL"

rm -rf "$TMP_ABS"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "$REPO:/project" \
  -w /project \
  personal-site-zola \
  zola build --base-url "$BASE_URL" --output-dir "/project/$TMP_REL" --force

# Promote: sync the new build's contents into the stable public/ dir.
mkdir -p "$REPO/public"
rsync -a --delete "$TMP_ABS/" "$REPO/public/"
rm -rf "$TMP_ABS"

echo "built $REPO/public"
