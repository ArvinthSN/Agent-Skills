---
name: loop-guard
description: Detect repeated unsuccessful coding attempts, change approach using evidence, and stop unproductive loops. Use when a command, test, build, or debugging attempt fails repeatedly.
---
# Loop Guard

1. State the expected result and the current hypothesis.
2. Run the relevant command once and inspect its real output.
3. Record the attempt using `python .github/skills/loop-guard/scripts/record_attempt.py --task-id "<short-id>" --command "<command>" --error "<error summary>" --hypothesis "<hypothesis>" --approach "<approach>"`.
4. After the same failure occurs again, do not repeat the same approach unless new evidence justifies it.
5. Change one meaningful variable based on evidence and test the new hypothesis.
6. Stop after three failed attempts for the same task/failure and report the evidence, likely cause, uncertainty, and next step.

Do not fabricate output, hide failures, or rerun destructive commands automatically. If the script is missing or fails, use this procedure manually and say the ledger was not updated.
