# Elyan Runtime Bundle

`npm run build:runtime` packages `/Users/emrekoca/Desktop/elyan/runtime/bridge.py` as the optional `elyan-runtime` binary with PyInstaller.

The Electron shell must still open when this bundle is absent. In that case Electron main reports degraded runtime availability and keeps the UI responsive.
