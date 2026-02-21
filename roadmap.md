# Elyan Development Roadmap

## Project Status
- **Current Sprint:** Sensory Feedback & Intelligence
- **Version:** 2.3.0 (Alpha)
- **Focus:** Audio Feedback & UX Polish

## Recent Accomplishments
- [x] **Voice/Audio Feedback:** System sounds for success/error events (macOS integration).
- [x] **Smart Approval Reduction:** Skip manual confirmation for actions explicitly approved before.
- [x] **Predictive UX:** Dashboard displays "preparing..." notifications.
- [x] **Read-After-Write Verification:** File integrity checks.
- [x] **Self-Correction V2:** Auto-retry on write verification failure.
- [x] **Intervention Strategy:** Critical tools trigger dashboard confirmation.

## Next Steps
- [ ] **Context-Aware Hints:** Dashboard "Did you know?" cards based on user habits.
- [ ] **Multi-Modal Input:** Drag & drop images to dashboard to trigger analysis.
- [ ] **Natural Language Voice Control:** Full STT/TTS integration for voice commands.

## Known Issues
- `apscheduler` requires `sqlalchemy` (Fixed).
- Audio feedback currently supports macOS (`afplay`). Linux support pending.
