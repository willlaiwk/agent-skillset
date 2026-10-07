#!/usr/bin/env python3
"""Behavioral tests with real Git repos and fake providers; no model/API calls.

Default: deterministic fake tmux. MANAGER_TEST_REAL_TMUX=1: real isolated tmux
server with the same fake providers, exercising interactive lifecycle and paste.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().with_name("manager")
REAL_TMUX = shutil.which("tmux")
USE_REAL = os.environ.get("MANAGER_TEST_REAL_TMUX") == "1"

FAKE_TMUX = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ["TEST_TMUX_STATE"])
s = json.loads(p.read_text()) if p.exists() else {"session": False, "panes": {}, "next": 1}
a = sys.argv[1:]
c = a[0]
def arg(name): return a[a.index(name) + 1]
if c == "-V": print("tmux test")
elif c == "list-panes":
    if not s["session"]:
        print("no server running", file=sys.stderr); sys.exit(1)
    for name, pane in s["panes"].items(): print(name + "\t" + pane + "\t0")
elif c == "has-session": sys.exit(0 if s["session"] else 1)
elif c == "new-session": s["session"] = True
elif c == "new-window":
    pane = "%" + str(s["next"]); s["next"] += 1
    s["panes"][arg("-n")] = pane; s["last_command"] = a[-1]; print(pane)
elif c == "kill-pane":
    s["panes"] = {k:v for k,v in s["panes"].items() if v != arg("-t")}
elif c == "load-buffer": s["buffer"] = sys.stdin.read()
elif c == "capture-pane": print(s.get("buffer", "Worker idle"))
elif c in ("set-option", "pipe-pane", "paste-buffer", "send-keys", "delete-buffer"): pass
else: print("Unhandled fake tmux: " + repr(a), file=sys.stderr); sys.exit(1)
p.write_text(json.dumps(s))
'''

FAKE_WORKER = r'''#!/usr/bin/env python3
import sys
print("FAKE_WORKER_READY", flush=True)
for line in sys.stdin:
    print("RECEIVED " + line.strip(), flush=True)
'''


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="manager-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "repo with spaces"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Runtime Test")
        self.git("config", "user.email", "runtime@example.invalid")
        (self.root / "base.txt").write_text("original\n")
        self.git("add", "base.txt")
        self.git("commit", "-qm", "Initial fixture")
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ)
        self.env.pop("MANAGER_WORKER_TASK", None)
        self.env.pop("MANAGER_WORKER_ATTEMPT", None)
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        self.env["TEST_TMUX_STATE"] = str(self.directory / "tmux.json")
        for name in ("codex", "claude"):
            self.executable(name, FAKE_WORKER)
        if USE_REAL:
            if not REAL_TMUX:
                self.skipTest("tmux is not installed")
            self.socket = str(self.directory / "tmux.sock")
            self.executable("tmux", "#!/bin/sh\nexec " + shlex.quote(REAL_TMUX) +
                            " -S " + shlex.quote(self.socket) + ' "$@"\n')
            self.addCleanup(lambda: subprocess.run([REAL_TMUX, "-S", self.socket, "kill-server"],
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        else:
            self.executable("tmux", FAKE_TMUX)
        self.brief = self.directory / "brief.md"
        self.brief.write_text("Implement the fixture change in base.txt; preserve other files.\n")
        self.review = self.directory / "review.md"
        self.review.write_text("Manager independently inspected the diff and fixture behavior.\n")
        self.call("init")

    def executable(self, name, content):
        path = self.bin / name
        path.write_text(content.replace("#!/usr/bin/env python3", "#!" + sys.executable))
        path.chmod(0o755)

    def git(self, *args, root=None):
        return subprocess.run(["git", "-C", str(root or self.root), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

    def call(self, *args, ok=True, env=None):
        result = subprocess.run([sys.executable, str(CLI), "--root", str(self.root), *args],
                                env=env or self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            value = json.loads(result.stdout)
        except ValueError:
            self.fail(result.stderr.decode() + result.stdout.decode())
        if ok:
            self.assertEqual(result.returncode, 0, value)
        else:
            self.assertNotEqual(result.returncode, 0, value)
        return value

    def spawn(self, identity="T001", **options):
        args = ["spawn", "--id", identity, "--title", "Fixture", "--brief", str(self.brief)]
        for key, value in options.items():
            args.extend(["--" + key.replace("_", "-"), str(value)])
        return self.call(*args)

    def worker_done(self, identity="T001", attempt=1):
        (self.root / ".manager/tasks" / identity / "result.md").write_text("Fixture deliverable and evidence.\n")
        return self.call("report", identity, "--attempt", str(attempt), "--state", "done", "--summary", "Delivered")

    def verify(self, identity="T001", command="test -f base.txt", ok=True, **kwargs):
        args = ["verify", identity, "--review", str(self.review), "--command", command]
        for key, value in kwargs.items():
            args.extend(["--" + key, str(value)])
        return self.call(*args, ok=ok)

    def state(self, identity="T001"):
        return next(t for t in self.call("status")["tasks"] if t["task_id"] == identity)

    def test_init_is_idempotent_and_preserves_user_files(self):
        self.assertFalse(self.call("init")["initialized"])
        self.assertEqual((self.root / "base.txt").read_text(), "original\n")
        self.assertEqual((self.root / ".gitignore").read_text().count("/.manager/"), 1)
        self.assertEqual(self.git("check-ignore", ".manager/state.json"), ".manager/state.json")

    def test_worker_done_requires_manager_verification(self):
        task = self.spawn()
        (Path(task["worktree"]) / "base.txt").write_text("worker edit\n")
        self.assertEqual((self.root / "base.txt").read_text(), "original\n")
        self.worker_done()
        self.assertEqual(self.state()["state"], "verification")
        self.call("accept", "T001", ok=False)
        self.assertTrue(self.verify()["passed"])
        self.assertEqual(self.call("accept", "T001")["state"], "done")
        self.assertFalse(self.state()["alive"])
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "late", ok=False)

    def test_completion_requires_result_and_incomplete_work_cannot_verify(self):
        self.spawn()
        self.call("report", "T001", "--attempt", "1", "--state", "done", "--summary", "Claim", ok=False)
        self.call("report", "T001", "--attempt", "1", "--state", "verification", "--summary", "Testing")
        self.verify(ok=False)

    def test_questions_escalation_and_acknowledged_correction(self):
        self.spawn()
        self.call("report", "T001", "--attempt", "1", "--state", "needs_manager", "--summary", "Question", ok=False)
        self.call("report", "T001", "--attempt", "1", "--state", "needs_manager", "--summary", "Question",
                  "--question", "Which product behavior?", "--question-type", "product")
        self.assertEqual(self.call("escalate", "T001", "--reason", "Need product choice")["state"], "needs_user")
        self.assertEqual(self.state()["state"], "needs_user")
        sent = self.call("send", "T001", "Use established behavior", "--inbox-only")
        self.assertFalse(self.call("inbox", "T001")[0]["acknowledged"])
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "Resolved",
                  "--ack", sent["message_id"])
        self.assertTrue(self.call("inbox", "T001")[0]["acknowledged"])
        self.assertEqual(self.state()["state"], "working")

    def test_failed_checks_and_post_verify_changes_block_acceptance(self):
        item = self.spawn()
        self.worker_done()
        self.assertFalse(self.verify(command="exit 7", ok=False)["passed"])
        self.call("accept", "T001", ok=False)
        self.verify()
        (Path(item["worktree"]) / "untracked.txt").write_text("new behavior")
        self.call("accept", "T001", ok=False)
        self.assertIsNone(self.state()["verification"])

    def test_content_changes_during_checks_fail(self):
        self.spawn()
        self.worker_done()
        record = self.verify(command="echo mutation >> base.txt", ok=False)
        self.assertFalse(record["unchanged"])
        self.assertEqual(record["checks"][0]["exit_code"], 0)

    def test_staged_content_and_review_changes_invalidate_evidence(self):
        item = self.spawn()
        tree = Path(item["worktree"])
        # The index changes while the working file stays the same; status is still M.
        (tree / "base.txt").write_text("index version one\n")
        self.git("add", "base.txt", root=tree)
        (tree / "base.txt").write_text("original\n")
        self.worker_done()
        self.verify()
        (tree / "base.txt").write_text("index version two\n")
        self.git("add", "base.txt", root=tree)
        (tree / "base.txt").write_text("original\n")
        self.call("accept", "T001", ok=False)
        record = self.verify()
        (self.root / ".manager" / record["review"]).write_text("Changed review")
        self.call("accept", "T001", ok=False)

    def test_failed_live_worker_can_receive_a_correction(self):
        self.spawn()
        self.call("report", "T001", "--attempt", "1", "--state", "failed", "--summary", "Check failed")
        self.assertEqual(self.state()["state"], "failed")
        self.call("send", "T001", "Fix the diagnosed failure", "--inbox-only")
        self.assertEqual(self.state()["state"], "working")
        self.worker_done()
        self.verify()
        self.call("accept", "T001")

    def test_stale_and_orphan_artifacts_are_preserved(self):
        self.spawn()
        report_path = self.root / ".manager/tasks/T001/status.json"
        report = json.loads(report_path.read_text())
        report["updated_at"] = "2000-01-01T00:00:00+00:00"
        report_path.write_text(json.dumps(report))
        orphan = self.root / ".manager/tasks/ORPHAN"
        orphan.mkdir()
        marker = orphan / "result.md"
        marker.write_text("preserve")
        result = self.call("reconcile")
        self.assertEqual(result["notices"][0]["issue"], "stale_report")
        self.assertIn(str(orphan.resolve()), result["orphan_tasks"])
        self.assertEqual(marker.read_text(), "preserve")
        self.assertEqual(self.state()["state"], "working")

    def test_yaml_configuration_or_explicit_missing_dependency_error(self):
        (self.root / ".manager.yml").write_text("manager:\n  max_workers: 1\nagents:\n  research: claude\n")
        try:
            import yaml
        except ImportError:
            value = self.call("status", ok=False)
            self.assertIn("requires PyYAML", value["error"])
        else:
            self.assertEqual(self.spawn(kind="research")["agent"], "claude")
            self.call("spawn", "--id", "T002", "--title", "Limit", "--brief", str(self.brief), ok=False)

    def test_verify_timeout_preserves_failure_evidence(self):
        self.spawn()
        self.worker_done()
        record = self.verify(command="sleep 10", timeout=1, ok=False)
        self.assertTrue(record["checks"][0]["timed_out"])
        self.assertEqual(record["checks"][0]["exit_code"], 124)

    def test_corrections_invalidate_prior_verification(self):
        self.spawn()
        self.worker_done()
        self.verify()
        self.call("send", "T001", "Add missing case", "--inbox-only")
        self.assertIsNone(self.state()["verification"])
        self.assertEqual(self.state()["state"], "working")
        self.call("accept", "T001", ok=False)

    def test_dependencies_and_committed_base_are_explicit(self):
        first = self.spawn()
        self.call("task", "--id", "T002", "--title", "Dependent", "--brief", str(self.brief), "--depends-on", "T001")
        self.call("spawn", "--id", "T002", ok=False)
        self.worker_done()
        self.verify()
        self.call("accept", "T001")
        second = self.call("spawn", "--id", "T002")
        self.assertEqual(first["base"], second["base"])
        self.assertEqual(self.state("T002")["state"], "working")
        self.call("task", "--id", "T003", "--title", "Bad", "--brief", str(self.brief), "--depends-on", "UNKNOWN", ok=False)

    def test_concurrency_config_and_provider_routing(self):
        (self.root / ".manager.yml").write_text(json.dumps({"manager": {"max_workers": 1},
                                                           "agents": {"research": "claude"}}))
        item = self.spawn(kind="research")
        self.assertEqual(item["agent"], "claude")
        self.call("spawn", "--id", "T002", "--title", "Second", "--brief", str(self.brief), ok=False)
        self.call("stop", "T001")
        self.assertEqual(self.call("spawn", "--id", "T002")["state"], "working")
        (self.root / ".manager.yml").write_text(json.dumps({"git": {"auto_push": True}}))
        self.call("status", ok=False)

    def test_retry_preserves_work_and_rejects_old_generations(self):
        item = self.spawn()
        (Path(item["worktree"]) / "retained.txt").write_text("keep me")
        self.call("stop", "T001")
        retry = self.call("retry", "T001", "--agent", "claude")
        self.assertEqual(retry["attempt"], 2)
        self.assertEqual(retry["agent"], "claude")
        self.assertEqual((Path(retry["worktree"]) / "retained.txt").read_text(), "keep me")
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "Old", ok=False)
        self.call("stop", "T001")
        self.call("retry", "T001")
        self.call("stop", "T001")
        self.call("retry", "T001", ok=False)

    def test_reconcile_recovers_pane_and_detects_missing_worker(self):
        self.spawn()
        state_path = self.root / ".manager/state.json"
        value = json.loads(state_path.read_text())
        pane = value["tasks"]["T001"]["pane"]
        value["tasks"]["T001"]["pane"] = None
        state_path.write_text(json.dumps(value))
        self.assertEqual(self.state()["pane"], pane)
        subprocess.run([str(self.bin / "tmux"), "kill-pane", "-t", pane], env=self.env, check=True)
        self.assertEqual(self.state()["state"], "failed")
        sent = self.call("send", "T001", "Diagnosis retained")
        self.assertIsNotNone(sent["delivery_error"])
        self.assertEqual(len(self.call("inbox", "T001")), 1)

    def test_corrupt_report_and_changed_branch_cannot_accept(self):
        item = self.spawn()
        self.worker_done()
        self.verify()
        (self.root / ".manager/tasks/T001/status.json").write_text("{broken")
        self.call("accept", "T001", ok=False)
        self.assertIsNotNone(self.state()["report_error"])
        # A separate task keeps report corruption distinct from a changed Git identity.
        other = self.spawn("T002")
        self.worker_done("T002")
        self.git("checkout", "-qb", "different-branch", root=Path(other["worktree"]))
        self.verify("T002", ok=False)
        self.assertFalse(self.state("T002")["worktree_valid"])

    def test_missing_completion_artifact_and_corrupt_registry_fail_explicitly(self):
        self.spawn()
        self.worker_done()
        (self.root / ".manager/tasks/T001/result.md").unlink()
        self.verify(ok=False)
        self.assertIsNotNone(self.state()["report_error"])
        path = self.root / ".manager/state.json"
        state = json.loads(path.read_text())
        del state["tasks"]["T001"]["dependencies"]
        path.write_text(json.dumps(state))
        self.assertIn("Invalid persisted task metadata", self.call("status", ok=False)["error"])

    def test_worker_environment_prevents_recursive_manager_commands(self):
        self.spawn()
        env = dict(self.env, MANAGER_WORKER_TASK="T001", MANAGER_WORKER_ATTEMPT="1")
        self.call("init", env=env, ok=False)
        self.call("report", "T001", "--attempt", "2", "--state", "working", "--summary", "Wrong", env=env, ok=False)
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "Allowed", env=env)

    def test_terminal_messages_preserve_shell_metacharacters(self):
        self.spawn()
        message = "Review `literal` and $(literal); 'quotes'\nSecond line"
        sent = self.call("send", "T001", message)
        self.assertEqual(sent["delivery"], "pasted_unacknowledged")
        self.assertEqual(self.call("inbox", "T001")[0]["text"], message)
        self.call("peek", "T001")

    def test_invalid_ids_and_state_reinitialization_are_rejected(self):
        result = subprocess.run([sys.executable, str(CLI), "--root", str(self.root), "task", "--id", "../escape"],
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        state_path = self.root / ".manager/state.json"
        state_path.write_text("corrupt")
        self.call("init", ok=False)
        self.assertEqual(state_path.read_text(), "corrupt")

    @unittest.skipUnless(USE_REAL, "requires MANAGER_TEST_REAL_TMUX=1")
    def test_real_interactive_worker_receives_message(self):
        import time
        self.spawn()
        deadline = time.monotonic() + 5
        while "FAKE_WORKER_READY" not in self.call("peek", "T001")["output"]:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        self.call("send", "T001", "interactive delivery fixture")
        while "RECEIVED Manager message" not in self.call("peek", "T001")["output"]:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
