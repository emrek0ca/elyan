# Elyan Dev Quickstart

## 1) Ortam
```bash
cd /Users/emrekoca/Desktop/bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Doctor
```bash
bash scripts/doctor.sh
```

## 3) Smoke
```bash
bash scripts/smoke.sh
```

## 3.1) Stabilite Baseline (Hafta 1)
```bash
python scripts/stability_baseline.py --profile quick
```

Çıktılar:
- `artifacts/stability/<run_id>/report.md`
- `artifacts/stability/<run_id>/report.json`
- `artifacts/stability/<run_id>/daily_quality_note.md`

## 4) Dashboard
```bash
source .venv/bin/activate
python main.py
```

Dashboard: `http://localhost:18789/dashboard`

## 5) Agentic v2 Flags (No-regression rollout)
Varsayılanlar kapalıdır.
```bash
export ELYAN_AGENTIC_V2=1
export ELYAN_STRICT_TASKSPEC=1
export ELYAN_DAG_EXEC=0
```

## 6) Run Artifacts
Her çalıştırma için:
- `~/.elyan/proofs/<run_id>/manifest.json`
- `~/.elyan/runs/<run_id>/task.json`
- `~/.elyan/runs/<run_id>/evidence.json`
- `~/.elyan/runs/<run_id>/summary.md`
- `~/.elyan/runs/<run_id>/logs.txt`
