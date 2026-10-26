Verification loop skill (problems 1, 4): the agent must reproduce, test, and prove before saying done.

Task-tracking skill (problem 3): the agent keeps a plan file and checks it off, so it doesn’t drift.



If you can show “without my skill, the agent claimed done but the tests failed; with my skill, it caught and fixed the failure itself,” that’s a strong demo.


Development phases
Phase 1 — LoopGuard
- Detect repeated errors.
- Count attempts.
- Require new evidence before another retry.
- Stop after the configured limit.
Phase 2 — ContextGuard
- Maintain task state and decisions.
- Save progress after significant milestones.
- Resume interrupted tasks using saved state.
Phase 3 — ChangeTracker
- Inspect Git changes.
- Record modified files and change summaries.
- Compare actual changes against the intended scope.
- Generate a report.
Phase 4 — Automatic orchestration
- Connect the components.
- Trigger checks at appropriate points.
- Integrate with OpenCode.
- Test the system on deliberately introduced failures.