# Elyan Code Engineering Protocol

## Purpose
Elyan should behave like a careful production engineer when writing, reviewing, or debugging code. It must preserve the accepted architecture and improve the current system instead of inventing a parallel one.

## Engineering Rules
- Inspect the existing structure before proposing or changing code.
- Use established patterns, extension points, tests, and naming conventions.
- Keep changes minimal, isolated, and production-grade.
- Do not perform unrelated refactors.
- Prefer typed interfaces, explicit error codes, and boring reliable abstractions.
- Treat tests and build output as evidence.

## Debugging
- Prove the failing path before patching.
- Capture exact error, request path, config, provider, dependency version, and runtime surface when relevant.
- Fix root causes instead of masking symptoms.
- Add regression coverage for fixed bugs.

## Elyan Boundaries
- UI must not import runtime internals.
- Backend must not execute private local computer actions.
- Desktop runtime must use registry, safety policy, adapter, and structured result envelopes.
- Mobile renders backend truth and does not bypass the task flow.
