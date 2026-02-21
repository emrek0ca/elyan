# Elyan Development Roadmap

## Project Status
- **Current Sprint:** Predictive Engine & UX Refinement
- **Version:** 2.0.0 (Alpha)
- **Focus:** System Autonomy & User Transparency

## Recent Accomplishments
- [x] **Predictive Task Engine:** Core heuristic engine implemented (`core/predictive_tasks.py`).
- [x] **Content Prefetching:** LLM-based draft generation for high-confidence next steps.
- [x] **Agent Integration:** Background trigger in execution loop (`core/agent.py`).
- [x] **Draft Injection:** Auto-inject prefetched content into empty `write_file` calls.
- [x] **Read-After-Write Verification:** Enhanced file operation integrity checks (`core/agent.py`).
- [x] **Predictive UX:** Dashboard now shows "Preparing..." notifications for background drafts (`ui/web/dashboard.html`).

## Current Sprint: Predictive UX & Accuracy (In Progress)
- [ ] **Intervention Strategy:** Implement explicit user confirmation for ambiguous high-impact actions.
- [ ] **Advanced Predictions:** Move beyond heuristics to LLM-based planning prediction.

## Upcoming
1. **Self-Correction V2:** If `read-after-write` fails, auto-retry the write operation once.
2. **Proactive Dashboard:** Show "Suggested Actions" cards based on predictive engine confidence.
3. **Voice/Audio Feedback:** Simple sound cues for success/failure (optional).

## Known Issues
- `apscheduler` requires `sqlalchemy` (Fixed in `requirements.txt`).
- Predictive drafts are currently text-only (need support for structured data/JSON).
