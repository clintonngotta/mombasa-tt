# @coast-tt/scoring

The scoring rules of table tennis as a pure TypeScript reducer (REQ-012): score events in, one canonical match state
out. It has no dependencies and touches no clock, storage or network, so the scoring deck can run it offline and a
native client can reuse it later (REQ-001). The API validates accepted streams with an independent Python
implementation, `services/api/scoring/engine.py`.

- `src/index.ts`: `Scoring` (push events, undo), `apply`, `replay`, the `State` and `ScoreEvent` types.
- `fixtures/f-sc*.json`: hand-worked fixtures F-SC1 to F-SC10, listed in test.md. Each step is a run of points or one
  event, with the fields the state must then have, or the code the event must be refused with.
- `fixtures/parity.json`: seeded random streams with a digest of the state after every accepted event, made by
  `scripts/make-parity.ts`. It shows that the two implementations agree; the hand-worked fixtures show they are right.

Both implementations run the same files:

```
cd apps/web
pnpm test:scoring        # TypeScript reducer
pnpm typecheck:scoring
pnpm gen:parity          # after changing the reducer; commit the result
cd ../../services/api
uv run pytest tests/test_scoring.py   # Python validator
```

A rule change means: the clause in spec.md, a hand-worked fixture, both implementations, then `pnpm gen:parity`.
