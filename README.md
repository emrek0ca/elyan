# Elyan Desktop

Elyan desktop ships from `electron/`. The desktop stack is Electron for shell/UI,
Python for runtime execution, C++ for thin OS integration, and Rust for native
compute sidecars where needed.

## Active Desktop Run

```bash
cd electron
npm install
npm run dev
```

From the repository root, the default desktop helper targets Electron:

```bash
script/build_and_run.sh
```

## Verify

```bash
cd electron
npm run typecheck
npm run test
npm run build
npm run test:smoke
```

Runtime contract smoke:

```bash
python -m pytest tests/test_runtime_startup_contract.py tests/test_runtime_bridge_contract.py -q
```

## Mobile

Mobile remains Flutter-only in `/Users/emrekoca/Desktop/mobile-elyan` and targets
iOS + Android. Desktop work in this repo should not add new Flutter shell code.
