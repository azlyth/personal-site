#!/usr/bin/env bash
# Run scripts/verify-fit.py against a SERVED site.
#
# With no argument it serves the working tree -- which is what you want before
# publishing, since checking the live site only tells you about the last thing
# you shipped. Pass a URL to check something already running:
#
#   scripts/check-fit.sh                        # the working tree
#   scripts/check-fit.sh https://cloudy.nyc     # what readers actually get
#
# Container handling follows the rule in CLAUDE.md: the ONLY safe dev teardown
# is `docker rm -f personal-site-zola-1`. Never `make stop`, never
# `docker compose down` on either file -- both take prod down with them. This
# script also leaves an already-running dev server alone, so running it while
# you are working does not pull the server out from under you.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ $# -gt 0 ]; then
    exec python3 scripts/verify-fit.py "$1"
fi

started=""
if [ -z "$(docker ps -q -f name=personal-site-zola-1)" ]; then
    echo "starting dev server to check the working tree..."
    docker compose -f compose.dev.yaml up -d zola >/dev/null
    started=1
    # Zola builds the whole site before it answers; poll rather than guess.
    for _ in $(seq 1 40); do
        if curl -fsS -o /dev/null http://127.0.0.1:1111/ 2>/dev/null; then break; fi
        sleep 1
    done
fi

rc=0
python3 scripts/verify-fit.py http://127.0.0.1:1111 || rc=$?

if [ -n "$started" ]; then
    docker rm -f personal-site-zola-1 >/dev/null
fi

exit $rc
