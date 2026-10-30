"""Tests for scripts/record_attempt.py (run: python -m unittest discover -s tests -v)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record_attempt.py"
sys.path.insert(0, str(SCRIPT.parent))
import record_attempt as ra  # noqa: E402


def run(cwd, *args, stdin=None, env=None):
    """Run the script as a subprocess; return (exit_code, stdout, stderr)."""
    full_env = {**os.environ, **(env or {})}
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, input=stdin,
                          capture_output=True, text=True, env=full_env)
    return proc.returncode, proc.stdout, proc.stderr


def record(cwd, error, approach="a", task="t1", outcome="failed", command="pytest", extra=()):
    return run(cwd, "--task-id", task, "--command", command, "--error", error,
               "--hypothesis", "h", "--approach", approach, "--outcome", outcome, *extra)


class RepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        self.ledger = self.repo / ".agentguard" / "attempts.json"

    def entries(self):
        return json.loads(self.ledger.read_text(encoding="utf-8"))["attempts"]


class NormalizeTests(unittest.TestCase):
    def test_paths_and_lines_collapse(self):
        a = ra.normalize('File "/home/alice/app/tests/test_user.py", line 12, KeyError: email')
        b = ra.normalize('File "C:\\Users\\bob\\proj\\tests\\test_user.py", line 99, KeyError: email')
        self.assertEqual(a, b)
        self.assertIn("test_user.py", a)

    def test_timestamps_addresses_uuids_ignored(self):
        a = ra.normalize("2026-01-02T10:00:00Z err at 0xdeadbeef id 123e4567-e89b-12d3-a456-426614174000 in 1.5s")
        b = ra.normalize("2026-05-09T23:59:59Z err at 0x1234 id 00000000-0000-0000-0000-000000000000 in 9s")
        self.assertEqual(a, b)

    def test_meaningful_numbers_kept(self):
        self.assertNotEqual(ra.normalize("HTTP 401 Unauthorized"), ra.normalize("HTTP 404 Unauthorized"))

    def test_api_route_not_mistaken_for_file_path(self):
        self.assertIn("/api/orders/123", ra.normalize("POST /api/orders/123 failed with 500"))

    def test_error_text_is_not_swallowed_after_path(self):
        self.assertIn("keyerror", ra.normalize("/tmp/x/app.py:10: KeyError: 'email'"))

    def test_url_scheme_not_mistaken_for_drive_letter(self):
        out = ra.normalize("POST https://api.x.com/orders?ts=1 -> 401 Unauthorized")
        self.assertEqual(out, "post https://api.x.com/orders -> 401 unauthorized")

    def test_url_query_stripped(self):
        self.assertEqual(ra.normalize("GET https://a.io/x?id=1 failed"),
                         ra.normalize("GET https://a.io/x?id=2 failed"))


class RedactTests(unittest.TestCase):
    def test_secrets_redacted(self):
        text = ("curl -H 'Authorization: Bearer abcdefghijklmnop' --token s3cr3tvalue "
                "password=hunter2 ghp_" + "a" * 30 + " postgres://u:pw@host/db AKIA" + "A" * 16)
        out = ra.redact(text)
        for leaked in ("abcdefghijklmnop", "s3cr3tvalue", "hunter2", "a" * 30, ":pw@", "AKIA" + "A" * 16):
            self.assertNotIn(leaked, out)

    def test_plain_text_untouched(self):
        self.assertEqual(ra.redact("KeyError: 'email'"), "KeyError: 'email'")


class VerdictTests(RepoCase):
    def test_first_failure_continues(self):
        code, out, _ = record(self.repo, "KeyError: email")
        self.assertEqual((code, out.splitlines()[0]), (0, "continue"))

    def test_second_repeat_changes_approach_third_stops(self):
        record(self.repo, "KeyError: email", approach="add key to serializer")
        code, out, _ = record(self.repo, "KeyError: email", approach="inspect fixture payload")
        self.assertEqual((code, out.splitlines()[0]), (10, "change-approach"))
        code, out, _ = record(self.repo, "KeyError: email", approach="patch the schema")
        self.assertEqual((code, out.splitlines()[0]), (20, "stop-and-escalate"))

    def test_line_number_change_still_same_signature(self):
        record(self.repo, "app.py:10 KeyError: email", approach="one")
        code, _, _ = record(self.repo, "app.py:55 KeyError: email", approach="completely different idea")
        self.assertEqual(code, 10)

    def test_tasks_are_independent(self):
        record(self.repo, "boom", task="a")
        record(self.repo, "boom", task="a", approach="x2")
        code, _, _ = record(self.repo, "boom", task="b")
        self.assertEqual(code, 0)

    def test_different_error_is_not_a_repeat(self):
        record(self.repo, "KeyError: email")
        code, _, _ = record(self.repo, "TypeError: bad operand")
        self.assertEqual(code, 0)

    def test_passed_resets_counters(self):
        record(self.repo, "boom", approach="one")
        record(self.repo, "boom", approach="two")
        code, out, _ = record(self.repo, "", outcome="passed")
        self.assertEqual((code, out.splitlines()[0]), (0, "resolved"))
        code, out, _ = record(self.repo, "boom", approach="three")
        self.assertEqual((code, out.splitlines()[0]), (0, "continue"))

    def test_blocked_escalates_immediately(self):
        code, out, _ = record(self.repo, "401 expired token", outcome="blocked")
        self.assertEqual((code, out.splitlines()[0]), (20, "stop-and-escalate"))

    def test_task_cap_across_signatures(self):
        codes = [record(self.repo, f"distinct failure {c}", approach=f"approach {c}",
                        extra=("--max-task-attempts", "3"))[0] for c in "xyz"]
        self.assertEqual(codes, [0, 10, 20])

    def test_identical_approach_flagged(self):
        record(self.repo, "boom", approach="add retry with sleep")
        code, _, _ = record(self.repo, "boom", approach="Add retry, with sleep!")
        self.assertEqual(code, 10)
        out = record(self.repo, "boom", approach="x", extra=("--json",))[1]
        self.assertEqual(json.loads(out)["verdict"], "stop-and-escalate")

    def test_progress_counts_toward_task_budget(self):
        record(self.repo, "first error", outcome="progress")
        self.assertEqual(self.entries()[0]["outcome"], "progress")
        code, _, _ = record(self.repo, "second error", extra=("--max-task-attempts", "2"))
        self.assertEqual(code, 20)

    def test_custom_and_env_limits(self):
        self.assertEqual(record(self.repo, "boom", extra=("--max-attempts", "1"))[0], 20)
        code, _, _ = run(self.repo, "--task-id", "e", "--command", "c", "--error", "bad",
                         "--hypothesis", "h", "--approach", "a", env={"AGENTGUARD_MAX_ATTEMPTS": "1"})
        self.assertEqual(code, 20)


class SafetyTests(RepoCase):
    def test_secrets_never_written_to_ledger(self):
        record(self.repo, "auth failed password=hunter2 ghp_" + "b" * 30,
               command="curl --token topsecretvalue https://x")
        raw = self.ledger.read_text(encoding="utf-8")
        for leaked in ("hunter2", "b" * 30, "topsecretvalue"):
            self.assertNotIn(leaked, raw)

    def test_destructive_command_warns_and_blocks_continue(self):
        code, out, _ = record(self.repo, "oops", command="git reset --hard HEAD")
        self.assertEqual(code, 10)
        self.assertIn("Destructive", out)

    def test_weakening_approach_warns(self):
        _, out, _ = record(self.repo, "boom", approach="skip the failing test")
        self.assertIn("weakens a check", out)


class LedgerTests(RepoCase):
    def test_corrupt_ledger_exit_2_and_untouched(self):
        self.ledger.parent.mkdir()
        self.ledger.write_text("{not json", encoding="utf-8")
        code, _, err = record(self.repo, "boom")
        self.assertEqual(code, 2)
        self.assertIn("--reset-corrupt", err)
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), "{not json")

    def test_reset_corrupt_keeps_backup(self):
        self.ledger.parent.mkdir()
        self.ledger.write_text("{not json", encoding="utf-8")
        code, _, _ = record(self.repo, "boom", extra=("--reset-corrupt",))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(len(list(self.ledger.parent.glob("attempts.json.corrupt-*"))), 1)

    def test_newer_schema_rejected(self):
        self.ledger.parent.mkdir()
        self.ledger.write_text(json.dumps({"schema_version": 99, "attempts": []}), encoding="utf-8")
        self.assertEqual(record(self.repo, "boom")[0], 2)

    def test_wrong_structure_rejected(self):
        self.ledger.parent.mkdir()
        self.ledger.write_text(json.dumps({"schema_version": 1, "attempts": "nope"}), encoding="utf-8")
        self.assertEqual(record(self.repo, "boom")[0], 2)

    def test_no_temp_files_left_behind(self):
        record(self.repo, "boom")
        self.assertEqual([p.name for p in self.ledger.parent.iterdir()], ["attempts.json"])

    def test_works_from_subdirectory_using_repo_root(self):
        sub = self.repo / "pkg" / "deep"
        sub.mkdir(parents=True)
        record(sub, "boom")
        self.assertTrue(self.ledger.exists())
        self.assertFalse((sub / ".agentguard").exists())


class CliTests(RepoCase):
    def test_missing_arguments_exit_2(self):
        code, _, err = run(self.repo, "--task-id", "t")
        self.assertEqual(code, 2)
        self.assertIn("missing required", err)

    def test_failed_outcome_requires_error(self):
        self.assertEqual(record(self.repo, "   ")[0], 2)

    def test_bad_task_id_exit_2(self):
        self.assertEqual(record(self.repo, "boom", task="bad id!")[0], 2)

    def test_bad_limit_exit_2(self):
        self.assertEqual(record(self.repo, "boom", extra=("--max-attempts", "0"))[0], 2)

    def test_error_from_stdin(self):
        code, _, _ = run(self.repo, "--task-id", "t", "--command", "c", "--error", "-",
                         "--hypothesis", "h", "--approach", "a", stdin="multi\nline KeyError")
        self.assertEqual(code, 0)
        self.assertIn("multi", self.entries()[0]["error"])

    def test_json_output_shape(self):
        _, out, _ = record(self.repo, "boom", extra=("--json",))
        data = json.loads(out)
        for key in ("verdict", "exit_code", "attempt_id", "signature_id", "reasons", "warnings"):
            self.assertIn(key, data)

    def test_status(self):
        record(self.repo, "boom")
        record(self.repo, "other", approach="b")
        code, out, _ = run(self.repo, "--status", "--task-id", "t1")
        self.assertEqual(code, 0)
        self.assertIn("2 failure(s)", out)
        self.assertIn("no attempts", run(self.repo, "--status", "--task-id", "zzz")[1])

    def test_outside_git_falls_back_with_warning(self):
        with tempfile.TemporaryDirectory() as plain:
            code, out, _ = record(Path(plain), "boom")
            self.assertEqual(code, 0)
            self.assertIn("not a Git repository", out)
            self.assertTrue((Path(plain) / ".agentguard" / "attempts.json").exists())


if __name__ == "__main__":
    unittest.main()