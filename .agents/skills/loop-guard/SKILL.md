---
name: loop-guard
description: Prevents unproductive retry loops while coding. Use whenever a command, test, build, lint, deploy, migration, or API call fails and you are about to retry, when the same or a similar error appears twice, when you are tempted to "just try again" or make a small variation of a fix that already failed, or when the user says "still failing", "same error", "stuck", or "going in circles". Records each attempt in a ledger, returns a verdict (continue, change-approach, stop-and-escalate), forces an evidence-based change of approach, and stops with an escalation report when the limit is reached. Use it even if the user does not mention loops.
---

# Loop Guard

Stop repeating failed approaches. Every retry must be justified by new evidence.

## When to use

- A command, test, build, or API call failed and you are about to try again.
- The same or a very similar error appears a second time.
- You are about to make a fix that resembles one you already tried.

Investigate a first-time failure before recording it. Successful or unrelated operations never count as failures.

## Definitions

- **Failure signature:** the root error with noise removed (paths, line numbers, timestamps, ids). Use the first causal error, not the cascade after it. The script computes this for you.
- **Same approach:** differs only cosmetically (sleeps, retries, renames, reformatting) or changes the same lines for the same reason.
- **Different approach:** tests a different hypothesis, works in a different layer (code, config, dependency, environment, data), or gathers new evidence first (minimal reproduction, added logging, bisecting).

## Procedure

1. **Frame.** State the expected result, the command, and your hypothesis about the cause, one line each.
2. **Run once.** Read the real output. Quote the real error; never reconstruct it from memory.
3. **Classify the outcome:**
   - `failed`: the command failed.
   - `progress`: still failing, but with a different error that is closer to the goal.
   - `passed`: the goal is met.
   - `blocked`: needs credentials, permissions, an unreachable service, or a user decision.
4. **Record it** (secrets are redacted before storage, but do not paste them in on purpose):

   ```
   python .github/skills/loop-guard/scripts/record_attempt.py \
     --task-id "<short-id>" --command "<command>" --error "<error summary>" \
     --hypothesis "<hypothesis>" --approach "<what you changed>" --outcome <failed|progress|passed|blocked>
   ```

   - Multi-line error output: pass `--error -` and pipe the text to stdin. This avoids shell quoting problems in PowerShell and bash.
   - `--outcome` defaults to `failed`. `--error` may be omitted when the outcome is `passed`.
   - Use the same `--task-id` for the whole task so repeats are detected.
5. **Obey the verdict** (first line of the output).
6. **Change approach properly.** Cite the evidence that rules out the old hypothesis, change one meaningful variable at a time, and state what result would confirm or reject the new hypothesis.

## Verdicts

| Verdict | Exit code | Meaning | What to do |
|---|---|---|---|
| `continue` | 0 | New or progressing failure, within budget | Make the next evidence-backed attempt |
| `resolved` | 0 | Outcome was `passed`; counters reset | Move on |
| `change-approach` | 10 | Same signature seen again, near-identical approach, destructive command, or task budget nearly spent | Do **not** repeat. Use a different approach as defined above |
| `stop-and-escalate` | 20 | Limit reached, or outcome was `blocked` | Stop. Write the escalation report |
| (script error) | 2 | Bad arguments, unreadable or corrupt ledger, write failure | Use the manual fallback below |

The script also prints `reason:` and `warning:` lines. Read them; they say why the verdict was chosen.

## Limits

- Default: **3** failures per signature and **6** per task. A new signature starts its own count.
- Override per call with `--max-attempts N` and `--max-task-attempts N`, or with the environment variables `AGENTGUARD_MAX_ATTEMPTS` and `AGENTGUARD_MAX_TASK_ATTEMPTS`. Use the user's limit if they gave one.
- The YAML config file is **not** read by this script.
- Counters reset after a `passed` outcome for that task.
- Rerunning an unchanged flaky test once to confirm flakiness is allowed. Label it "flaky" in your report.
- Check state any time: `python .github/skills/loop-guard/scripts/record_attempt.py --status [--task-id <id>]`.

## Not valid ways to escape a loop

Never do these without explicit user approval. The script warns when an approach or command looks like one:

- Delete, skip, or weaken the failing test or assertion.
- Disable lint, type, or security checks, or add `noqa`, `@ts-ignore`, `eslint-disable`.
- Swallow exceptions or hardcode the expected value.
- Use `--force` or `--no-verify`, or lower coverage thresholds.
- Mock out the component that is actually failing.

## Safety

- Never automatically repeat destructive commands (`rm -rf`, `git reset --hard`, `git clean -f`, dropping data, force pushes, down-migrations). The script flags them. Ask first.
- Never fabricate output, errors, or results. Never hide an unresolved failure or call it fixed.
- State plainly when user intervention is required.

## Escalation report

When the verdict is `stop-and-escalate`, report:

1. **Task and expected result**
2. **Attempts:** numbered, each with command, hypothesis, approach, and real outcome (the ledger at `.agentguard/attempts.json` has them)
3. **Most likely root cause** and the evidence for it
4. **Remaining uncertainty:** what you could not confirm
5. **What you did not try**, and why
6. **Next action:** the specific step for the user, or for you with approval
7. **User intervention needed?** yes or no, and exactly what (credentials, access, a decision)

## Examples

**Failing Python test.** `pytest tests/test_user.py` fails with `KeyError: 'email'`. Attempt 1 adds the key in the serializer; attempt 2 adds it with a default. Both give the same signature, so the verdict is `change-approach`. New evidence: print the fixture payload, which lacks the field. Fix the fixture, not the serializer.

**API error.** `POST /orders` returns `401` after two header changes. Stop guessing at headers. Check whether the token is expired. If a user must supply new credentials, record `--outcome blocked` and escalate.

**Frontend build failure.** `npm run build` fails with `Module not found: 'lodash'` after two reinstalls. Check whether `lodash` is declared in `package.json` and whether the lockfile matches. Ask before resetting the lockfile.

## Fallback

If the script is missing or exits with code 2, follow this procedure manually, keep a numbered attempt list in your reply, and say explicitly that the ledger was not updated. If the ledger is corrupt, tell the user. They can move it aside, or you can rerun with `--reset-corrupt` (the old file is kept as `attempts.json.corrupt-<timestamp>`). Add `.agentguard/` to `.gitignore` so the ledger is not committed.