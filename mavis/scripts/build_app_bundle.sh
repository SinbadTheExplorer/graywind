#!/bin/bash
# Builds ~/Applications/Johnny.app -- a bundle that exists ONLY to give the
# avatar a stable TCC identity.
#
# The problem it solves: macOS remembers a microphone grant against the
# requesting binary's code-signing identity. The avatar runs on Homebrew
# python3.14, which is ad-hoc signed with NO team identifier, at a
# version-pinned Cellar path (.../python@3.14/3.14.6/...). So the identity is
# a bare hash of that exact binary, with nothing stable to hold onto -- macOS
# re-asks, and the entry reads "Python" rather than anything meaningful.
#
# A bundle identifier does not move when Homebrew upgrades Python.
#
# Build:      mavis/scripts/build_app_bundle.sh
# Remove:     mavis/scripts/build_app_bundle.sh --uninstall
set -euo pipefail

APP="$HOME/Applications/Johnny.app"

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$APP"
    echo "Removed $APP (the microphone grant it held is now orphaned; macOS"
    echo "will drop it, or you can remove 'Johnny' in Privacy & Security)."
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAVIS_DIR="$(dirname "$SCRIPT_DIR")"
AVATAR_SH="$MAVIS_DIR/scripts/mavis-avatar.sh"

[ -f "$AVATAR_SH" ] || { echo "no $AVATAR_SH" >&2; exit 1; }
chmod +x "$AVATAR_SH"

mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Johnny</string>
    <key>CFBundleDisplayName</key>
    <string>Johnny</string>
    <key>CFBundleExecutable</key>
    <string>Johnny</string>
    <key>CFBundleIdentifier</key>
    <string>com.mavis.johnny</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>Johnny listens for the wake phrase and for your spoken questions.</string>
    <key>NSCameraUsageDescription</key>
    <string>In portal mode Johnny watches where your eyes are, so the room behind the screen moves the way a real window would. Frames never leave this Mac.</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
</dict>
</plist>
PLIST

# The avatar path is baked in at BUILD time so the bundle has no dependency
# on the caller's cwd or environment -- launchd gives it neither.
cat > "$APP/Contents/MacOS/Johnny" <<EOF
#!/bin/bash
# Deliberately NOT exec. exec would replace this bundle's process image with
# the Python interpreter, and TCC would go back to attributing the microphone
# to python3.14 -- the exact thing this bundle exists to stop. Running the
# avatar as a CHILD keeps the bundle as the responsible process, so the grant
# attaches to com.mavis.johnny and survives a Homebrew Python upgrade.
set -euo pipefail
"$AVATAR_SH" "\$@"
EOF
chmod +x "$APP/Contents/MacOS/Johnny"

# --identifier is the point of this line, not the signature. An ad-hoc
# signature with no identifier derives one from the binary, so it would change
# whenever this script's contents change and the grant would be lost again.
# --deep is deliberately absent: Apple deprecated it for signing, and there is
# nothing nested here to sign.
codesign --force --sign - --identifier com.mavis.johnny "$APP"

echo "Built $APP"
codesign -dv "$APP" 2>&1 | grep -E "^Identifier|^Signature" | sed 's/^/  /'
echo "macOS will ask for the microphone the first time he runs, as 'Johnny'."
echo "With MAVIS_PORTAL=1 in ~/.mavis/env it will also ask for the camera."
