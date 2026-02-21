# Elyan Development Roadmap

## Project Status
- **Current Sprint:** Robustness & Proactivity
- **Version:** 2.1.0 (Alpha)
- **Focus:** Autonomy, Safety, and User Trust

## Recent Accomplishments
- [x] **Predictive UX:** Dashboard displays "preparing..." notifications for background drafts.
- [x] **Read-After-Write Verification:** File integrity checks.
- [x] **Self-Correction V2:** Auto-retry on write verification failure.
- [x] **Intervention Strategy:** Critical tools (`delete_file`) trigger dashboard confirmation.
- [x] **Advanced Predictions:** LLM-based next-step prediction when plan is ambiguous.

## Next Steps
- [ ] **Proactive Dashboard:** Show "Suggested Actions" cards based on predictive engine confidence.
- [ ] **Voice/Audio Feedback:** Simple sound cues for success/failure.
- [ ] **Memory Integration:** Store successful interventions in Learning Engine to avoid repeated questions.

## Known Issues
- `apscheduler` requires `sqlalchemy` (Fixed).
- LLM predictions can be slow; ensure they don't block the main thread (Verified: executed in background/async).
