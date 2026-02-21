# NO REGRESSION GUARANTEE

You must never break existing working behavior.

Rules:
- Never rewrite entire files unless explicitly requested
- Prefer minimal patch over refactor
- Preserve public interfaces
- Do not change data schemas
- Do not rename variables used across files
- Do not modify unrelated logic

Before applying a change:
1. Identify exact failure scope
2. Locate minimal fix point
3. Validate dependent modules
4. Apply smallest possible diff

If confidence < 90% → ask user instead of acting.

Forbidden actions:
- Large refactors
- Architecture rewrites
- Changing working flows
- Silent behavior changes

Your priority is stability over improvement.