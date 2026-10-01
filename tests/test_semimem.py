import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SEMIMEM = Path(__file__).resolve().parent.parent / "skill" / "bin" / "semimem"


class Repo:
    def __init__(self, config):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        (self.root / ".semimem.toml").write_text(textwrap.dedent(config))
        self.env = {**os.environ, "XDG_STATE_HOME": str(self.root / "state"), "SEMIMEM_AGENT": "test"}
        self.env.pop("SEMIMEM_MODE", None)
        self.env.pop("CLAUDE_PROJECT_DIR", None)

    def run(self, *args, stdin=None, check=True):
        result = subprocess.run(
            [sys.executable, str(SEMIMEM), *args],
            cwd=self.root,
            env=self.env,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise AssertionError(f"semimem {args} failed: {result.stderr}")
        return result

    def propose(self, *args):
        out = self.run("propose", *args).stdout
        return out.split()[1].rstrip(":")

    def records(self):
        return {r["id"]: r for r in json.loads(self.run("list", "--status", "all", "--json").stdout)}


class Case(unittest.TestCase):
    def make(self, config):
        repo = Repo(config)
        self.addCleanup(repo.dir.cleanup)
        return repo


MARKDOWN = """\
queue = "queue.jsonl"
[targets.notes]
builtin = "markdown"
path = "MEMORY.md"
"""


class MarkdownTarget(Case):
    def test_approve_writes_and_edit_replaces_entry(self):
        repo = self.make(MARKDOWN)
        first = repo.propose("--title", "Build", "--text", "Run just build.")
        repo.run("approve", first)
        second = repo.propose("--title", "Build", "--text", "Run nix build.")
        repo.run("approve", second, "--text", "Run nix build .#default.")
        text = (repo.root / "MEMORY.md").read_text()
        self.assertIn("**Build** — Run nix build .#default.", text)
        self.assertNotIn("just build", text)
        self.assertEqual(repo.records()[second]["status"], "applied")

    def test_target_changed_after_proposal_is_refused(self):
        repo = self.make(MARKDOWN)
        (repo.root / "MEMORY.md").write_text("## Memory\n\n- **Build** — Run just build.\n")
        ident = repo.propose("--title", "Build", "--text", "Run nix build.")
        (repo.root / "MEMORY.md").write_text("## Memory\n\n- **Build** — Run make.\n")
        result = repo.run("approve", ident, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(repo.records()[ident]["status"], "stale")
        self.assertIn("Run make.", (repo.root / "MEMORY.md").read_text())
        repo.run("approve", ident, "--force")
        self.assertIn("Run nix build.", (repo.root / "MEMORY.md").read_text())

    def test_duplicate_proposal_is_not_queued_twice(self):
        repo = self.make(MARKDOWN)
        first = repo.propose("--title", "Build", "--text", "Run just build.")
        again = repo.run("propose", "--title", "Build", "--text", "Run just build.").stdout
        self.assertIn(first, again)
        self.assertEqual(len(repo.records()), 1)


COMMANDS = """\
queue = "queue.jsonl"
[targets.cmd]
write = "cat > written-{ref}.txt"
discard = "touch discarded-{ref}"
fingerprint = "cat written-{ref}.txt 2>/dev/null"

[targets.broken]
write = "echo nope >&2; exit 3"

[targets.agent]
writer = "agent"
instructions = "Append it to NOTES.org."

[[importers]]
name = "legacy"
target = "cmd"
command = "cat items.jsonl"
"""


class CommandTargets(Case):
    def test_write_and_discard_commands_get_quoted_fields(self):
        repo = self.make(COMMANDS)
        ident = repo.propose("--title", "x", "--ref", "a b", "--target", "cmd", "--text", "hello")
        repo.run("approve", ident)
        self.assertEqual((repo.root / "written-a b.txt").read_text(), "hello")
        other = repo.propose("--title", "y", "--ref", "c", "--target", "cmd", "--text", "bye")
        repo.run("reject", other, "--reason", "wrong")
        self.assertTrue((repo.root / "discarded-c").exists())
        self.assertEqual(repo.records()[other]["status"], "rejected")

    def test_failed_write_is_recorded_and_retryable(self):
        repo = self.make(COMMANDS)
        ident = repo.propose("--title", "x", "--target", "broken", "--text", "t")
        result = repo.run("approve", ident, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nope", result.stderr)
        self.assertEqual(repo.records()[ident]["status"], "failed")
        repo.run("approve", ident, "--target", "cmd")
        self.assertEqual(repo.records()[ident]["status"], "applied")

    def test_agent_writer_prints_brief_and_waits_for_done(self):
        repo = self.make(COMMANDS)
        ident = repo.propose("--title", "x", "--target", "agent", "--text", "remember me")
        out = repo.run("approve", ident).stdout
        self.assertIn("Append it to NOTES.org.", out)
        self.assertIn("remember me", out)
        self.assertEqual(repo.records()[ident]["status"], "approved")
        repo.run("done", ident, "--detail", "NOTES.org")
        self.assertEqual(repo.records()[ident]["status"], "applied")

    def test_importer_skips_items_already_open_or_seen(self):
        repo = self.make(COMMANDS)
        item = {"key": "n1", "title": "Note", "text": "v1"}
        (repo.root / "items.jsonl").write_text(json.dumps(item) + "\n")
        repo.run("sync")
        repo.run("sync")
        self.assertEqual(len(repo.records()), 1)
        (repo.root / "items.jsonl").write_text(json.dumps({**item, "text": "v2"}) + "\n")
        repo.run("sync")
        self.assertEqual(len(repo.records()), 1, "an open record for the key blocks re-import")
        (ident,) = repo.records()
        repo.run("reject", ident)
        repo.run("sync")
        self.assertEqual(len(repo.records()), 2, "changed text after a decision is a new candidate")


class StopHook(Case):
    def hook(self, repo, transcript, active=False):
        payload = {
            "session_id": "s1",
            "cwd": str(repo.root),
            "transcript_path": str(transcript),
            "stop_hook_active": active,
        }
        return repo.run("hook", "stop", stdin=json.dumps(payload)).stdout

    def test_blocks_only_after_enough_new_tool_calls(self):
        repo = self.make(MARKDOWN + "[stop_hook]\nmin_tool_calls = 3\n")
        transcript = repo.root / "t.jsonl"
        transcript.write_text('{"type":"tool_use"}\n' * 2)
        self.assertEqual(self.hook(repo, transcript), "")
        transcript.write_text('{"type":"tool_use"}\n' * 3)
        self.assertEqual(json.loads(self.hook(repo, transcript))["decision"], "block")
        self.assertEqual(self.hook(repo, transcript, active=True), "")
        transcript.write_text('{"type":"tool_use"}\n' * 5)
        self.assertEqual(self.hook(repo, transcript), "", "counts from the last offer")
        transcript.write_text('{"type": "function_call"}\n' * 6)
        self.assertIn("propose --session s1", json.loads(self.hook(repo, transcript))["reason"])

    def test_session_start_reports_pending_queue(self):
        repo = self.make(MARKDOWN)
        repo.propose("--title", "Build", "--text", "Run just build.")
        out = repo.run("hook", "session-start", stdin=json.dumps({"session_id": "s1", "cwd": str(repo.root)})).stdout
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("1 pending", context)


if __name__ == "__main__":
    unittest.main()
