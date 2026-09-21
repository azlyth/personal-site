#!/usr/bin/env bash
# Build the site and publish it to where the public actually reads it: S3.
#
# cloudy.nyc is served by Cloudflare straight from the S3 website endpoint, so
# the Pi is not in the request path at all -- the site stays up when this
# machine is off. That also means building alone publishes nothing; the sync
# below is what makes a change visible.
#
# Ordering matters. The build must fully succeed before anything is uploaded,
# so a broken build can never replace a working site. scripts/build-site.sh
# already guarantees that locally (it builds into a scratch dir and refuses to
# promote an empty result), so this script simply runs it first and stops on
# failure.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

if [ ! -f .aws.env ]; then
  echo "missing .aws.env -- run 'make sync-personal-site' in personal-cloud-infra" >&2
  exit 1
fi

# shellcheck disable=SC1091
source .aws.env
: "${PERSONAL_SITE_PAGES_BUCKET:?}" "${PERSONAL_SITE_PAGES_ACCESS_KEY_ID:?}" "${PERSONAL_SITE_PAGES_SECRET_ACCESS_KEY:?}"

"$REPO/scripts/build-site.sh"

export AWS_ACCESS_KEY_ID="$PERSONAL_SITE_PAGES_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$PERSONAL_SITE_PAGES_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
BUCKET="$PERSONAL_SITE_PAGES_BUCKET"

# Two passes, because a single sync can't set different cache headers per file
# type. Pass 1 carries --delete so files a rebuild dropped (a deleted post)
# stop being served. Pass 2 must NOT carry --delete: combined with --exclude it
# would delete everything pass 1 just uploaded.
aws s3 sync public/ "s3://$BUCKET/" --delete --no-progress \
  --cache-control "public, max-age=86400, stale-if-error=604800"

# HTML gets a short TTL: pages live at stable URLs and their content changes,
# unlike the content-hashed images. stale-if-error keeps the site readable if
# the origin ever misbehaves.
aws s3 cp public/ "s3://$BUCKET/" --recursive --no-progress \
  --exclude "*" --include "*.html" \
  --content-type "text/html; charset=utf-8" \
  --cache-control "public, max-age=300, stale-if-error=86400"

# Purge Cloudflare, or the edge keeps serving the old page for up to the TTL.
# Unlike images (content-hashed, immutable), a post's URL doesn't change when
# its content does, so the cache cannot invalidate itself.
if [ -f "$REPO/../http-routing/.env" ]; then
  # shellcheck disable=SC1091
  source "$REPO/../http-routing/.env"
  ZONE=$(curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    "https://api.cloudflare.com/client/v4/zones?name=cloudy.nyc" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['result'][0]['id'])")
  curl -s -X POST \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    -H "Content-Type: application/json" \
    "https://api.cloudflare.com/client/v4/zones/$ZONE/purge_cache" \
    --data '{"purge_everything":true}' \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('purged cloudflare' if d.get('success') else 'PURGE FAILED: %s' % d.get('errors'))"
else
  echo "warning: no ../http-routing/.env, skipping Cloudflare purge" >&2
fi

echo "published to s3://$BUCKET/ (https://cloudy.nyc/)"
