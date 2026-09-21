#!/usr/bin/env bash
# Build the site and make the new version visible to the public.
#
# cloudy.nyc is served from this Pi: Caddy (http-routing) reverse-proxies the
# `web` nginx container on :8802, which serves this repo's `public/` directory
# through a bind mount. So building IS deploying -- `scripts/build-site.sh`
# promotes the new files into `public/` and the origin is immediately current.
#
# What is NOT immediate is what the public sees. Cloudflare holds pages at the
# edge for 30 days (a Cache Rule in the zone's http_request_cache_settings
# phase), which is what keeps real traffic off this machine and keeps the site
# readable while it is off. Pages live at stable URLs, so unlike the
# content-hashed images that cache cannot invalidate itself -- the purge below
# is the step that actually publishes.
#
# Ordering matters. The build must fully succeed before the cache is dropped,
# so a broken build can never become the thing everyone fetches.
# scripts/build-site.sh builds into a scratch dir and refuses to promote an
# empty result, so this script simply runs it first and stops on failure.
#
# (Until 2026-09-21 this also synced `public/` to an S3 website bucket, which
# was then the origin. The Pi is the origin again; that bucket is no longer
# written to and is stale. See http-routing/CLAUDE.md for the cutover.)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

"$REPO/scripts/build-site.sh"

# The origin only exists while the nginx container is up. This used to be
# cosmetic -- S3 served the site and the container was just a local preview --
# so a stopped container was invisible. It is now the whole site.
if ! docker compose ps --status running --services 2>/dev/null | grep -qx web; then
  echo "warning: the 'web' container is not running -- cloudy.nyc is DOWN." >&2
  echo "         start it with 'docker compose up -d web' in $REPO" >&2
fi

if [ ! -f "$REPO/../http-routing/.env" ]; then
  echo "missing ../http-routing/.env -- cannot purge Cloudflare." >&2
  echo "The build is live at the origin, but the edge will serve the old" >&2
  echo "pages for up to 30 days. Purge by hand before calling this done." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$REPO/../http-routing/.env"
: "${CLOUDFLARE_API_TOKEN:?}"

ZONE=$(curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=cloudy.nyc" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['result'][0]['id'])")

curl -s -X POST \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE/purge_cache" \
  --data '{"purge_everything":true}' \
  | python3 -c "
import json,sys
d = json.load(sys.stdin)
if not d.get('success'):
    print('PURGE FAILED: %s' % d.get('errors'), file=sys.stderr)
    sys.exit(1)
print('purged cloudflare')
"

echo "published (https://cloudy.nyc/)"
