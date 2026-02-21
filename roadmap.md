# Elyan Development Roadmap

## Project Status
- **Current Sprint:** Intelligence & UX
- **Version:** 2.2.0 (Alpha)
- **Focus:** Reducing User Friction (Smart Approvals)

## Recent Accomplishments
- [x] **Smart Approval Reduction:** Skip manual confirmation for actions explicitly approved before (exact param match).
- [x] **Predictive UX:** Dashboard displays "preparing..." notifications for background drafts.
- [x] **Read-After-Write Verification:** File integrity checks.
- [x] **Self-Correction V2:** Auto-retry on write verification failure.
- [x] **Intervention Strategy:** Critical tools (`delete_file`) trigger dashboard confirmation.
- [x] **Advanced Predictions:** LLM-based next-step prediction when plan is ambiguous.

## Next Steps
- [ ] **Voice/Audio Feedback:** Simple sound cues for success/failure.
- [ ] **Context-Aware Hints:** Dashboard "Did you know?" cards based on user habits.
- [ ] **Multi-Modal Input:** Drag & drop images to dashboard to trigger analysis.

## Known Issues
- `apscheduler` requires `sqlalchemy` (Fixed).
- `elyan` console script required non-editable install fix (Fixed via `cli.main` entry point and standard install).
