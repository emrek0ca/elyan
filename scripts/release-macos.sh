#!/usr/bin/env bash
# ElyanMac yayın hattı: archive → Developer ID export → notarize → staple.
#
# Ön koşullar (bir kere):
#   1. Xcode → Settings → Accounts → Manage Certificates →
#      "Developer ID Application" sertifikası oluştur (takım: 7SRKKF75MC).
#   2. Notarization kimliği kaydet (App Store Connect app-specific password
#      veya API key ile):
#        xcrun notarytool store-credentials elyan-notary \
#          --apple-id <apple-id> --team-id 7SRKKF75MC --password <app-specific>
#
# Kullanım:
#   NOTARY_PROFILE=elyan-notary ./scripts/release-macos.sh
#
# Çıktı: dist/Elyan.app (imzalı + notarize + stapled) ve dist/Elyan-macos.zip

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="$ROOT/apps/macos/ElyanMac/ElyanMac.xcodeproj"
SCHEME="ElyanMac"
TEAM_ID="${TEAM_ID:-7SRKKF75MC}"
NOTARY_PROFILE="${NOTARY_PROFILE:-elyan-notary}"
DIST="$ROOT/dist"
ARCHIVE="$DIST/ElyanMac.xcarchive"
EXPORT_DIR="$DIST/export"

mkdir -p "$DIST"
rm -rf "$ARCHIVE" "$EXPORT_DIR"

echo "── 1/5 Developer ID sertifika kontrolü"
if ! security find-identity -v -p codesigning | grep -q "Developer ID Application"; then
  echo "HATA: 'Developer ID Application' sertifikası bulunamadı."
  echo "Xcode → Settings → Accounts → Manage Certificates'ten oluşturun."
  exit 1
fi

echo "── 2/5 Archive"
xcodebuild -project "$PROJECT" -scheme "$SCHEME" -configuration Release \
  -archivePath "$ARCHIVE" -allowProvisioningUpdates archive | tail -3

echo "── 3/5 Developer ID export"
EXPORT_PLIST="$DIST/exportOptions.plist"
cat > "$EXPORT_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>developer-id</string>
  <key>teamID</key><string>${TEAM_ID}</string>
  <key>signingStyle</key><string>automatic</string>
</dict>
</plist>
PLIST
xcodebuild -exportArchive -archivePath "$ARCHIVE" \
  -exportOptionsPlist "$EXPORT_PLIST" -exportPath "$EXPORT_DIR" \
  -allowProvisioningUpdates | tail -3

APP="$EXPORT_DIR/Elyan.app"
ZIP="$DIST/Elyan-macos.zip"
rm -f "$ZIP"

echo "── 4/5 Notarization (profil: $NOTARY_PROFILE)"
ditto -c -k --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" --keychain-profile "$NOTARY_PROFILE" --wait

echo "── 5/5 Staple + doğrulama"
xcrun stapler staple "$APP"
spctl -a -vv --type execute "$APP"
codesign --verify --deep --strict "$APP"

rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
echo "TAMAM: $APP ve $ZIP yayına hazır."
