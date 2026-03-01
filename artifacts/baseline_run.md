# Baseline Run Evidence

- Date: 2026-02-26
- Branch: `codex/refactor-agentic-core`
- Baseline Tag: `baseline-pre-agentic`
- Flags:
  - `ELYAN_AGENTIC_V2=0`
  - `ELYAN_STRICT_TASKSPEC=0`
  - `ELYAN_DAG_EXEC=0`

## Smoke Commands
```bash
bash scripts/doctor.sh
bash scripts/smoke.sh
```

## Dashboard
- URL: `http://localhost:18789/dashboard`

## Smoke Result
- `scripts/doctor.sh`: PASS (port 18789 kullanımda uyarısı hariç)
- `scripts/smoke.sh`: PASS

## Golden Task Evidence (Agentic v2)
- Command:
  - `Bu işi planla ve uygula: 1) ~/Desktop/elyan-test/a klasörü oluştur 2) not.md yaz 3) içeriği doğrula 4) bana artifact yollarını ver`
- Runtime flags:
  - `ELYAN_AGENTIC_V2=1`
- Status: `success`
- Run ID: `run_d21d1d5df0f4`
- Manifest:
  - `/Users/emrekoca/.elyan/proofs/run_d21d1d5df0f4/manifest.json`
- Run bundle:
  - `/Users/emrekoca/.elyan/runs/run_d21d1d5df0f4/task.json`
  - `/Users/emrekoca/.elyan/runs/run_d21d1d5df0f4/evidence.json`
  - `/Users/emrekoca/.elyan/runs/run_d21d1d5df0f4/summary.md`
  - `/Users/emrekoca/.elyan/runs/run_d21d1d5df0f4/logs.txt`

## Notes
- Bu dosya baseline smoke çalıştırma kanıtını tutar.
- İlgili run dizinleri: `~/.elyan/runs/<run_id>/`
