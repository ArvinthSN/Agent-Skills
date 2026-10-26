---
name: change-guard
description: Review Git changes before or after edits, identify unexpected paths, and check for common secret patterns. Use during preflight and before reporting a task complete.
---
# Change Guard

1. Inspect `git status --short --untracked-files=all` and the current diff.
2. Distinguish pre-existing changes from changes caused by the current task. Do not discard user changes.
3. Inspect untracked files separately; ordinary `git diff` does not include their contents.
4. Flag sensitive-looking filenames and common secret patterns. Explain that detection is heuristic.
5. Run relevant tests and report the actual results.
6. Never stage, delete, or commit files as part of this review.

Helper usage:
- Capture a baseline: `python .github/skills/change-guard/scripts/check_changes.py --baseline`
- Inspect current status: `python .github/skills/change-guard/scripts/check_changes.py --json`

If a helper option is unavailable, inspect `--help` and perform the review manually. Do not claim the helper performs a check it does not implement.
