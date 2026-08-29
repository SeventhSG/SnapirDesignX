#!/bin/bash
# Publish a release: create it from docs/RELEASE-<version>.md and upload both
# the Windows installer and the Android APK.
#
#   bash tools/publish_release.sh 1.1.1
#
# The token comes from the credential helper git already uses for this remote,
# so nothing new is stored anywhere.
set -euo pipefail

VERSION=${1:?usage: publish_release.sh <version>}
REPO=SeventhSG/SnapirDesignX
ROOT="C:/Users/gamin/Downloads/Snapir-Design-X"
SETUP="$ROOT/app/release/SnapirDesignX-${VERSION}-setup.exe"
APK="$ROOT/android/app/build/outputs/apk/release/app-release.apk"
APK_NAME="SnapirDesignX-${VERSION}.apk"

for f in "$SETUP" "$APK"; do
  [ -f "$f" ] || { echo "missing artifact: $f" >&2; exit 1; }
done

TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git -C "$ROOT" credential fill | grep '^password=' | cut -d= -f2-)
API=https://api.github.com/repos/$REPO
UP=https://uploads.github.com/repos/$REPO

# Drop an existing v${VERSION} so re-running this is safe.
OLD=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/releases/tags/v${VERSION}" \
      | python -c "import json,sys;d=json.load(sys.stdin);print(d.get('id',''))" 2>/dev/null || true)
if [ -n "$OLD" ]; then
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $TOKEN" "$API/releases/$OLD"
  echo "removed previous release $OLD"
fi

python - "$ROOT" "$VERSION" > /tmp/rel.json <<'PY'
import json, sys, pathlib
body = pathlib.Path(sys.argv[1], "docs", "RELEASE-" + sys.argv[2] + ".md").read_text(encoding="utf-8")
body = body.split("\n", 2)[2].strip()  # drop the title line, the release has one
print(json.dumps({"tag_name": "v" + sys.argv[2], "name": "Snapir Design X v" + sys.argv[2],
                  "body": body, "draft": False, "prerelease": False}))
PY

ID=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
     -d @/tmp/rel.json "$API/releases" \
     | python -c "import json,sys;d=json.load(sys.stdin);print(d.get('id') or d)")
echo "release id: $ID"

for pair in "$SETUP|SnapirDesignX-${VERSION}-setup.exe" "$APK|$APK_NAME"; do
  path=${pair%%|*}; name=${pair##*|}
  echo "uploading $name ($(du -h "$path" | cut -f1))..."
  curl -s --max-time 3600 -X POST -H "Authorization: Bearer $TOKEN" \
       -H "Content-Type: application/octet-stream" --data-binary @"$path" \
       "$UP/releases/$ID/assets?name=$name" \
    | python -c "import json,sys;d=json.load(sys.stdin);print(' ',d.get('name'),d.get('size'),d.get('state'))"
done

echo "https://github.com/$REPO/releases/tag/v${VERSION}"
