---
name: auto-commit-guard
description: Prepare a focused Git commit after completed work and passing tests. Use when the user requests or explicitly authorizes a commit.
---
# Auto-Commit Guard

This skill does not automatically monitor filesystem changes and must not commit after every edit by default.

1. Confirm the task is complete and relevant tests passed.
2. Inspect Git status, full diff, and untracked files. Preserve unrelated changes.
3. Check selected files for credentials and sensitive filenames.
4. Propose the exact paths and commit message.
5. Require explicit user approval before creating the commit unless the user already clearly authorized this specific commit.
6. Use the helper's dry-run mode first:
   `python .github/skills/auto-commit-guard/scripts/auto_commit.py --dry-run --message "feat: describe change" path/to/file`
7. After approval, use `--yes` only if the helper's prerequisites pass. Verify the resulting commit.
8. Never push, amend, reset, force-push, or rewrite shared history unless separately authorized.

If the helper is unavailable or its prerequisites cannot be verified, explain that and do not bypass the safeguards.
