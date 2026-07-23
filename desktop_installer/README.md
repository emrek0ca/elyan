# Elyan Desktop Release Packaging

Elyan installers bundle a uv-managed portable CPython runtime, Elyan sources,
and the hash-locked release dependencies. End users do not need Node.js,
Python, pip, or terminal knowledge.

The release payload intentionally excludes multi-gigabyte model weights and
platform-specific audio build drivers. Those remain optional, capability-level
dependencies and must lazy-load or fail with a safe dependency status; they do
not block startup or the core agent runtime.

## Artifacts

- macOS arm64/x64: signed and notarized `.app.zip` plus `.dmg`
- Windows x64: Authenticode-signed per-user Setup `.exe` plus portable `.zip`
- Linux x64: `.AppImage`, `.deb`, portable `.tar.gz`, and detached GPG signatures
- Every artifact: SHA-256 checksum
- Every release: CycloneDX SBOM and aggregate `SHA256SUMS`

The application launcher copies the immutable payload into the current user's
application-data directory, runs the existing `python -m cli` entry point, and
registers the existing Elyan daemon. The architecture remains:

`installer -> bootstrap -> CLI -> daemon -> capability registry -> safety policy -> adapter`

## Required GitHub Secrets

Production release jobs fail closed when a signing identity is unavailable.

### Apple

- `APPLE_CERTIFICATE`: base64 PKCS#12 Developer ID Application certificate
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_ID`
- `APPLE_TEAM_ID`
- `APPLE_APP_SPECIFIC_PASSWORD`

### Windows

- `WINDOWS_CERTIFICATE`: base64 Authenticode PKCS#12 certificate
- `WINDOWS_CERTIFICATE_PASSWORD`

An EV code-signing certificate provides the best initial SmartScreen trust.
Standard certificates are valid but reputation can take time to accumulate.

### Linux

- `LINUX_GPG_PRIVATE_KEY`: armored private release-signing key
- `LINUX_GPG_PASSPHRASE`

## Release

1. Set every signing secret on `emrek0ca/elyan`.
2. Ensure `package.json` contains the release version.
3. Push an annotated `v<version>` tag.
4. The `Desktop Signed Release` workflow builds on native runners, verifies
   signatures/notarization, scans the Windows package, and publishes only after
   every platform gate succeeds.

Unsigned artifacts are never attached to a GitHub Release. No publisher can
guarantee that every antivirus engine will avoid every future false positive;
the signed/notarized, unobfuscated, hash-locked pipeline is the enforceable
release standard.
