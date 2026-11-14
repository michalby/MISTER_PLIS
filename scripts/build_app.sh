#!/usr/bin/env bash
# Build "dist/MISTER PLIS.app" — the double-click app for the lab Mac Studio — and a .zip of it.
# Needs Apple's Command Line Tools (xcode-select --install) and an internet connection the first
# time (to download Python). The app has Python inside; on first launch it downloads the code
# from this repository's GitHub remote and installs the packages. See docs/DEPLOY_MAC_STUDIO.md.
#   ./scripts/build_app.sh
#   MISTER_PLIS_REPO_URL=https://github.com/you/fork.git ./scripts/build_app.sh   # other repo
#   MISTER_PLIS_LAB_FILE=labs/ourlab.toml ./scripts/build_app.sh   # set a new Mac up from this lab file on first launch
#                                          # (a path in the repository, or an https:// address; docs/LAB_SETUP_PLAN.md)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd -P)"

# Python bundled in the app (python-build-standalone, relocatable). To update: pick a release at
# https://github.com/astral-sh/python-build-standalone/releases and copy its line from SHA256SUMS.
PY_VERSION=3.12.13
PY_RELEASE=20260623
PY_SHA256=41df7d3ae4757e84b97874f76d634268456aaa271740d33f968d826374998fb7
PY_FILE="cpython-${PY_VERSION}+${PY_RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_RELEASE}/${PY_FILE/+/%2B}"

BUILD="$ROOT/build/macos"
APP="$ROOT/dist/MISTER PLIS.app"
ZIP="$ROOT/dist/MISTER PLIS.zip"

if ! xcrun --find swiftc >/dev/null 2>&1; then
  echo "Needs Apple's Command Line Tools: run  xcode-select --install  and try again."; exit 1
fi

# GitHub's source ZIP has no .git directory. Only read Git metadata when this folder is
# the checkout root, so an unrelated parent repository cannot supply the app's update URL.
REPO_URL="${MISTER_PLIS_REPO_URL:-}"
BUILD_NUMBER=1
if [ "$(git rev-parse --show-toplevel 2>/dev/null || true)" = "$ROOT" ]; then
  if [ -z "$REPO_URL" ]; then
    REPO_URL="$(git remote get-url origin 2>/dev/null || true)"
  fi
  BUILD_NUMBER="$(git rev-list --count HEAD 2>/dev/null || echo 1)"
fi
REPO_URL="${REPO_URL:-https://github.com/michalby/MISTER_PLIS.git}"
REPO_URL="$(printf %s "$REPO_URL" | sed -E 's#://[^/@]+@#://#')"   # never bake a token into the app
VERSION="$(sed -nE 's/^__version__ = "(.*)"/\1/p' mister_plis/__init__.py)"
LAB_FILE="${MISTER_PLIS_LAB_FILE:-}"
case "$LAB_FILE" in *://*@*) echo "MISTER_PLIS_LAB_FILE must not hold a user name or token."; exit 1 ;; esac
xml() { printf %s "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

mkdir -p "$BUILD" "$ROOT/dist"

# 1. Python
if [ ! -f "$BUILD/$PY_FILE" ]; then
  echo "Downloading Python ${PY_VERSION}…"
  curl -fL --progress-bar -o "$BUILD/$PY_FILE.part" "$PY_URL"
  mv "$BUILD/$PY_FILE.part" "$BUILD/$PY_FILE"
fi
if [ "$(shasum -a 256 "$BUILD/$PY_FILE" | cut -d' ' -f1)" != "$PY_SHA256" ]; then
  rm -f "$BUILD/$PY_FILE"
  echo "The Python download doesn't match its checksum — deleted it; run the script again."; exit 1
fi

# 2. Launcher and icon
echo "Compiling the launcher…"
rm -rf "$APP" "$ZIP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -swift-version 5 -target arm64-apple-macos13.0 \
  -framework AppKit -framework ServiceManagement -framework SystemConfiguration \
  macos/launcher/main.swift -o "$APP/Contents/MacOS/MISTER PLIS"

swiftc -O -swift-version 5 macos/make_icon.swift -o "$BUILD/make_icon"
rm -rf "$BUILD/AppIcon.iconset"
"$BUILD/make_icon" mister_plis/static/favicon.svg "$BUILD/AppIcon.iconset"
iconutil -c icns "$BUILD/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"

tar -xzf "$BUILD/$PY_FILE" -C "$APP/Contents/Resources"     # → Resources/python
echo "$PY_VERSION+$PY_RELEASE" > "$APP/Contents/Resources/python-version.txt"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>MISTER PLIS</string>
  <key>CFBundleDisplayName</key><string>MISTER PLIS</string>
  <key>CFBundleIdentifier</key><string>com.misterplis.launcher</string>
  <key>CFBundleExecutable</key><string>MISTER PLIS</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$BUILD_NUMBER</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>Lab toolbox server</string>
  <key>MPRepoURL</key><string>$(xml "$REPO_URL")</string>
  <key>MPLabFile</key><string>$(xml "$LAB_FILE")</string>
</dict>
</plist>
PLIST

# 3. Sign for this Mac only ("ad-hoc"); enough for an app you copy yourself.
codesign --force --sign - "$APP"
ditto -c -k --keepParent "$APP" "$ZIP"

echo
echo "Built: dist/MISTER PLIS.app  ($(du -sh "$APP" | cut -f1); zip $(du -sh "$ZIP" | cut -f1))"
echo "  repository: $REPO_URL"
[ -n "$LAB_FILE" ] && echo "  lab file:   $LAB_FILE (applied when a new Mac first starts the server)"
echo "Copy it into /Applications on the Mac Studio and open it — see docs/DEPLOY_MAC_STUDIO.md."
