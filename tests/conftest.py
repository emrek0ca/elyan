"""Test oturumu güvenlik ağı: GERÇEK kullanıcı state dosyasını koru.

Testler kendi içinde `_isolate_state` (monkeypatch) kullanır; ama RuntimeBridge
testlerde arka plan thread'leri başlatabilir ve bu thread'ler test bittikten
(monkeypatch geri alındıktan) SONRA da yaşayıp state yazabilir. Bu, gerçek
`~/Library/Application Support/Elyan/state/elyan_state.json` dosyasına test
kimliği (deviceId=1111...) sızdırdı ve canlıda runtime_register 404 fırtınası
(device_not_found) yarattı. Buradaki oturum-kapsamlı yönlendirme, sızıntı olsa
bile yazımın sandbox'a gitmesini garanti eder.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime import state_store


@pytest.fixture(scope="session", autouse=True)
def _sandbox_real_state_for_whole_session():
    sandbox = Path(tempfile.mkdtemp(prefix="elyan-test-state-"))
    state_store.CONFIG_DIR = sandbox
    state_store.STATE_PATH = sandbox / "elyan_state.json"
    state_store.LEGACY_STATE_PATH = sandbox / "legacy.json"
    yield
    # Bilinçli olarak geri YÜKLEMİYORUZ: pytest süreci kapanana kadar yaşayan
    # sızıntı thread'leri de sandbox'a yazsın. Süreç sonunda her şey gider.
