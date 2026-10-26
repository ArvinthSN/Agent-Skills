---
name: loop-guard
description: Prevents unproductive retry loops during coding tasks. Use when a command, test, build, lint, deploy, API call, or debugging attempt has failed and may be retried, when the same or a similar error appears twice, or when the user says "still failing", "same error", or "stuck". Tracks attempts, forces evidence-based changes of approach, and stops with an escalation report after the attempt limit.
---

# Loop Guard

Stop repeating failed approaches. Every retry must be justified by new evidence.

## When to use

- A command, test, build, or API call failed and you are about to try again.
- The same or a very similar error appears a second time.
- You are about to make a fix that resembles one you already tried.

Do not count successful or unrelated operations as failures. Do not use this skill for a first-time failure that you have not yet investigated; investigate it first, then start recording.

## Definitions

- **Failure signature:** the root error with noise removed (file paths, line numbers, timestamps, memory addresses, ids). Use the first causal error, not the cascade that follows it.
- **Attempt:** one run of a command after a specific change or hypothesis.
- **Approach:** the combination of hypothesis, files touched, and the kind of change made.
- **Same approach:** differs only cosmetically (timeouts, sleeps, retries, renaming, reformatting, reordering), or changes the same lines for the same reason.
- **Different approach:** tests a different hypothesis about the cause, works in a different layer (code, config, dependency, environment, data), or gathers new evidence first (minimal reproduction, added logging, bisecting).

## Limits

- Default: **3 failed attempts per failure signature**, plus a **cap of 6 failed attempts per task** across all signatures.
- If the user or project configuration sets a different limit, use that.
- A new signature starts its own count. A different error than before often means progress, so say so.
- Rerunning an unchanged flaky test once to confirm flakiness does not count. Label the result "flaky" and say so in the report.

## Procedure

1. **Frame.** In one line each, state the expected result, the command, and the hypothesis about the cause.
2. **Run once.** Run the command and read the actual output. Quote the real error; never reconstruct it from memory.
3. **Classify the outcome:**
   - `passed`: the goal is met. Record it if earlier failures exist, then stop using this guard.
   - `progress`: a different error than before, closer to the goal.
   - `same-failure`: same signature as an earlier attempt.
   - `new-failure`: unrelated to previous attempts.
   - `blocked`: needs credentials, permissions, a service you cannot reach, or a user decision.
4. **Record** the attempt (redact secrets first; see Safety):
   `python .github/skills/loop-guard/scripts/record_attempt.py --task-id "<short-id>" --command "<command>" --error "<error summary>" --hypothesis "<hypothesis>" --approach "<approach>" --outcome <failed|progress|passed|blocked>`
5. **Obey the verdict** (see below).
6. **Change approach properly.** Cite the evidence that rules out the old hypothesis, change one meaningful variable at a time, and state what result would confirm or reject the new hypothesis.
7. **Stop and report** when the verdict says so (see Escalation report).

## Verdicts

The script prints one verdict and sets the exit code:

| Verdict | Exit code | Meaning | What to do |
|---|---|---|---|
| `continue` | 0 | Within budget, new or progressing failure | Proceed with the next evidence-backed attempt |
| `change-approach` | 10 | Same signature repeated, or one attempt left | Do not repeat; use a different approach as defined above |
| `stop-and-escalate` | 20 | Limit reached, or blocked | Stop; write the escalation report |
| (error) | 2 | Script or ledger problem | Use manual mode (see Fallback) |

## Not valid ways to escape a loop

Never do these unless the user explicitly approves:

- Delete, skip, or weaken the failing test or assertion.
- Disable lint, type, or security checks.
- Swallow exceptions or hardcode the expected value.
- Use `--force` or `--no-verify`, or lower coverage thresholds.
- Mock out the component that is actually failing.

Treat any of these as a stop condition, not a fix.

## Safety

- Never automatically repeat destructive commands (`rm -rf`, `git reset --hard`, `git clean`, dropping data, force pushes, down-migrations). Ask first. Removing regenerable build artifacts may be done once, and must be stated.
- Redact tokens, passwords, API keys, and connection strings from `--command` and `--error` before recording.
- Never fabricate output, errors, or test results.
- Never hide an unresolved failure or describe it as fixed.

## Escalation report

When stopping, report:

1. **Task and expected result**
2. **Attempts:** a numbered list with command, hypothesis, approach, and real outcome
3. **Most likely root cause** and the evidence for it
4. **Remaining uncertainty:** what you could not confirm
5. **What you did not try** and why
6. **Next action:** the specific thing the user, or you with approval, should do
7. **User intervention needed?** yes/no, and what exactly (credentials, access, a decision)

## Examples

**Failing Python test.** `pytest tests/test_user.py` fails with `KeyError: 'email'` three times. Attempt 1 adds the key in the serializer; attempt 2 adds it with a default; both fail identically. Verdict `change-approach`. New evidence: print the fixture payload, which shows the fixture lacks the field. Fix the fixture, not the serializer.

**API error.** `POST /orders` returns `401` after rotating headers twice. Same signature, same layer. Stop guessing at headers. Check whether the token is expired (a `blocked` outcome needing user credentials), and escalate if so.

**Frontend build failure.** `npm run build` fails with `Module not found: 'lodash'`. Reinstalling dependencies twice does not change the result. Change approach: check whether `lodash` is declared in `package.json` and whether the lockfile matches. If a lockfile reset is needed, ask first.

## Fallback

If the script is missing or exits with code 2, follow this procedure manually, keep a numbered attempt list in your reply, and say explicitly that the ledger file was not updated.