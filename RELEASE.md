# ElyanMac Yayın Prosedürü

Kod tarafı yayına hazır ve doğrulanmış durumda:

- İmzalı Release build ✅ (provisioning profile + Sign in with Apple
  entitlement gömülü, imza zinciri Apple Root CA'ya doğrulanmış,
  `codesign --verify --deep --strict` geçiyor)
- Google OAuth client'ları ✅ (token-ucu doğrulaması: mac client
  `invalid_grant` = kayıtlı, server client `invalid_request:
  client_secret missing` = kayıtlı web client)
- Python runtime 349/349 sözleşme testi ✅
- `get-task-allow` entitlements'tan çıkarıldı (Debug'da Xcode otomatik
  enjekte eder; release'te bulunması notarization engelidir)

## Tek seferlik kurulum (Apple ID sahibi yapmalı)

Bu iki adım Apple ID parolası / cihaz 2FA / app-specific password
gerektirir; otomatikleştirilemez:

1. **Developer ID Application sertifikası**
   Xcode → Settings → Accounts (7SRKKF75MC takımı) →
   Manage Certificates → **+** → *Developer ID Application*

2. **Notarization kimliği** (app-specific password'ü
   [appleid.apple.com](https://appleid.apple.com) → Sign-In & Security →
   App-Specific Passwords'ten üret):

   ```bash
   xcrun notarytool store-credentials elyan-notary \
     --apple-id osmanemrekoca@gmail.com \
     --team-id 7SRKKF75MC \
     --password <app-specific-password>
   ```

## Her yayında

```bash
NOTARY_PROFILE=elyan-notary ./scripts/release-macos.sh
```

Script sırasıyla: Developer ID sertifika kontrolü → Release archive →
Developer ID export → notarization (`--wait`) → staple →
`spctl`/`codesign` doğrulaması. Çıktı: dağıtıma hazır `dist/Elyan.app`
ve `dist/Elyan-macos.zip`.

## Dağıtım notları

- `app-sandbox=false` bilinçlidir (Python runtime süreci + izin-kapılı
  bilgisayar kontrolü): kanal **App Store değil**, notarize edilmiş
  doğrudan dağıtımdır (web sitesi / Sparkle vb.).
- Sürüm numarası: `CFBundleShortVersionString` (Info.plist) her yayında
  artırılmalı.
- Yayın öncesi hızlı doğrulama:
  ```bash
  venv/bin/python -m pytest tests/ -q
  xcodebuild -project apps/macos/ElyanMac/ElyanMac.xcodeproj \
    -scheme ElyanMac -configuration Release \
    -derivedDataPath apps/macos/ElyanMac/build-release \
    -allowProvisioningUpdates build
  ```
