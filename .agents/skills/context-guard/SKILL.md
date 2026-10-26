---
name: context-guard
description: Preserve and recover verified project context, architecture decisions, task progress, and blockers across coding sessions. Use when starting or resuming substantial work.
---
# Context Guard

1. Inspect current repository instructions, source, Git status, and existing context before trusting notes.
2. Store durable notes under `.agentguard/context.md`; include project facts, decisions with rationale, conventions, current task, completed work, remaining work, blockers, and validation evidence.
3. Clearly label assumptions and unknowns. Source code and current Git state outrank stale notes.
4. Update context only at meaningful milestones or before interruption.
5. Never save credentials, tokens, private keys, or unnecessary personal information.
6. Do not claim context persisted unless a write actually succeeded.

Optional helper:
- Initialize context: `python .github/skills/context-guard/scripts/context_tool.py init`
- Check context commit marker: `python .github/skills/context-guard/scripts/context_tool.py check`
- Scan context for common secret patterns: `python .github/skills/context-guard/scripts/context_tool.py scan-secrets`

The secret scan is heuristic and cannot guarantee detection of every secret.
