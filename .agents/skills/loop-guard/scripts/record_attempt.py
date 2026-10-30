#!/usr/bin/env python3
"""Loop Guard ledger: record a coding attempt and get a verdict on what to do next.

Verdicts and exit codes:
    continue           0   within budget; keep going with an evidence-backed attempt
    resolved           0   the command passed; per-task counters reset
    change-approach   10   same failure repeated (or budget nearly spent); do NOT repeat
    stop-and-escalate 20   limit reached or blocked; stop and report to the user
    (error)            2   bad arguments, unreadable/corrupt ledger, or write failure

State lives in <repo-root>/.agentguard/attempts.json (schema_version 1).
Only the standard library is used. Limits come from flags or the environment
variables AGENTGUARD_MAX_ATTEMPTS / AGENTGUARD_MAX_TASK_ATTEMPTS; the YAML
config file is NOT read by this script.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_TASK_ATTEMPTS = 6
APPROACH_SIMILARITY = 0.85
MAX_ERROR_CHARS = 2000
MAX_COMMAND_CHARS = 1000
MAX_FIELD_CHARS = 500

OUTCOMES = ["failed", "progress", "passed", "blocked"]
FAILING_OUTCOMES = {"failed", "progress"}
EXIT_CODES = {"continue": 0, "resolved": 0, "change-approach": 10, "stop-and-escalate": 20}
SEVERITY = {"continue": 0, "resolved": 0, "change-approach": 1, "stop-and-escalate": 2}
TASK_ID_RE = re.compile(r"^[\w.:-]{1,64}$")
NEXT_STEP = {
    "continue": "Proceed with the next evidence-backed attempt.",
    "resolved": "Done with this failure. Record nothing further unless it regresses.",
    "change-approach": "Do not repeat the previous approach. Test a different hypothesis "
    "(different layer, or gather new evidence first).",
    "stop-and-escalate": "Stop. Write the escalation report and tell the user what you need.",
}

# --------------------------------------------------------------------------- redaction
_QUOTED_OR_BARE = r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
_REDACTIONS: List[Tuple["re.Pattern[str]", str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
     "<REDACTED:private-key>"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "<REDACTED:aws-key>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "<REDACTED:github-token>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "<REDACTED:github-token>"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "<REDACTED:slack-token>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "<REDACTED:api-key>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "<REDACTED:jwt>"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer <REDACTED>"),
    (re.compile(r"(?i)(://[^/\s:@]+):[^@\s/]+@"), r"\1:<REDACTED>@"),
    (re.compile(r"(?i)(\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
                r"authorization)[\w.-]*\s*[=:]\s*)" + _QUOTED_OR_BARE), r"\1<REDACTED>"),
    (re.compile(r"(?i)(--?(?:password|passwd|token|secret|api[-_]?key)[\s=])" + _QUOTED_OR_BARE),
     r"\1<REDACTED>"),
]


def redact(text: str) -> str:
    """Replace likely secrets in ``text`` with placeholders (best effort, may over-redact)."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


# ------------------------------------------------------------------------ normalization
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_URL_QUERY = re.compile(r"(https?://[^\s'\"?#]+)[?#]\S*")
_ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_CLOCK = re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\b")
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_HEX_ADDR = re.compile(r"\b0x[0-9a-fA-F]+\b")
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{12,}\b")
_WIN_PATH = re.compile(r"(?<![\w])[A-Za-z]:[\\/](?![\\/])(?:[^\s\\/:*?\"<>|'()]+[\\/])*[^\s\\/:*?\"<>|'()]*")
_POSIX_PATH = re.compile(r"(?<![\w:/.<>-])(?:~|\.{1,2})?/(?:[\w.@+~-]+/)+[\w.@+~-]+")
_REL_FILE = re.compile(r"(?<![\w:/.<>-])(?:[\w.@+~-]+/)+[\w.@+~-]+\.\w{1,6}\b")
_FS_ROOTS = ("/home/", "/users/", "/tmp/", "/var/", "/usr/", "/opt/", "/mnt/", "/workspace/",
             "/app/", "/src/", "/private/", "~/", "./", "../")
_LINE_COL = re.compile(r"(\.\w{1,6}):\d+(?::\d+)?")
_LINE_WORD = re.compile(r"\b(line|lineno|col|column|pid)[ =:]+\d+", re.I)
_DURATION = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|µs|us|s|sec|secs|seconds|min|minutes)\b", re.I)


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1]


def _sub_win(match: "re.Match[str]") -> str:
    return "<path>/" + _basename(match.group(0))


def _sub_posix(match: "re.Match[str]") -> str:
    text = match.group(0)
    looks_like_fs = text.lower().startswith(_FS_ROOTS) or re.search(r"\.\w{1,6}$", text)
    return "<path>/" + _basename(text) if looks_like_fs else text


def normalize(value: str) -> str:
    """Strip volatile noise (paths, line numbers, timestamps, ids) so repeats compare equal.

    File basenames and numbers that carry meaning (HTTP status, exit codes) are kept.
    """
    value = _ANSI.sub("", value)
    value = _URL_QUERY.sub(r"\1", value)
    value = _ISO_TS.sub("<ts>", value)
    value = _CLOCK.sub("<time>", value)
    value = _UUID.sub("<uuid>", value)
    value = _HEX_ADDR.sub("<addr>", value)
    value = _LONG_HEX.sub("<hash>", value)
    value = _WIN_PATH.sub(_sub_win, value)
    value = _POSIX_PATH.sub(_sub_posix, value)
    value = _REL_FILE.sub(_sub_win, value)
    value = _LINE_COL.sub(r"\1:<n>", value)
    value = _LINE_WORD.sub(lambda m: f"{m.group(1).lower()} <n>", value)
    value = _DURATION.sub("<dur>", value)
    return re.sub(r"\s+", " ", value).strip().lower()[:500]


def signature_id(signature: str) -> str:
    """Short stable id for a normalized signature (for display only)."""
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------- risk checks
_DESTRUCTIVE = re.compile(
    r"\brm\s+-[a-z]*[rf][a-z]*\b|\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-[a-z]*f|"
    r"\bgit\s+push\b.*(?:--force|\s-f\b)|\bgit\s+checkout\s+--\s|\bgit\s+restore\b|"
    r"\bdrop\s+(?:table|database|schema)\b|\btruncate\s+table\b|\bdel\s+/[sfq]|\brmdir\s+/s|"
    r"remove-item\b.*-recurse|\bmkfs\b|\bdd\s+if=|\bdocker\s+system\s+prune|"
    r"\bkubectl\s+delete\b|\bterraform\s+destroy\b|\b(?:migrate|alembic)\b.*\b(?:down|downgrade)\b",
    re.I,
)
_WEAKENING = re.compile(
    r"--no-verify|\bskip(?:ped|ping)?\s+(?:the\s+)?(?:failing\s+)?tests?\b|@pytest\.mark\.skip|\bxfail\b|"
    r"\bdelet(?:e|ed|ing)\s+(?:the\s+)?(?:failing\s+)?tests?\b|"
    r"\bdisabl(?:e|ed|ing)\s+(?:the\s+)?(?:lint|linter|type|security|check)|--force\b|\bnoqa\b|"
    r"eslint-disable|@ts-ignore|#\s*type:\s*ignore|\blower(?:ed|ing)?\s+(?:the\s+)?coverage|"
    r"\bcomment(?:ed|ing)?\s+out\s+(?:the\s+)?(?:tests?|assert)|\bswallow|except\s*:\s*pass",
    re.I,
)


def risk_warnings(entry: Dict[str, Any], history: List[Dict[str, Any]]) -> List[str]:
    """Warn about destructive commands and attempts that weaken checks."""
    warnings: List[str] = []
    command = entry["command"]
    if _DESTRUCTIVE.search(command):
        repeated = any(normalize(e.get("command", "")) == normalize(command) for e in history)
        warnings.append(
            "Destructive command detected. Do not repeat it automatically; get user approval."
            if repeated else
            "Destructive command detected. Confirm with the user before running it again."
        )
    if _WEAKENING.search(entry["approach"]) or _WEAKENING.search(command):
        warnings.append("This approach looks like it weakens a check (skip/disable/force). "
                        "That is not a fix; get explicit user approval first.")
    return warnings


# ------------------------------------------------------------------------------- ledger
class LedgerError(Exception):
    """Raised when the attempt ledger cannot be read, validated, or written."""


def new_ledger() -> Dict[str, Any]:
    """Return an empty ledger."""
    return {"schema_version": SCHEMA_VERSION, "attempts": []}


def load_ledger(path: Path) -> Dict[str, Any]:
    """Load and validate the ledger; a missing file yields an empty ledger."""
    if not path.exists():
        return new_ledger()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LedgerError(f"cannot read ledger {path}: {exc}") from exc
    attempts = data.get("attempts") if isinstance(data, dict) else None
    if not isinstance(attempts, list) or not all(isinstance(a, dict) for a in attempts):
        raise LedgerError(f"ledger {path} has an unexpected structure")
    version = data.get("schema_version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        raise LedgerError(f"ledger {path} has unsupported schema_version {version!r}")
    return data


def save_ledger(path: Path, data: Dict[str, Any]) -> None:
    """Write the ledger atomically (temp file + replace)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".attempts-", suffix=".tmp")
    except OSError as exc:
        raise LedgerError(f"cannot write ledger {path}: {exc}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except OSError as exc:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise LedgerError(f"cannot write ledger {path}: {exc}") from exc


def back_up_corrupt(path: Path) -> Path:
    """Move an unreadable ledger aside (never deleted) so a fresh one can start."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        path.replace(target)
    except OSError as exc:
        raise LedgerError(f"cannot back up corrupt ledger: {exc}") from exc
    return target


def find_root(start: Path) -> Tuple[Path, Optional[str]]:
    """Return the Git top-level directory, or ``start`` plus a note when Git is unusable."""
    try:
        proc = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return start, "git is unavailable; ledger stored under --root"
    if proc.returncode != 0 or not proc.stdout.strip():
        return start, "not a Git repository; ledger stored under --root"
    return Path(proc.stdout.strip()), None


# -------------------------------------------------------------------------- evaluation
def since_last_pass(entries: List[Dict[str, Any]], task_id: str) -> List[Dict[str, Any]]:
    """Entries for ``task_id`` recorded after its most recent ``passed`` outcome."""
    kept: List[Dict[str, Any]] = []
    for entry in entries:
        if entry.get("task_id") != task_id:
            continue
        if entry.get("outcome") == "passed":
            kept = []
        else:
            kept.append(entry)
    return kept


def evaluate(history: List[Dict[str, Any]], entry: Dict[str, Any],
             max_attempts: int, max_task: int) -> Dict[str, Any]:
    """Decide the verdict for ``entry`` given the task's prior ``history``."""
    if entry["outcome"] == "passed":
        return {"verdict": "resolved", "reasons": ["Command passed; counters reset for this task."],
                "same_signature_count": 0, "task_failure_count": 0}

    failing = [e for e in history if e.get("outcome") in FAILING_OUTCOMES]
    same = [e for e in failing if e.get("signature") == entry["signature"]]
    sig_count, task_count = len(same) + 1, len(failing) + 1
    verdict, reasons = "continue", []

    def raise_to(level: str, reason: str) -> None:
        nonlocal verdict
        reasons.append(reason)
        if SEVERITY[level] > SEVERITY[verdict]:
            verdict = level

    if entry["outcome"] == "blocked":
        raise_to("stop-and-escalate", "Blocked: needs access, credentials, or a user decision.")
    if sig_count >= max_attempts:
        raise_to("stop-and-escalate", f"Same failure seen {sig_count} times (limit {max_attempts}).")
    if task_count >= max_task:
        raise_to("stop-and-escalate", f"{task_count} failed attempts on this task (limit {max_task}).")
    if sig_count >= 2:
        raise_to("change-approach", f"Same failure signature seen {sig_count} times.")
    wanted = _squash(entry["approach"])
    for prior in same:
        ratio = difflib.SequenceMatcher(None, wanted, _squash(prior.get("approach", ""))).ratio()
        if ratio >= APPROACH_SIMILARITY:
            raise_to("change-approach",
                     f"Approach is nearly identical to attempt #{prior.get('id', '?')}.")
            break
    if task_count == max_task - 1:
        raise_to("change-approach", "One failed attempt left in this task's budget.")
    if not reasons:
        reasons.append("New or progressing failure; within budget.")
    return {"verdict": verdict, "reasons": reasons,
            "same_signature_count": sig_count, "task_failure_count": task_count}


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


# ----------------------------------------------------------------------------------- CLI
def positive_int(raw: str) -> int:
    """argparse type: integer >= 1."""
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer")
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def env_int(name: str, default: int) -> int:
    """Read a positive integer from the environment, or fall back (with a stderr note)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return positive_int(raw)
    except argparse.ArgumentTypeError as exc:
        print(f"warning: ignoring {name}: {exc}", file=sys.stderr)
        return default


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    p = argparse.ArgumentParser(description="Record a coding attempt and get a Loop Guard verdict.")
    p.add_argument("--root", type=Path, default=Path.cwd(), help="start directory (default: cwd)")
    p.add_argument("--task-id", help="short id for the task, e.g. fix-login (letters, digits, . _ : -)")
    p.add_argument("--command", help="the command that was run")
    p.add_argument("--error", help="error summary; use '-' to read it from stdin")
    p.add_argument("--hypothesis", help="why you think it failed")
    p.add_argument("--approach", help="what you changed or tried")
    p.add_argument("--outcome", choices=OUTCOMES, default="failed")
    p.add_argument("--max-attempts", type=positive_int,
                   help=f"limit per failure signature (default {DEFAULT_MAX_ATTEMPTS})")
    p.add_argument("--max-task-attempts", type=positive_int,
                   help=f"limit per task (default {DEFAULT_MAX_TASK_ATTEMPTS})")
    p.add_argument("--status", action="store_true", help="show counts instead of recording")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--reset-corrupt", action="store_true",
                   help="move a corrupt ledger aside and start a new one")
    return p


def emit(args: argparse.Namespace, payload: Dict[str, Any], lines: List[str]) -> None:
    """Print ``payload`` as JSON or ``lines`` as text."""
    print(json.dumps(payload, indent=2) if args.json else "\n".join(lines))


def run_status(args: argparse.Namespace, ledger: Dict[str, Any], path: Path) -> int:
    """Print failure counts per task and signature since each task's last pass."""
    tasks = sorted({e.get("task_id") for e in ledger["attempts"] if e.get("task_id")})
    if args.task_id:
        tasks = [t for t in tasks if t == args.task_id]
    summary: Dict[str, Any] = {}
    for task in tasks:
        failing = [e for e in since_last_pass(ledger["attempts"], task)
                   if e.get("outcome") in FAILING_OUTCOMES]
        counts: Dict[str, int] = {}
        for e in failing:
            counts[e.get("signature", "?")] = counts.get(e.get("signature", "?"), 0) + 1
        summary[task] = {"failures": len(failing), "by_signature": counts}
    lines = [f"ledger: {path}"] + ([f"{t}: {s['failures']} failure(s) since last pass, "
                                    f"{len(s['by_signature'])} distinct signature(s)"
                                    for t, s in summary.items()] or ["no attempts recorded"])
    emit(args, {"ledger_path": str(path), "tasks": summary}, lines)
    return 0


def run_record(args: argparse.Namespace, ledger: Dict[str, Any], path: Path,
               notes: List[str]) -> int:
    """Validate input, evaluate, append to the ledger, and report the verdict."""
    error_text = sys.stdin.read() if args.error == "-" else (args.error or "")
    entry = {
        "task_id": args.task_id,
        "command": redact(args.command)[:MAX_COMMAND_CHARS],
        "error": redact(error_text).strip()[:MAX_ERROR_CHARS],
        "hypothesis": redact(args.hypothesis)[:MAX_FIELD_CHARS],
        "approach": redact(args.approach)[:MAX_FIELD_CHARS],
        "outcome": args.outcome,
    }
    entry["signature"] = normalize(entry["error"])
    history = since_last_pass(ledger["attempts"], args.task_id)
    result = evaluate(history, entry,
                      args.max_attempts or env_int("AGENTGUARD_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS),
                      args.max_task_attempts or env_int("AGENTGUARD_MAX_TASK_ATTEMPTS",
                                                        DEFAULT_MAX_TASK_ATTEMPTS))
    warnings = notes + risk_warnings(entry, history)
    if result["verdict"] == "continue" and any("Destructive" in w for w in warnings):
        result["verdict"] = "change-approach"
        result["reasons"].append("Destructive command needs user approval before another run.")

    number = len(ledger["attempts"]) + 1
    ledger["attempts"].append({
        "id": number, **entry, "signature_id": signature_id(entry["signature"]),
        "verdict": result["verdict"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    save_ledger(path, ledger)

    code = EXIT_CODES[result["verdict"]]
    payload = {"verdict": result["verdict"], "exit_code": code, "attempt_id": number,
               "task_id": args.task_id, "signature_id": signature_id(entry["signature"]),
               "same_signature_count": result["same_signature_count"],
               "task_failure_count": result["task_failure_count"],
               "reasons": result["reasons"], "warnings": warnings, "ledger_path": str(path)}
    lines = [result["verdict"],
             f"  attempt #{number} for task '{args.task_id}' "
             f"(same signature: {result['same_signature_count']}, "
             f"task failures: {result['task_failure_count']})"]
    lines += [f"  reason: {r}" for r in result["reasons"]]
    lines += [f"  warning: {w}" for w in warnings]
    lines.append(f"  next: {NEXT_STEP[result['verdict']]}")
    emit(args, payload, lines)
    return code


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point; returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.task_id is not None and not TASK_ID_RE.match(args.task_id):
        parser.error("--task-id must be 1-64 characters: letters, digits, . _ : -")
    if not args.status:
        missing = [f"--{n}" for n in ("task-id", "command", "hypothesis", "approach")
                   if getattr(args, n.replace("-", "_")) is None]
        if args.outcome != "passed" and not (args.error or "").strip():
            missing.append("--error")
        if missing:
            parser.error("missing required arguments: " + ", ".join(missing))

    root, note = find_root(args.root.resolve())
    notes = [note] if note else []
    path = root / ".agentguard" / "attempts.json"
    try:
        try:
            ledger = load_ledger(path)
        except LedgerError as exc:
            if not args.reset_corrupt:
                print(f"error: {exc}\nFix or move the file, or rerun with --reset-corrupt "
                      "(the old file is kept as a .corrupt-* backup). Using manual mode meanwhile.",
                      file=sys.stderr)
                return 2
            backup = back_up_corrupt(path)
            notes.append(f"corrupt ledger moved to {backup.name}; started a new one")
            ledger = new_ledger()
        if args.status:
            return run_status(args, ledger, path)
        return run_record(args, ledger, path, notes)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())