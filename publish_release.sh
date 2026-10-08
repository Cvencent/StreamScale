#!/bin/sh
# Retry publishing the release asset once the network comes back.
#
# The code itself is already on GitHub (commit 3d72079). Only the 18.7 MB
# executable still needs uploading, and the earlier attempt failed with
# "Bad Gateway" while the proxy was returning 000 to everything.
#
# Run this from the repository root:
#     sh publish_release.sh

set -u

REPO="Cvencent/StreamScale"
TAG="v0.2.0"
ASSET="StreamScale.exe"

echo "Checking GitHub reachability..."
reachable=0
i=1
while [ "$i" -le 12 ]; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 12 \
           -x "${https_proxy:-http://127.0.0.1:57892}" \
           https://api.github.com 2>/dev/null)
    if [ "$code" = "200" ]; then
        echo "  reachable (attempt $i)"
        reachable=1
        break
    fi
    echo "  attempt $i: HTTP $code"
    sleep 10
    i=$((i + 1))
done

if [ "$reachable" != "1" ]; then
    echo "GitHub is still unreachable. Try again later."
    exit 1
fi

if [ ! -f "$ASSET" ]; then
    echo "$ASSET not found. Build it first:  python runtime/build.py"
    exit 1
fi

echo
echo "Publishing $TAG..."
if gh release view "$TAG" >/dev/null 2>&1; then
    echo "  release exists, uploading asset"
    gh release upload "$TAG" "$ASSET" --clobber
else
    gh release create "$TAG" \
        --title "StreamScale 0.2.0 - tray app" \
        --notes "Adds a tray companion: status icon, settings window, and one-click install of the Sunshine press commands. The tray is optional - the scaling hooks keep working when it is closed. Windows 10/11, no Python needed." \
        "$ASSET"
fi

echo
echo "Verifying..."
gh release view "$TAG" --json assets \
    --jq '.assets[] | "  \(.name)  \(.size) bytes"'

echo
echo "Done: https://github.com/$REPO/releases/tag/$TAG"
