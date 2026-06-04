# Elyan Electron Desktop

This is the active Elyan desktop shell. It preserves the existing Python runtime,
backend control-plane, mobile flow, Rust sidecar, and optional C++ window shim
boundaries.

## Development

```bash
npm install
npm run dev
```

The renderer never calls backend APIs directly. Core Elyan flows go through:

```text
renderer -> preload -> Electron main -> runtime/bridge.py -> capability registry -> safety policy -> adapter
```

## Verification

```bash
npm run typecheck
npm run test
npm run build
npm run test:smoke
```

## Packaging

Unsigned macOS directory smoke:

```bash
CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --config electron-builder.yml --mac dir
```

Normal packaging:

```bash
npm run package
```

## Runtime Bundle

`npm run build:runtime` attempts to bundle `../runtime/bridge.py` with
PyInstaller into `build/runtime/<platform>/`. If PyInstaller is unavailable,
the Electron app still opens and reports degraded runtime availability.

Set `ELYAN_RUNTIME_BUNDLE_REQUIRED=1` in CI when a missing PyInstaller bundle
should fail the build.

## Native Addon

`npm run build:native` builds the optional C++ Node-API window shim. If the
addon is unavailable, Electron main falls back to safe platform capabilities.

Set `ELYAN_NATIVE_REQUIRED=1` in CI when native addon build failure should fail
the build.

## Signing Notes

Local macOS smoke can use ad-hoc signing with `CSC_IDENTITY_AUTO_DISCOVERY=false`.
Release signing/notarization must use a single unambiguous Apple identity.
