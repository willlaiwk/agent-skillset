#!/usr/bin/env python3
"""Behavioral tests with real Git repos and fake providers; no model/API calls.

Default: deterministic fake tmux. MANAGER_TEST_REAL_TMUX=1: real isolated tmux
server with the same fake providers, exercising interactive lifecycle and paste.
"""
import argparse
import contextlib
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

CLI = Path(__file__).resolve().with_name("manager")
REAL_TMUX = shutil.which("tmux")
USE_REAL = os.environ.get("MANAGER_TEST_REAL_TMUX") == "1"

FAKE_TMUX = r'''#!/usr/bin/env python3
import fcntl, json, os, sys
from pathlib import Path
p = Path(os.environ["TEST_TMUX_STATE"])
stream = p.with_suffix(".lock").open("a")
fcntl.flock(stream, fcntl.LOCK_EX)
s = json.loads(p.read_text()) if p.exists() else {"sessions": {}, "next": 1, "buffers": {}}
a = sys.argv[1:]
c = a[0]
def arg(name): return a[a.index(name) + 1]
def target(): return arg("-t").rstrip(":")
def session():
    value = s["sessions"].get(target())
    if value is None:
        print("can't find session", file=sys.stderr); sys.exit(1)
    return value
if c == "-V": print("tmux test")
elif c == "list-panes":
    for name, pane in session()["panes"].items(): print(name + "\t" + pane + "\t0")
elif c == "has-session": sys.exit(0 if target() in s["sessions"] else 1)
elif c == "new-session": s["sessions"][arg("-s")] = {"panes": {}, "options": {}}
elif c == "new-window":
    pane = "%" + str(s["next"]); s["next"] += 1
    session()["panes"][arg("-n")] = pane
    session()["last_command"] = a[-1]; print(pane)
elif c == "kill-pane":
    for value in s["sessions"].values():
        value["panes"] = {k:v for k,v in value["panes"].items() if v != arg("-t")}
elif c == "set-option": session()["options"][a[-2]] = a[-1]
elif c == "show-options": print(session()["options"].get(a[-1], ""))
elif c == "load-buffer": s["buffers"][arg("-b")] = sys.stdin.read()
elif c == "paste-buffer": s["buffer"] = s["buffers"][arg("-b")]
elif c == "capture-pane": print(s.get("buffer", "Worker idle"))
elif c == "delete-buffer": s["buffers"].pop(arg("-b"), None)
elif c in ("pipe-pane", "send-keys"): pass
else: print("Unhandled fake tmux: " + repr(a), file=sys.stderr); sys.exit(1)
p.write_text(json.dumps(s))
'''

FAKE_WORKER = r'''#!/usr/bin/env python3
import hashlib, os, sys
print("FAKE_WORKER_READY", flush=True)
print("WORKER_OWNER " + ("set" if os.environ.get("MANAGER_OWNER_FILE") else "unset"), flush=True)
print("WORKER_ROUTE " + " ".join([hashlib.sha256(os.environ.get("MANAGER_WORKER_ROOT", "").encode()).hexdigest()[:12]] + [os.environ.get(k, "") for k in ("MANAGER_WORKER_MANAGER", "MANAGER_WORKER_TASK", "MANAGER_WORKER_ATTEMPT", "MANAGER_WORKER_ASSIGNMENT")]), flush=True)
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
        self.root = self.root.resolve()
        self.git("init", "-q")
        self.git("config", "user.name", "Runtime Test")
        self.git("config", "user.email", "runtime@example.invalid")
        (self.root / "base.txt").write_text("original\n")
        self.git("add", "base.txt")
        self.git("commit", "-qm", "Initial fixture")
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ)
        for key in ("MANAGER_WORKER_ROOT", "MANAGER_WORKER_MANAGER", "MANAGER_WORKER_TASK",
                    "MANAGER_WORKER_ATTEMPT", "MANAGER_WORKER_ASSIGNMENT", "MANAGER_OWNER_FILE"):
            self.env.pop(key, None)
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
        self.credentials = {}
        self.home = self.root / ".manager" / "alpha"
        self.create_manager("alpha")

    def executable(self, name, content):
        path = self.bin / name
        path.write_text(content.replace("#!/usr/bin/env python3", "#!" + sys.executable))
        path.chmod(0o755)

    def git(self, *args, root=None):
        return subprocess.run(["git", "-C", str(root or self.root), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

    def create_manager(self, identity):
        self.call("init", manager=identity, owner=False)
        credential = self.directory / (identity + ".owner.json")
        self.call("owner", "claim", "--session-id", "test-" + identity,
                  "--credential-file", str(credential), manager=identity, owner=False)
        self.credentials[identity] = credential

    def call(self, *args, ok=True, env=None, manager="alpha", owner=True, root=None, assignment=True):
        environment = env or self.env
        prefix = [sys.executable, str(CLI), "--root", str(root or self.root)]
        if manager is not None:
            prefix += ["--manager-id", manager]
        if owner and manager in self.credentials:
            prefix += ["--owner-file", str(self.credentials[manager])]
        args = list(args)
        if args[0] == "report" and assignment and "--assignment-id" not in args and not environment.get("MANAGER_WORKER_ASSIGNMENT"):
            path = (root or self.root) / ".manager" / manager / "tasks" / args[1] / "assignment.json"
            if path.exists():
                args += ["--assignment-id", json.loads(path.read_text())["assignment_id"]]
        result = subprocess.run(prefix + args, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            value = json.loads(result.stdout)
        except ValueError:
            self.fail(result.stderr.decode() + result.stdout.decode())
        if ok:
            self.assertEqual(result.returncode, 0, value)
        else:
            self.assertNotEqual(result.returncode, 0, value)
        return value

    def worker_env(self, manager, task):
        assignment = json.loads((self.root / ".manager" / manager / "tasks" / task / "assignment.json").read_text())
        return dict(self.env, MANAGER_WORKER_ROOT=str(self.root), MANAGER_WORKER_MANAGER=manager,
                    MANAGER_WORKER_TASK=task, MANAGER_WORKER_ATTEMPT=str(assignment["attempt"]),
                    MANAGER_WORKER_ASSIGNMENT=assignment["assignment_id"])

    def spawn(self, identity="T001", manager="alpha", **options):
        args = ["spawn", "--id", identity, "--title", "Fixture", "--brief", str(self.brief)]
        for key, value in options.items():
            args.extend(["--" + key.replace("_", "-"), str(value)])
        return self.call(*args, manager=manager)

    def worker_done(self, identity="T001", attempt=1, manager="alpha"):
        (self.root / ".manager" / manager / "tasks" / identity / "result.md").write_text("Fixture deliverable and evidence.\n")
        return self.call("report", identity, "--attempt", str(attempt), "--state", "done", "--summary", "Delivered", manager=manager)

    def verify(self, identity="T001", command="test -f base.txt", ok=True, manager="alpha", **kwargs):
        args = ["verify", identity, "--review", str(self.review), "--command", command]
        for key, value in kwargs.items():
            args.extend(["--" + key, str(value)])
        return self.call(*args, ok=ok, manager=manager)

    def state(self, identity="T001", manager="alpha"):
        return next(t for t in self.call("reconcile", manager=manager)["tasks"] if t["task_id"] == identity)

    def test_init_is_idempotent_and_preserves_user_files(self):
        self.assertFalse(self.call("init")["initialized"])
        self.assertEqual((self.root / "base.txt").read_text(), "original\n")
        self.assertFalse((self.root / ".gitignore").exists())
        self.assertEqual(self.git("check-ignore", ".manager/alpha/state.json"), ".manager/alpha/state.json")

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
        (self.home / record["review"]).write_text("Changed review")
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
        report_path = self.home / "tasks/T001/status.json"
        report = json.loads(report_path.read_text())
        report["updated_at"] = "2000-01-01T00:00:00+00:00"
        report_path.write_text(json.dumps(report))
        orphan = self.home / "tasks/ORPHAN"
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
        state_path = self.home / "state.json"
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
        (self.home / "tasks/T001/status.json").write_text("{broken")
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
        (self.home / "tasks/T001/result.md").unlink()
        self.verify(ok=False)
        self.assertIsNotNone(self.state()["report_error"])
        path = self.home / "state.json"
        state = json.loads(path.read_text())
        del state["tasks"]["T001"]["dependencies"]
        path.write_text(json.dumps(state))
        self.assertIn("Invalid persisted task metadata", self.call("status", ok=False)["error"])

    def test_worker_environment_prevents_recursive_manager_commands(self):
        self.spawn()
        env = self.worker_env("alpha", "T001")
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
        state_path = self.home / "state.json"
        state_path.write_text("corrupt")
        self.call("init", ok=False)
        self.assertEqual(state_path.read_text(), "corrupt")

    def snapshot(self, directory):
        result = {}
        for path in directory.rglob("*"):
            # A live worker can append diagnostics during inspection; those are not registry writes.
            if path.is_file() and path.name != "log.txt":
                result[str(path.relative_to(directory))] = (path.read_bytes(), path.stat().st_mtime_ns)
        return result

    def test_parallel_initialization_isolated_ids_and_shared_exclude(self):
        from concurrent.futures import ThreadPoolExecutor
        (self.root / ".gitignore").write_text("# user-owned dirty file\n")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.call("init", manager=None, owner=False), range(4)))
        ids = {r["manager_id"] for r in results}
        self.assertEqual(len(ids), 4)
        for result in results:
            self.assertTrue(result["initialized"])
            self.assertEqual(result["owner"]["state"], "released")
            self.assertEqual(result["owner"]["generation"], 0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            same = list(pool.map(lambda _: self.call("init", manager="shared", owner=False), range(2)))
        self.assertEqual(sorted(r["initialized"] for r in same), [False, True])
        self.assertEqual((self.root / ".gitignore").read_text(), "# user-owned dirty file\n")
        self.assertEqual((self.root / ".git/info/exclude").read_text().splitlines().count("/.manager/"), 1)
        listed = self.call("managers", manager=None, owner=False)
        self.assertEqual(len(listed["managers"]), 6)
        self.assertEqual(listed["capacity_scope"], "per-manager")

    def test_resume_preserves_plan_attempt_and_owner_without_reconcile(self):
        self.spawn()
        self.call("report", "T001", "--attempt", "1", "--state", "needs_manager",
                  "--summary", "Question", "--question", "Which case?")
        (self.home / "plan.md").write_text("retain decisions\n")
        before = self.snapshot(self.home)
        result = self.call("init")
        self.assertFalse(result["initialized"])
        self.assertEqual(self.snapshot(self.home), before)
        self.assertEqual(json.loads((self.home / "state.json").read_text())["tasks"]["T001"]["state"], "working")

    def test_missing_selector_never_guesses_or_creates_manager(self):
        before = self.snapshot(self.root / ".manager")
        for args in [("status",), ("reconcile",), ("inbox", "T001"),
                     ("task", "--id", "T001", "--title", "X", "--brief", str(self.brief)),
                     ("report", "T001", "--attempt", "1", "--state", "working", "--summary", "X")]:
            value = self.call(*args, manager=None, owner=False, assignment=False, ok=False)
            self.assertIn("--manager-id is required", value["error"])
        self.assertEqual(self.snapshot(self.root / ".manager"), before)

    def test_read_commands_preserve_files_and_separate_observation(self):
        self.spawn()
        self.worker_done()
        before = self.snapshot(self.home)
        index = (self.root / ".git/index").read_bytes()
        exclude = (self.root / ".git/info/exclude").read_bytes()
        status = self.call("status", owner=False)
        self.assertEqual(status["tasks"][0]["state"], "working")
        self.assertEqual(status["observed"]["tasks"][0]["state"], "verification")
        self.call("peek", "T001", owner=False)
        self.call("events", owner=False)
        self.call("inbox", "T001", owner=False)
        self.call("owner", "status", owner=False)
        self.call("managers", manager=None, owner=False)
        self.assertEqual(self.snapshot(self.home), before)
        self.assertEqual((self.root / ".git/index").read_bytes(), index)
        self.assertEqual((self.root / ".git/info/exclude").read_bytes(), exclude)
        self.assertEqual(self.state()["state"], "verification")

    def test_same_task_names_route_independently_through_lifecycle(self):
        self.create_manager("beta")
        (self.root / ".manager.yml").write_text(json.dumps({"manager": {"max_workers": 1}}))
        a, b = self.spawn(), self.spawn(manager="beta")
        self.assertNotEqual(a["branch"], b["branch"])
        self.assertNotEqual(a["worktree"], b["worktree"])
        self.assertNotEqual(a["assignment_id"], b["assignment_id"])
        other_home = self.root / ".manager/beta"
        before = self.snapshot(other_home)
        sent = self.call("send", "T001", "Only alpha", "--inbox-only")
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "Ack", "--ack", sent["message_id"])
        self.call("stop", "T001")
        retried = self.call("retry", "T001")
        self.assertEqual(retried["attempt"], 2)
        self.worker_done(attempt=2)
        self.verify()
        self.call("accept", "T001")
        result = self.call("reconcile")
        self.assertNotIn(b["worktree"], result["orphan_worktrees"])
        self.assertEqual(self.snapshot(other_home), before)
        self.assertTrue(self.call("status", manager="beta")["observed"]["tasks"][0]["alive"])
        self.assertEqual(self.call("status")["worker_capacity"]["max_workers"], 1)
        self.assertEqual(self.call("status", manager="beta")["worker_capacity"]["active"], 1)

    def test_cross_manager_report_ack_and_worker_inbox_are_rejected(self):
        self.create_manager("beta")
        a, b = self.spawn(), self.spawn(manager="beta")
        env = self.worker_env("alpha", "T001")
        before = self.snapshot(self.root / ".manager/beta")
        self.call("report", "T001", "--attempt", "1", "--assignment-id", a["assignment_id"],
                  "--state", "working", "--summary", "Wrong route", manager="beta", owner=False, ok=False)
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "Wrong environment",
                  manager="beta", env=env, owner=False, ok=False)
        self.call("inbox", "T001", manager="beta", env=env, owner=False, ok=False)
        self.assertEqual(self.snapshot(self.root / ".manager/beta"), before)
        sent = self.call("send", "T001", "For alpha", "--inbox-only")
        copied = self.root / ".manager/beta/inbox/T001" / (sent["message_id"] + ".json")
        copied.write_bytes((self.home / "inbox/T001" / copied.name).read_bytes())
        before_report = (self.root / ".manager/beta/tasks/T001/status.json").read_bytes()
        self.call("report", "T001", "--attempt", "1", "--assignment-id", b["assignment_id"], "--state", "working",
                  "--summary", "Wrong ack", "--ack", sent["message_id"], manager="beta", ok=False)
        self.assertEqual((self.root / ".manager/beta/tasks/T001/status.json").read_bytes(), before_report)
        self.call("inbox", "T001", manager="beta", ok=False)

    def test_retry_keeps_ack_history_and_rejects_old_assignment(self):
        original = self.spawn()
        message = self.call("send", "T001", "First attempt", "--inbox-only")
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "Received", "--ack", message["message_id"])
        env = self.worker_env("alpha", "T001")
        self.call("stop", "T001")
        retried = self.call("retry", "T001")
        self.assertNotEqual(original["assignment_id"], retried["assignment_id"])
        self.call("report", "T001", "--attempt", "2", "--assignment-id", original["assignment_id"],
                  "--state", "working", "--summary", "Old assignment", ok=False)
        self.call("report", "T001", "--attempt", "2", "--state", "working", "--summary", "Old ack",
                  "--ack", message["message_id"], ok=False)
        self.call("inbox", "T001", env=env, owner=False, ok=False)
        inbox = self.call("inbox", "T001")
        self.assertFalse(inbox[0]["current_attempt"])
        self.assertTrue(inbox[0]["acknowledged"])
        self.assertEqual(json.loads((self.home / "tasks/T001/status.json").read_text())["acks"], [])

    def test_assignment_required_and_launch_environment_excludes_owner(self):
        self.env["MANAGER_OWNER_FILE"] = str(self.credentials["alpha"])
        item = self.spawn()
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "Missing ID", assignment=False, ok=False)
        env = self.worker_env("alpha", "T001")
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "Environment ID", env=env, owner=False)
        self.call("report", "T001", "--attempt", "1", "--assignment-id", "0" * 32,
                  "--state", "working", "--summary", "Conflicting ID", env=env, owner=False, ok=False)
        if not USE_REAL:
            tmux = json.loads((self.directory / "tmux.json").read_text())
            launch = next(iter(tmux["sessions"].values()))["last_command"]
            self.assertIn("-u MANAGER_OWNER_FILE", launch)
            self.assertNotIn(str(self.credentials["alpha"]), launch)
            self.assertIn(item["assignment_id"], launch)
        else:
            import time
            deadline = time.monotonic() + 5
            while True:
                output = self.call("peek", "T001")["output"]
                lines = [line for line in output.splitlines() if line.startswith("WORKER_ROUTE ")]
                if lines and "WORKER_OWNER unset" in output:
                    route = lines[0].split(" ")[1:]
                    break
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.05)
            self.assertEqual(route, [hashlib.sha256(str(self.root).encode()).hexdigest()[:12],
                                     "alpha", "T001", "1", item["assignment_id"]])

    def test_foreign_or_unmarked_tmux_session_is_not_adopted(self):
        self.spawn()
        session = json.loads((self.home / "state.json").read_text())["session"]
        subprocess.run([str(self.bin / "tmux"), "set-option", "-t", session, "@manager_id", "foreign"], env=self.env, check=True)
        before = self.snapshot(self.home)
        self.call("reconcile", ok=False)
        self.call("peek", "T001", ok=False)
        self.call("stop", "T001", ok=False)
        # stop must validate identity before writing its marker.
        self.assertEqual(self.snapshot(self.home), before)

    def test_invalid_namespace_state_symlinks_and_legacy_preserve_data(self):
        before = self.snapshot(self.root / ".manager")
        for identity in ("../escape", "Upper", "tasks", "", "a" * 65):
            result = subprocess.run([sys.executable, str(CLI), "--root", str(self.root), "--manager-id", identity, "init"],
                                    env=self.env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(self.root / ".manager"), before)
        destination = self.root / ".manager/linked"
        destination.symlink_to(self.home, target_is_directory=True)
        self.call("init", manager="linked", ok=False)
        self.assertEqual(self.snapshot(self.home), {k.split("alpha/", 1)[1]: v for k, v in before.items() if k.startswith("alpha/")})
        destination.unlink()
        marker = self.root / ".manager/state.json"
        marker.write_text(json.dumps({"version": 1, "root": str(self.root), "tasks": {}}))
        legacy_before = self.snapshot(self.root / ".manager")
        self.assertIn("migrate", self.call("init", manager="legacy", ok=False)["error"])
        self.assertEqual(self.snapshot(self.root / ".manager"), legacy_before)
        marker.unlink()
        state_path = self.home / "state.json"
        original = json.loads(state_path.read_text())
        for patch in ({"manager_id": "foreign"}, {"version": 99}, {"version": 2.0}):
            state = {**original, **patch}
            state_path.write_text(json.dumps(state))
            content = state_path.read_bytes()
            self.call("init", ok=False)
            self.call("status", ok=False)
            self.assertEqual(state_path.read_bytes(), content)
            listed = self.call("managers", manager=None, owner=False)
            self.assertIn("error", listed["managers"][0])

    def test_owner_claim_is_explicit_and_does_not_leak_credential(self):
        initialized = self.call("init", manager="fresh", owner=False)
        self.assertEqual(initialized["owner"]["state"], "released")
        self.call("task", "--id", "T001", "--title", "X", "--brief", str(self.brief), manager="fresh", owner=False, ok=False)
        credential = self.directory / "fresh.owner.json"
        claim = self.call("owner", "claim", "--session-id", "fresh-session", "--credential-file", str(credential), manager="fresh", owner=False)
        token = json.loads(credential.read_text())["token"]
        self.assertEqual(credential.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(token, json.dumps(claim))
        self.assertNotIn(token, json.dumps(self.call("events", manager="fresh", owner=False)))
        self.call("owner", "claim", "--session-id", "another", "--credential-file", str(self.directory / "another.owner.json"), manager="fresh", owner=False, ok=False)
        self.assertFalse((self.directory / "another.owner.json").exists())
        # The alpha credential cannot authorize a write to fresh.
        env = dict(self.env, MANAGER_OWNER_FILE=str(self.credentials["alpha"]))
        self.assertFalse(self.call("owner", "status", manager="fresh", owner=False, env=env)["credential_valid"])
        self.call("task", "--id", "T001", "--title", "X", "--brief", str(self.brief), manager="fresh", owner=False, env=env, ok=False)

    def test_readonly_inventory_without_runtime_and_corrupt_entries(self):
        checkout = self.directory / "another-checkout"
        self.git("worktree", "add", "-qb", "another-checkout", str(checkout))
        self.assertEqual(self.call("managers", root=checkout, manager=None, owner=False)["managers"], [])
        self.assertFalse((checkout / ".manager").exists())
        self.call("status", root=checkout, manager="missing", owner=False, ok=False)
        self.assertFalse((checkout / ".manager").exists())
        broken = self.root / ".manager/broken"
        broken.symlink_to(self.directory / "missing", target_is_directory=True)
        listed = self.call("managers", manager=None, owner=False)
        entries = {r["manager_id"]: r for r in listed["managers"]}
        self.assertIn("error", entries["broken"])
        self.assertEqual(entries["alpha"]["version"], 2)

    def test_unsafe_control_paths_and_corrupt_assignment_do_not_escape_namespace(self):
        self.spawn()
        report_path = self.home / "tasks/T001/status.json"
        outside = self.directory / "outside.json"
        outside.write_bytes(report_path.read_bytes())
        report_path.unlink()
        report_path.symlink_to(outside)
        before = outside.read_bytes()
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "Escape", ok=False)
        self.assertEqual(outside.read_bytes(), before)
        report_path.unlink()
        report_path.write_bytes(before)
        assignment_path = self.home / "tasks/T001/assignment.json"
        assignment = json.loads(assignment_path.read_text())
        assignment["manager_id"] = "foreign"
        assignment_path.write_text(json.dumps(assignment))
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "Corrupt assignment", ok=False)
        self.assertEqual(report_path.read_bytes(), before)
        # A symlink shared exclude must be rejected before initializing another namespace.
        exclude = self.root / ".git/info/exclude"
        outside_exclude = self.directory / "outside-exclude"
        exclude_before = exclude.read_bytes()
        outside_exclude.write_bytes(exclude_before)
        exclude.unlink()
        exclude.symlink_to(outside_exclude)
        self.call("init", manager="unsafe-exclude", owner=False, ok=False)
        self.assertFalse((self.root / ".manager/unsafe-exclude").exists())
        self.assertEqual(outside_exclude.read_bytes(), exclude_before)

    def takeover(self, generation=None, reason="Explicit fixture handoff", manager="alpha"):
        if generation is None:
            generation = self.call("owner", "status", manager=manager)["generation"]
        credential = self.directory / ("takeover-" + str(generation) + ".json")
        result = self.call("owner", "takeover", "--expect-generation", str(generation),
                           "--reason", reason, "--session-id", "successor",
                           "--credential-file", str(credential), owner=False, manager=manager)
        self.credentials[manager] = credential
        return result

    def start_verify(self, action=None, manager="alpha"):
        started, finish = self.directory / "started", self.directory / "finish"
        code = ("from pathlib import Path; import time, os; "
                "assert 'MANAGER_OWNER_FILE' not in os.environ; "
                "Path(" + repr(str(started)) + ").write_text('ready'); "
                "deadline=time.monotonic()+30\n"
                "while not Path(" + repr(str(finish)) + ").exists():\n"
                " assert time.monotonic()<deadline; time.sleep(.02)\n")
        command = shlex.join([sys.executable, "-c", code])
        process = subprocess.Popen([sys.executable, str(CLI), "--root", str(self.root),
                                   "--manager-id", manager, "--owner-file", str(self.credentials[manager]),
                                   *(action or ["verify", "T001"]), "--review", str(self.review), "--command", command],
                                  env=dict(self.env, MANAGER_OWNER_FILE=str(self.credentials[manager])),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            finish.touch()
            if process.poll() is None:
                process.communicate(timeout=20)
        self.addCleanup(cleanup)
        deadline = time.monotonic() + 8
        while not started.exists():
            self.assertIsNone(process.poll(), "Verification exited before entering checks")
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)
        return process, finish

    def finish_verify(self, process, finish, passed):
        finish.touch()
        output, error = process.communicate(timeout=10)
        value = json.loads(output)
        self.assertEqual(process.returncode, 0 if passed else 1, (value, error))
        return value

    def runtime_module(self):
        sys.path.insert(0, str(CLI.parent))
        self.addCleanup(lambda: sys.path.remove(str(CLI.parent)))
        spec = importlib.util.spec_from_loader("manager_fixture", SourceFileLoader("manager_fixture", str(CLI)))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_owner_claim_race_release_and_no_automatic_expiry(self):
        from concurrent.futures import ThreadPoolExecutor
        self.call("init", manager="race", owner=False)
        def claim(index):
            return subprocess.run([sys.executable, str(CLI), "--root", str(self.root), "--manager-id", "race",
                                   "owner", "claim", "--session-id", "same-session", "--credential-file",
                                   str(self.directory / ("race-" + str(index) + ".json"))],
                                  env=self.env, capture_output=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, range(2)))
        self.assertEqual(sorted(r.returncode for r in results), [0, 1])
        self.assertEqual(len(list(self.directory.glob("race-*.json"))), 1)
        self.spawn()
        owner_path = self.home / "owner.json"
        owner = json.loads(owner_path.read_text())
        owner["last_activity_at"] = "2000-01-01T00:00:00+00:00"
        owner_path.write_text(json.dumps(owner))
        self.call("owner", "claim", "--session-id", "new", "--credential-file", str(self.directory / "new.json"), ok=False)
        released = self.call("owner", "release")
        self.assertEqual((released["generation"], released["state"]), (2, "released"))
        self.assertTrue(self.call("status")["observed"]["tasks"][0]["alive"])
        before = self.snapshot(self.home)
        self.call("send", "T001", "fenced", ok=False)
        self.assertEqual(self.snapshot(self.home), before)
        new = self.directory / "reclaimed.json"
        self.call("owner", "claim", "--session-id", "again", "--credential-file", str(new), owner=False)
        self.credentials["alpha"] = new
        self.assertEqual(self.call("owner", "status")["generation"], 3)
        self.call("send", "T001", "continued", "--inbox-only")

    def test_takeover_checks_generation_and_fences_every_old_write(self):
        self.spawn()
        original = self.credentials["alpha"]
        before = self.snapshot(self.home)
        for generation, reason in ((0, "wrong generation"), (1, " ")):
            self.call("owner", "takeover", "--expect-generation", str(generation), "--reason", reason,
                      "--session-id", "new", "--credential-file", str(self.directory / "bad.json"), owner=False, ok=False)
        self.assertEqual(self.snapshot(self.home), before)
        result = self.takeover()
        self.assertEqual(result["generation"], 2)
        token = json.loads(self.credentials["alpha"].read_text())["token"]
        self.assertNotIn(token, json.dumps(result))
        self.assertNotIn(token, json.dumps(self.call("events")))
        self.credentials["alpha"] = original
        before_state = (self.home / "state.json").read_bytes()
        for args in [("task", "--id", "T002", "--title", "X", "--brief", str(self.brief)),
                     ("spawn", "--id", "T001"), ("send", "T001", "old"), ("stop", "T001"),
                     ("retry", "T001"), ("reconcile",), ("escalate", "T001", "--reason", "old"),
                     ("verify", "T001", "--review", str(self.review), "--command", "true"),
                     ("accept", "T001"), ("owner", "release")]:
            self.call(*args, ok=False)
        self.assertEqual((self.home / "state.json").read_bytes(), before_state)
        self.assertFalse(self.call("owner", "status")["credential_valid"])
        self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "worker unchanged")

    def test_takeover_race_only_one_expected_generation_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        def take(index):
            return subprocess.run([sys.executable, str(CLI), "--root", str(self.root), "--manager-id", "alpha",
                                   "owner", "takeover", "--expect-generation", "1", "--reason", "competing handoff",
                                   "--session-id", "successor", "--credential-file",
                                   str(self.directory / ("successor-" + str(index) + ".json"))], env=self.env, capture_output=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(take, range(2)))
        self.assertEqual(sorted(r.returncode for r in results), [0, 1])
        self.assertEqual(self.call("owner", "status", owner=False)["generation"], 2)

    def test_owner_credentials_reject_existing_symlink_and_artifact_paths(self):
        self.spawn()
        for path in (self.credentials["alpha"], self.home / "private.json",
                     Path(self.state()["worktree"]) / "private.json"):
            self.call("owner", "takeover", "--expect-generation", "1", "--reason", "test", "--session-id", "next",
                      "--credential-file", str(path), owner=False, ok=False)
        linked = self.directory / "linked.json"
        linked.symlink_to(self.credentials["alpha"])
        self.call("owner", "takeover", "--expect-generation", "1", "--reason", "test", "--session-id", "next",
                  "--credential-file", str(linked), owner=False, ok=False)
        self.assertEqual(self.call("owner", "status")["generation"], 1)

    def test_uncommitted_credential_is_diagnosed_without_activation(self):
        module = self.runtime_module()
        runtime = module.Runtime(self.root, "alpha")
        runtime.load()
        filename = self.directory / "interrupted-owner.json"
        original = module.atomic_json
        def fail_owner(path, value):
            if path.name == "owner.json":
                raise OSError("fixture crash before owner commit")
            original(path, value)
        args = argparse.Namespace(owner_action="takeover", expect_generation=1, reason="test",
                                  session_id="next", credential_file=str(filename))
        with mock.patch.object(module, "atomic_json", side_effect=fail_owner):
            with self.assertRaises(OSError):
                runtime.change_owner(args)
        self.assertTrue(filename.exists())
        before = self.snapshot(self.home)
        status = self.call("owner", "status", owner=False, env=dict(self.env, MANAGER_OWNER_FILE=str(filename)))
        self.assertFalse(status["credential_valid"])
        self.assertEqual(status["generation"], 1)
        self.assertEqual(len(status["pending_owner_operations"]), 1)
        self.assertEqual(self.snapshot(self.home), before)
        self.call("reconcile")
        self.assertEqual(self.call("owner", "status")["pending_owner_operations"], [])
        self.assertEqual(self.call("owner", "status")["generation"], 1)
        self.call("owner", "takeover", "--expect-generation", "1", "--reason", "retry", "--session-id", "next",
                  "--credential-file", str(filename), owner=False, ok=False)
        self.takeover()

    def test_committed_owner_event_is_repaired_once(self):
        module = self.runtime_module()
        runtime = module.Runtime(self.root, "alpha")
        runtime.load()
        filename = self.directory / "committed-owner.json"
        args = argparse.Namespace(owner_action="takeover", expect_generation=1, reason="test",
                                  session_id="next", credential_file=str(filename))
        with mock.patch.object(runtime, "owner_event", side_effect=OSError("fixture crash after commit")):
            with self.assertRaises(OSError):
                runtime.change_owner(args)
        self.credentials["alpha"] = filename
        status = self.call("owner", "status")
        self.assertTrue(status["credential_valid"])
        self.assertEqual(len(status["pending_owner_operations"]), 1)
        self.call("reconcile")
        self.call("reconcile")
        events = [e for e in self.call("events") if e["type"] == "owner.taken_over"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["operation_id"], status["operation_id"])
        self.assertEqual(self.call("owner", "status")["pending_owner_operations"], [])

    def test_claim_interruption_before_credential_preserves_released_owner(self):
        self.call("init", manager="fresh", owner=False)
        module = self.runtime_module()
        runtime = module.Runtime(self.root, "fresh")
        runtime.load()
        filename = self.directory / "missing-credential.json"
        args = argparse.Namespace(owner_action="claim", session_id="fresh", credential_file=str(filename))
        original_open = module.os.open
        def fail_credential(path, *args, **kwargs):
            if Path(path).resolve() == filename.resolve():
                raise OSError("fixture failure before credential write")
            return original_open(path, *args, **kwargs)
        with mock.patch.object(module.os, "open", side_effect=fail_credential):
            with self.assertRaises(OSError):
                runtime.change_owner(args)
        self.assertFalse(filename.exists())
        self.assertEqual(self.call("owner", "status", manager="fresh", owner=False)["generation"], 0)
        self.call("owner", "claim", "--session-id", "retry", "--credential-file", str(filename), manager="fresh", owner=False)
        status = self.call("owner", "status", manager="fresh", owner=False)
        self.assertEqual(status["generation"], 1)
        self.assertEqual(sorted(r["state"] for r in status["owner_operations"]), ["committed", "not_committed"])

    def test_release_interruption_repairs_event_before_next_claim(self):
        module = self.runtime_module()
        runtime = module.Runtime(self.root, "alpha")
        runtime.load()
        args = argparse.Namespace(owner_action="release", owner_file=str(self.credentials["alpha"]))
        with mock.patch.object(runtime, "owner_event", side_effect=OSError("fixture crash after release")):
            with self.assertRaises(OSError):
                runtime.change_owner(args)
        status = self.call("owner", "status")
        self.assertEqual((status["generation"], status["state"], status["credential_valid"]), (2, "released", False))
        filename = self.directory / "after-release.json"
        self.call("owner", "claim", "--session-id", "next", "--credential-file", str(filename), owner=False)
        events = [e for e in self.call("events", owner=False) if e["type"] == "owner.released"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["operation_id"], status["operation_id"])

    def test_long_verify_allows_takeover_reports_and_other_tasks_but_fences_finish(self):
        self.spawn()
        self.worker_done()
        process, finish = self.start_verify()
        status = self.call("owner", "status")
        self.assertEqual(len(status["pending_operations"]), 1)
        self.assertIn("busy", self.call("send", "T001", "blocked", ok=False)["error"].lower())
        started = time.monotonic()
        self.takeover()
        self.assertLess(time.monotonic() - started, 3)
        self.call("report", "T001", "--attempt", "1", "--state", "done", "--summary", "still reporting")
        self.call("task", "--id", "T002", "--title", "parallel", "--brief", str(self.brief))
        self.call("reconcile")
        self.assertIn("busy", self.call("accept", "T001", ok=False)["error"].lower())
        record = self.finish_verify(process, finish, passed=False)
        self.assertEqual(record["outcome"], "fenced")
        state = json.loads((self.home / "state.json").read_text())
        self.assertIn("T002", state["tasks"])
        self.assertIsNone(state["tasks"]["T001"]["verification"])
        self.call("reconcile")
        self.assertEqual(self.call("owner", "status")["pending_operations"], [])
        self.verify()
        self.call("accept", "T001")

    def test_long_verify_merges_latest_registry_and_blocks_same_task(self):
        self.spawn()
        self.worker_done()
        process, finish = self.start_verify()
        for args in [("stop", "T001"), ("retry", "T001"), ("spawn", "--id", "T001"),
                     ("verify", "T001", "--review", str(self.review), "--command", "true")]:
            self.assertIn("busy", self.call(*args, ok=False)["error"].lower())
        self.call("task", "--id", "T002", "--title", "parallel", "--brief", str(self.brief))
        record = self.finish_verify(process, finish, passed=True)
        self.assertEqual(record["outcome"], "passed")
        self.assertIn("T002", json.loads((self.home / "state.json").read_text())["tasks"])
        self.call("accept", "T001")

    def test_report_or_review_changes_during_long_verify_invalidate_run(self):
        self.spawn()
        self.worker_done()
        for mutation in ("report", "review"):
            for name in ("started", "finish"):
                (self.directory / name).unlink(missing_ok=True)
            process, finish = self.start_verify()
            if mutation == "report":
                self.call("report", "T001", "--attempt", "1", "--state", "done", "--summary", "updated completion")
            else:
                operation = self.call("owner", "status")["pending_operations"][0]
                (self.home / "tasks/T001/verification" / operation["id"] / "review.md").write_text("Changed review")
            record = self.finish_verify(process, finish, passed=False)
            self.assertEqual(record["outcome"], "snapshot_changed")
            self.assertIsNone(json.loads((self.home / "state.json").read_text())["tasks"]["T001"]["verification"])

    def test_completion_change_before_start_snapshot_cannot_pass(self):
        self.spawn()
        self.worker_done()
        module = self.runtime_module()
        runtime = module.Runtime(self.root, "alpha")
        runtime.load()
        original = runtime.reconcile
        def completion_changes():
            observed = original()
            self.call("report", "T001", "--attempt", "1", "--state", "working", "--summary", "new work")
            return observed
        args = argparse.Namespace(id="T001", owner_file=str(self.credentials["alpha"]),
                                  review=str(self.review), command=["true"], timeout=10)
        with mock.patch.dict(os.environ, self.env, clear=True), module.lock(
                self.home / "tasks/T001/.operation.lock", nonblocking=True):
            with mock.patch.object(runtime, "reconcile", side_effect=completion_changes):
                with self.assertRaisesRegex(module.Error, "Completion changed"):
                    runtime.verify(args)
        self.assertIsNone(json.loads((self.home / "state.json").read_text())["tasks"]["T001"]["verification"])

    def test_release_during_verify_fences_run_and_preserves_worker(self):
        self.spawn()
        self.worker_done()
        process, finish = self.start_verify()
        self.call("owner", "release")
        record = self.finish_verify(process, finish, passed=False)
        self.assertEqual(record["outcome"], "fenced")
        self.assertTrue(self.call("status", owner=False)["observed"]["tasks"][0]["alive"])

    def test_successful_verification_can_be_accepted_after_takeover(self):
        self.spawn()
        self.worker_done()
        record = self.verify()
        self.takeover()
        accepted = self.call("accept", "T001")
        self.assertEqual(accepted["verification"]["id"], record["id"])
        self.assertEqual(accepted["acceptance_eligibility"], "current")

    def test_interrupted_verify_releases_lock_without_granting_success(self):
        self.spawn()
        self.worker_done()
        process, finish = self.start_verify()
        process.kill()
        process.communicate(timeout=5)
        finish.touch()  # Quiesce the fixture check child separately; takeover never kills it.
        self.takeover()
        state = self.call("reconcile")["tasks"][0]
        self.assertEqual(state["operation"]["state"], "interrupted")
        self.assertTrue(state["operation"]["snapshot_matches"])
        self.assertIsNone(state["verification"])
        self.call("accept", "T001", ok=False)
        self.verify()

    def accepted_source(self, identity="T001", manager="alpha", dirty=False):
        item = self.spawn(identity, manager=manager)
        tree = Path(item["worktree"])
        (tree / "base.txt").write_text(manager + " accepted change\n")
        if dirty:
            (tree / "notes.txt").write_text("Reviewed task-owned untracked artifact\n")
        else:
            self.git("add", "base.txt", root=tree)
            self.git("commit", "-qm", "Accepted fixture change", root=tree)
        self.worker_done(identity, manager=manager)
        self.verify(identity, manager=manager)
        self.call("accept", identity, manager=manager)
        return item

    def integration_fixture(self, manager="alpha", dirty=False):
        source = self.accepted_source(manager=manager, dirty=dirty)
        base = self.git("rev-parse", "HEAD")
        self.git("branch", "release-" + manager, base)
        record = self.call("integration", "init", "--base", base, manager=manager)
        tree = Path(record["worktree"])
        if dirty:
            for filename in ("base.txt", "notes.txt"):
                (tree / filename).write_bytes((Path(source["worktree"]) / filename).read_bytes())
            self.git("add", "base.txt", "notes.txt", root=tree)
            self.git("commit", "-qm", "Integrate reviewed dirty artifacts", root=tree)
        else:
            self.git("cherry-pick", source["branch"], root=tree)
        return source, record

    def combined_verify(self, manager="alpha", command="test -f base.txt", ok=True, sources=None, target=None, timeout=600):
        args = ["integration", "verify", "--target", target or "refs/heads/release-" + manager,
                "--review", str(self.review), "--command", command, "--timeout", str(timeout)]
        for identity in sources or ["T001"]:
            args += ["--source", identity]
        return self.call(*args, manager=manager, ok=ok)

    def test_integration_parallel_init_and_resume_preserve_dirty_checkout(self):
        from concurrent.futures import ThreadPoolExecutor
        self.create_manager("beta")
        base = self.git("rev-parse", "HEAD")
        (self.root / "base.txt").write_text("user staged version\n")
        self.git("add", "base.txt")
        (self.root / "base.txt").write_text("user working version\n")
        (self.root / "user-untracked.txt").write_text("keep\n")
        index = (self.root / ".git/index").read_bytes()
        with ThreadPoolExecutor(max_workers=2) as pool:
            records = list(pool.map(lambda m: self.call("integration", "init", "--base", base, manager=m), ("alpha", "beta")))
        self.assertNotEqual(records[0]["branch"], records[1]["branch"])
        for record in records:
            self.assertEqual(self.git("rev-parse", "HEAD", root=Path(record["worktree"])), base)
            self.assertEqual((Path(record["worktree"]) / "base.txt").read_text(), "original\n")
        before = self.snapshot(self.home)
        self.assertFalse(self.call("integration", "init", "--base", base)["initialized"])
        self.assertEqual(self.snapshot(self.home), before)
        other = self.git("commit-tree", self.git("rev-parse", "HEAD^{tree}"), "-p", base, "-m", "different base")
        self.call("integration", "init", "--base", other, ok=False)
        self.assertEqual(self.snapshot(self.home), before)
        self.assertEqual((self.root / ".git/index").read_bytes(), index)
        self.assertEqual(self.git("rev-parse", "HEAD"), base)
        self.assertEqual((self.root / "base.txt").read_text(), "user working version\n")
        self.assertEqual((self.root / "user-untracked.txt").read_text(), "keep\n")
        self.assertEqual(self.call("reconcile")["orphan_worktrees"], [])

    def test_integration_dirty_accepted_source_is_copied_without_mutation(self):
        (self.root / "base.txt").write_text("user work stays here\n")
        index = (self.root / ".git/index").read_bytes()
        source, integration = self.integration_fixture(dirty=True)
        source_before = self.snapshot(Path(source["worktree"]))
        proof = self.combined_verify(command="test -f notes.txt && grep -q alpha base.txt")
        status = self.call("integration", "status")
        self.assertTrue(status["eligible"])
        self.assertEqual(status["verification_id"], proof["id"])
        accepted = proof["snapshot"]["sources"][0]
        self.assertEqual(accepted["verification_id"], self.state()["verification"]["id"])
        self.assertEqual(self.snapshot(Path(source["worktree"])), source_before)
        self.assertEqual((self.root / ".git/index").read_bytes(), index)
        self.assertEqual((self.root / "base.txt").read_text(), "user work stays here\n")
        self.assertEqual(self.git("rev-parse", "refs/heads/release-alpha"), integration["base"])
        self.assertNotEqual(proof["snapshot"]["candidate"]["oid"], integration["base"])

    def test_integration_committed_base_reaches_dependent_worker_and_multiple_sources(self):
        first, integration = self.integration_fixture()
        tree = Path(integration["worktree"])
        second = self.spawn("T002", depends_on="T001", base=integration["branch"])
        worker = Path(second["worktree"])
        self.assertEqual((worker / "base.txt").read_text(), "alpha accepted change\n")
        (worker / "dependent.txt").write_text("Uses accepted first source\n")
        self.git("add", "dependent.txt", root=worker)
        self.git("commit", "-qm", "Dependent fixture", root=worker)
        self.worker_done("T002")
        self.verify("T002")
        self.call("accept", "T002")
        self.git("cherry-pick", second["branch"], root=tree)
        record = self.combined_verify(sources=["T002", "T001"], command="test -f dependent.txt && grep -q alpha base.txt")
        self.assertEqual([s["task_id"] for s in record["snapshot"]["sources"]], ["T001", "T002"])
        self.assertTrue(self.call("integration", "status")["eligible"])
        self.combined_verify(sources=["T001", "T001"], ok=False)
        self.combined_verify(sources=["missing"], ok=False)

    def test_integration_requires_current_acceptance_and_same_manager_evidence(self):
        source, integration = self.integration_fixture()
        state_path = self.home / "state.json"
        original = state_path.read_bytes()
        for eligibility in ("unaccepted", "reverify_required"):
            state = json.loads(original)
            state["tasks"]["T001"]["acceptance_eligibility"] = eligibility
            state_path.write_text(json.dumps(state))
            self.combined_verify(ok=False)
        state_path.write_bytes(original)
        accepted_path = self.home / "tasks/T001/accepted.json"
        original_accepted = accepted_path.read_bytes()
        accepted = json.loads(original_accepted)
        accepted["manager_id"] = "beta"
        accepted_path.write_text(json.dumps(accepted))
        self.combined_verify(ok=False)
        accepted_path.write_bytes(original_accepted)
        source_review = self.home / self.state()["verification"]["review"]
        source_review.write_text("Modified source review")
        self.combined_verify(ok=False)

    def test_integration_candidate_source_review_and_record_edits_invalidate_proof(self):
        source, integration = self.integration_fixture()
        tree = Path(integration["worktree"])
        proof = self.combined_verify()
        for path, replacement in ((Path(source["worktree"]) / "base.txt", b"accepted source mutated\n"),
                                  (self.home / proof["review"], b"combined review mutated\n")):
            original = path.read_bytes()
            path.write_bytes(replacement)
            self.assertFalse(self.call("integration", "status")["eligible"])
            self.assertEqual(self.call("integration", "status")["verification_id"], proof["id"])
            path.write_bytes(original)
        proof_path = self.home / "integration-verification" / proof["id"] / "record.json"
        original = proof_path.read_bytes()
        mutated = json.loads(original)
        mutated["checks"][0]["command"] = "unreviewed replacement"
        proof_path.write_text(json.dumps(mutated))
        self.assertFalse(self.call("integration", "status")["eligible"])
        proof_path.write_bytes(original)
        (tree / "new.txt").write_text("candidate untracked change\n")
        self.assertFalse(self.call("integration", "status")["eligible"])
        self.git("add", "new.txt", root=tree)
        self.git("commit", "-qm", "Candidate advanced", root=tree)
        self.assertFalse(self.call("integration", "status")["eligible"])
        fresh = self.combined_verify()
        self.assertNotEqual(fresh["id"], proof["id"])
        self.assertFalse(self.call("integration", "status", "--verification", proof["id"])["eligible"])
        self.assertTrue(self.call("integration", "status")["eligible"])

    def test_integration_target_types_ancestry_and_stale_oid(self):
        source, integration = self.integration_fixture()
        main = self.git("symbolic-ref", "HEAD")
        main_oid = self.git("rev-parse", "HEAD")
        self.combined_verify(target=main)  # Preparation is allowed; checkout inventory belongs to delivery.
        self.assertEqual(self.git("rev-parse", "HEAD"), main_oid)
        proof = self.combined_verify()
        candidate = proof["snapshot"]["candidate"]["oid"]
        self.git("update-ref", "refs/heads/release-alpha", candidate, integration["base"])
        self.assertFalse(self.call("integration", "status")["eligible"])
        fresh = self.combined_verify()
        self.assertEqual(fresh["snapshot"]["target"]["oid"], candidate)
        self.git("symbolic-ref", "refs/heads/symbolic-release", "refs/heads/release-alpha")
        self.git("tag", "tag-release", candidate)
        unrelated = self.git("commit-tree", self.git("rev-parse", "HEAD^{tree}"), "-m", "unrelated root")
        self.git("branch", "unrelated-release", unrelated)
        for ref in ("release-alpha", "refs/tags/tag-release", "refs/remotes/origin/main", "refs/heads/missing",
                    "refs/heads/symbolic-release", "refs/heads/" + integration["branch"], "refs/heads/unrelated-release"):
            self.combined_verify(target=ref, ok=False)
        self.assertEqual(self.git("rev-parse", "refs/heads/release-alpha"), candidate)

    def test_integration_rejects_dirty_staged_untracked_and_git_operation(self):
        source, integration = self.integration_fixture()
        tree = Path(integration["worktree"])
        (tree / "base.txt").write_text("dirty\n")
        self.combined_verify(ok=False)
        self.git("add", "base.txt", root=tree)
        self.combined_verify(ok=False)
        self.git("restore", "--staged", "--worktree", "base.txt", root=tree)
        untracked = tree / "new.txt"
        untracked.write_text("untracked\n")
        self.combined_verify(ok=False)
        untracked.unlink()
        marker = Path(self.git("rev-parse", "--git-path", "CHERRY_PICK_HEAD", root=tree))
        marker.write_text(self.git("rev-parse", "HEAD", root=tree))
        self.combined_verify(ok=False)
        marker.unlink()
        self.combined_verify()

    def test_integration_submodule_dirty_untracked_uninitialized_and_revision_rejected(self):
        source, integration = self.integration_fixture()
        tree = Path(integration["worktree"])
        module = self.directory / "module-repo"
        module.mkdir()
        self.git("init", "-q", root=module)
        self.git("config", "user.name", "Fixture", root=module)
        self.git("config", "user.email", "fixture@example.invalid", root=module)
        (module / "module.txt").write_text("submodule baseline\n")
        self.git("add", "module.txt", root=module)
        self.git("commit", "-qm", "Module baseline", root=module)
        self.git("-c", "protocol.file.allow=always", "submodule", "add", str(module), "module", root=tree)
        self.git("commit", "-qm", "Combined candidate with submodule", root=tree)
        self.combined_verify()
        child = tree / "module"
        (child / "module.txt").write_text("nested dirty\n")
        self.combined_verify(ok=False)
        self.git("restore", "module.txt", root=child)
        (child / "untracked.txt").write_text("nested untracked\n")
        self.combined_verify(ok=False)
        (child / "untracked.txt").unlink()
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "Module advanced", root=child)
        self.combined_verify(ok=False)
        self.git("-c", "protocol.file.allow=always", "submodule", "update", root=tree)
        self.combined_verify()
        self.git("submodule", "deinit", "-f", "module", root=tree)
        self.combined_verify(ok=False)

    def test_integration_two_managers_verify_without_cross_writes(self):
        self.create_manager("beta")
        alpha_source, alpha = self.integration_fixture()
        beta_source, beta = self.integration_fixture(manager="beta")
        before = self.snapshot(self.root / ".manager/beta")
        a = self.combined_verify(command="grep -q alpha base.txt")
        self.assertEqual(self.snapshot(self.root / ".manager/beta"), before)
        before = self.snapshot(self.home)
        b = self.combined_verify(manager="beta", command="grep -q beta base.txt")
        self.assertEqual(self.snapshot(self.home), before)
        self.assertNotEqual(a["snapshot"]["candidate"]["ref"], b["snapshot"]["candidate"]["ref"])
        self.assertTrue(self.call("integration", "status", manager="beta")["eligible"])
        self.assertTrue(self.call("integration", "status")["eligible"])

    def test_integration_long_checks_allow_other_work_and_fence_takeover(self):
        source, integration = self.integration_fixture()
        self.create_manager("beta")
        process, finish = self.start_verify(action=["integration", "verify", "--target", "refs/heads/release-alpha", "--source", "T001"])
        self.assertIn("busy", self.call("integration", "init", "--base", integration["base"], ok=False)["error"].lower())
        self.assertIn("busy", self.combined_verify(ok=False)["error"].lower())
        observed = self.call("reconcile")
        self.assertIn({"resource": "integration", "issue": "operation_busy"}, observed["notices"])
        self.assertEqual(self.call("owner", "status")["pending_operations"][0]["resource"], "integration")
        self.takeover()
        task = self.spawn("T002", base=integration["branch"])
        self.call("report", "T002", "--attempt", "1", "--state", "working", "--summary", "Reporting during combined checks")
        self.assertEqual((Path(task["worktree"]) / "base.txt").read_text(), "alpha accepted change\n")
        # Another manager can create a worktree and verify while alpha checks hold no common lock.
        self.integration_fixture(manager="beta")
        self.combined_verify(manager="beta")
        record = self.finish_verify(process, finish, passed=False)
        self.assertEqual(record["outcome"], "fenced")
        self.assertIsNone(self.call("integration", "status")["verification_id"])
        self.call("reconcile")
        self.assertEqual(self.call("owner", "status")["pending_operations"], [])
        self.assertIn("T002", json.loads((self.home / "state.json").read_text())["tasks"])
        fresh = self.combined_verify()
        self.assertTrue(self.call("integration", "status")["eligible"])
        self.assertFalse(self.call("integration", "status", "--verification", record["id"])["eligible"])

    def test_integration_long_checks_detect_target_and_review_changes(self):
        source, integration = self.integration_fixture()
        for change in ("target", "review"):
            for filename in ("started", "finish"):
                (self.directory / filename).unlink(missing_ok=True)
            process, finish = self.start_verify(action=["integration", "verify", "--target", "refs/heads/release-alpha", "--source", "T001"])
            if change == "target":
                head = self.git("rev-parse", "HEAD", root=Path(integration["worktree"]))
                self.git("update-ref", "refs/heads/release-alpha", head)
            else:
                operation = self.call("owner", "status")["pending_operations"][0]
                (self.home / "integration-verification" / operation["id"] / "review.md").write_text("Changed copied review")
            record = self.finish_verify(process, finish, passed=False)
            self.assertEqual(record["outcome"], "snapshot_changed")
            self.assertIsNone(self.call("integration", "status")["verification_id"])

    def test_integration_failed_checks_timeout_and_interruption_never_restore_success(self):
        source, integration = self.integration_fixture()
        self.assertEqual(self.combined_verify(command="exit 7", ok=False)["outcome"], "failed")
        timeout = self.combined_verify(command="sleep 3", timeout=1, ok=False)
        self.assertTrue(timeout["checks"][0]["timed_out"])
        process, finish = self.start_verify(action=["integration", "verify", "--target", "refs/heads/release-alpha", "--source", "T001"])
        process.kill()
        process.communicate(timeout=5)
        finish.touch()  # Check children are quiesced separately from runtime advisory-lock release.
        recovered = self.call("reconcile")["integration"]
        self.assertEqual(recovered["operation"]["state"], "interrupted")
        self.assertTrue(recovered["operation"]["snapshot_matches"])
        self.assertFalse(recovered["eligible"])
        self.combined_verify()

    def test_integration_proof_survives_takeover_and_read_commands_do_not_write(self):
        before = self.snapshot(self.home)
        self.assertFalse(self.call("integration", "status", owner=False)["initialized"])
        self.assertEqual(self.snapshot(self.home), before)
        self.integration_fixture()
        proof = self.combined_verify()
        self.takeover()
        before = self.snapshot(self.home)
        self.assertTrue(self.call("integration", "status", owner=False)["eligible"])
        self.assertTrue(self.call("integration", "status", "--verification", proof["id"], owner=False)["eligible"])
        self.assertTrue(self.call("status", owner=False)["integration"]["eligible"])
        self.call("owner", "status", owner=False)
        self.assertEqual(self.snapshot(self.home), before)
        self.spawn("T002")
        self.call("integration", "status", env=self.worker_env("alpha", "T002"), owner=False, ok=False)

    def test_integration_init_recovers_completed_git_side_effect_without_reset(self):
        module = self.runtime_module()
        runtime = module.Runtime(self.root, "alpha")
        runtime.load()
        base = self.git("rev-parse", "HEAD")
        args = argparse.Namespace(base=base, owner_file=str(self.credentials["alpha"]))
        original = module.atomic_json
        def crash_before_ready(path, value):
            if path.name == "integration.json" and value["state"] == "ready":
                raise OSError("fixture crash after worktree creation")
            original(path, value)
        with mock.patch.object(module, "atomic_json", side_effect=crash_before_ready):
            with self.assertRaises(OSError):
                runtime.integration_init(args)
        status = self.call("integration", "status", owner=False)
        self.assertFalse(status["initialized"])
        tree = self.home / "integration"
        self.assertTrue(tree.is_dir())
        (tree / "local.txt").write_text("Do not reset interrupted work\n")
        self.call("integration", "init", "--base", base, ok=False)
        self.assertEqual((tree / "local.txt").read_text(), "Do not reset interrupted work\n")
        (tree / "local.txt").unlink()
        resumed = self.call("integration", "init", "--base", base)
        self.assertTrue(resumed["initialized"])
        self.assertEqual(self.git("rev-parse", "HEAD", root=tree), base)

    def test_integration_unknown_refs_paths_and_identity_are_preserved(self):
        base = self.git("rev-parse", "HEAD")
        key = hashlib.sha256(str(self.root).encode()).hexdigest()[:12]
        branch = "manager/" + key + "/alpha/integration"
        self.git("branch", branch, base)
        self.call("integration", "init", "--base", base, ok=False)
        self.assertFalse((self.home / "integration.json").exists())
        self.assertEqual(self.git("rev-parse", branch), base)
        self.git("branch", "-d", branch)  # Fixture-owned ref only.
        outside = self.directory / "outside-integration"
        outside.mkdir()
        (outside / "keep.txt").write_text("retained\n")
        (self.home / "integration").symlink_to(outside)
        self.call("integration", "init", "--base", base, ok=False)
        self.assertEqual((outside / "keep.txt").read_text(), "retained\n")
        (self.home / "integration").unlink()
        record = self.call("integration", "init", "--base", base)
        tree = Path(record["worktree"])
        self.git("checkout", "-qb", "foreign-integration", root=tree)
        self.call("integration", "init", "--base", base, ok=False)
        self.assertIn("mismatch", self.call("integration", "status")["diagnostic_error"].lower())
        self.assertEqual(self.git("branch", "--show-current", root=tree), "foreign-integration")

    def test_integration_real_conflict_must_be_resolved_before_combined_checks(self):
        source, integration = self.integration_fixture()
        tree = Path(integration["worktree"])
        second = self.spawn("T002")
        worker = Path(second["worktree"])
        (worker / "base.txt").write_text("second accepted change\n")
        self.git("add", "base.txt", root=worker)
        self.git("commit", "-qm", "Conflicting source", root=worker)
        self.worker_done("T002")
        self.verify("T002")
        self.call("accept", "T002")
        sources_before = [self.snapshot(Path(t["worktree"])) for t in (source, second)]
        with self.assertRaises(subprocess.CalledProcessError):
            self.git("cherry-pick", second["branch"], root=tree)
        self.combined_verify(sources=["T001", "T002"], ok=False)
        (tree / "base.txt").write_text("alpha accepted change\nsecond accepted change\n")
        self.git("add", "base.txt", root=tree)
        self.git("cherry-pick", "--continue", root=tree)
        self.combined_verify(sources=["T001", "T002"], command="grep -q alpha base.txt && grep -q second base.txt")
        self.assertEqual([self.snapshot(Path(t["worktree"])) for t in (source, second)], sources_before)

    def test_integration_checks_mutating_candidate_or_source_cannot_qualify(self):
        source, integration = self.integration_fixture()
        record = self.combined_verify(command="echo mutation >> base.txt", ok=False)
        self.assertEqual(record["outcome"], "snapshot_changed")
        self.assertEqual(record["checks"][0]["exit_code"], 0)
        self.git("restore", "base.txt", root=Path(integration["worktree"]))
        command = "echo mutation >> " + shlex.quote(str(Path(source["worktree"]) / "base.txt"))
        record = self.combined_verify(command=command, ok=False)
        self.assertEqual(record["outcome"], "snapshot_changed")
        self.assertIsNone(self.call("integration", "status")["verification_id"])
        self.call("spawn", "--id", "T002", "--title", "dependent", "--brief", str(self.brief),
                  "--depends-on", "T001", "--base", integration["branch"], ok=False)
        self.assertFalse((self.home / "worktrees/T002").exists())

    def test_integration_ignored_cache_output_does_not_dirty_committed_candidate(self):
        source, integration = self.integration_fixture()
        tree = Path(integration["worktree"])
        (tree / ".gitignore").write_text("cache/\n")
        self.git("add", ".gitignore", root=tree)
        self.git("commit", "-qm", "Reviewed cache ignore", root=tree)
        record = self.combined_verify(command="mkdir -p cache && echo generated > cache/test.log")
        self.assertEqual(record["outcome"], "passed")
        self.assertTrue(self.call("integration", "status")["eligible"])

    def test_integration_passed_record_before_metadata_commit_never_restores_eligibility(self):
        self.integration_fixture()
        module = self.runtime_module()
        runtime = module.Runtime(self.root, "alpha")
        runtime.load()
        args = argparse.Namespace(owner_file=str(self.credentials["alpha"]), source=["T001"],
                                  target="refs/heads/release-alpha", review=str(self.review), command=["true"], timeout=10)
        original = module.atomic_json
        def fail_current_commit(path, value):
            if path.name == "integration.json" and value.get("verification"):
                raise OSError("fixture crash after passed record, before owner qualification commit")
            original(path, value)
        with module.lock(self.home / ".integration.operation.lock", nonblocking=True):
            with mock.patch.object(module, "atomic_json", side_effect=fail_current_commit):
                with self.assertRaises(OSError):
                    runtime.integration_verify(args)
        status = self.call("integration", "status")
        identity = status["operation"]["id"]
        record_path = self.home / "integration-verification" / identity / "record.json"
        self.assertTrue(json.loads(record_path.read_text())["passed"])
        self.assertFalse(self.call("integration", "status", "--verification", identity)["eligible"])
        recovered = self.call("reconcile")["integration"]
        self.assertEqual(recovered["operation"]["state"], "interrupted")
        self.assertFalse(self.call("integration", "status", "--verification", identity)["eligible"])
        self.combined_verify()
        self.assertTrue(self.call("integration", "status")["eligible"])
        self.assertFalse(self.call("integration", "status", "--verification", identity)["eligible"])

    def delivery_runtime(self, proof):
        module = self.runtime_module()
        runtime = module.Runtime(self.root, "alpha")
        args = argparse.Namespace(owner_file=str(self.credentials["alpha"]), verification=proof["id"])
        return module, runtime, args

    def test_delivery_fast_forward_receipt_and_idempotence_after_advancement(self):
        (self.root / "base.txt").write_text("user dirty checkout\n")
        (self.root / "user.txt").write_text("untracked\n")
        source, integration = self.integration_fixture(dirty=True)
        proof = self.combined_verify()
        original = self.snapshot(Path(source["worktree"]))
        main = self.git("rev-parse", "HEAD")
        result = self.call("deliver", "--verification", proof["id"])
        self.assertEqual(result["state"], "committed")
        for ref in (result["target"], result["receipt_ref"]):
            self.assertEqual(self.git("rev-parse", ref), result["new_oid"])
        self.assertEqual(self.git("rev-parse", "HEAD"), main)
        self.assertEqual((self.root / "base.txt").read_text(), "user dirty checkout\n")
        self.assertEqual((self.root / "user.txt").read_text(), "untracked\n")
        self.assertEqual(original, self.snapshot(Path(source["worktree"])))
        tree = Path(integration["worktree"])
        (tree / "later.txt").write_text("later\n")
        self.git("add", "later.txt", root=tree)
        self.git("commit", "-qm", "Later advancement", root=tree)
        later = self.git("rev-parse", "HEAD", root=tree)
        self.git("update-ref", result["target"], later, result["new_oid"])
        self.assertEqual(self.call("deliver", "--verification", proof["id"]), result)
        self.assertEqual(self.git("rev-parse", result["target"]), later)
        self.assertEqual(self.call("reconcile")["deliveries"][0], result)
        module = self.runtime_module()
        control = module.Runtime(self.root, "alpha").control
        before = self.snapshot(control), self.snapshot(self.home)
        for action in (("status",), ("owner", "status"), ("integration", "status")):
            self.call(*action, owner=False)
        self.assertEqual(before, (self.snapshot(control), self.snapshot(self.home)))

    def test_delivery_rejects_main_linked_missing_and_locked_checkouts(self):
        self.integration_fixture()
        proof = self.combined_verify(target="refs/heads/" + self.git("branch", "--show-current"))
        self.assertIn("checked out", self.call("deliver", "--verification", proof["id"], ok=False)["error"])
        proof = self.combined_verify()
        tree = self.directory / "registered-release"
        self.git("worktree", "add", str(tree), "release-alpha")
        for state in ("present", "locked", "missing"):
            if state == "locked":
                self.git("worktree", "lock", "--reason", "Fixture retention", str(tree))
            if state == "missing":
                tree.rename(self.directory / "saved-release")
            self.assertIn("checked out", self.call("deliver", "--verification", proof["id"], ok=False)["error"])
        self.git("worktree", "unlock", str(tree))
        self.assertIn("checked out", self.call("deliver", "--verification", proof["id"], ok=False)["error"])
        self.assertEqual(self.git("rev-parse", "release-alpha"), proof["snapshot"]["target"]["oid"])
        self.assertFalse((self.root / ".git" / "manager-runtime" / "deliveries").exists())

    def test_delivery_stale_foreign_invalid_and_worker_evidence_is_rejected(self):
        self.integration_fixture()
        proof = self.combined_verify()
        self.git("update-ref", "refs/heads/release-alpha", proof["snapshot"]["candidate"]["oid"])
        self.call("deliver", "--verification", proof["id"], ok=False)
        self.assertFalse((self.root / ".git" / "manager-runtime" / "delivery.lock").exists())
        self.create_manager("beta")
        self.call("deliver", "--verification", proof["id"], manager="beta", ok=False)
        self.call("deliver", "--verification", "../../outside", ok=False)
        self.call("deliver", "--verification", proof["id"], owner=False, ok=False)
        self.call("deliver", "--verification", proof["id"], env=self.worker_env("alpha", "T001"), ok=False)

    def test_delivery_final_gate_rechecks_candidate_source_review_record_and_acceptance(self):
        source, integration = self.integration_fixture()
        proof = self.combined_verify()
        module, runtime, args = self.delivery_runtime(proof)
        original_gate = runtime.delivery_gate
        paths = [Path(integration["worktree"]) / "base.txt", Path(source["worktree"]) / "base.txt",
                 self.home / proof["review"], self.home / "integration-verification" / proof["id"] / "record.json",
                 self.home / "tasks" / "T001" / "accepted.json"]
        for path in paths:
            original = path.read_bytes()
            @contextlib.contextmanager
            def changed_gate(call_args):
                with original_gate(call_args):
                    path.write_bytes(original + b"changed\n")
                    yield
            try:
                with mock.patch.object(runtime, "delivery_gate", changed_gate):
                    with self.assertRaises((module.Error, ValueError)):
                        runtime.deliver(args)
            finally:
                path.write_bytes(original)
            self.assertEqual(self.git("rev-parse", "release-alpha"), proof["snapshot"]["target"]["oid"])
        self.call("deliver", "--verification", proof["id"])

    def test_delivery_handoff_between_preflight_and_gate_fences_old_owner(self):
        self.integration_fixture()
        proof = self.combined_verify()
        module, runtime, args = self.delivery_runtime(proof)
        original_gate = runtime.delivery_gate
        @contextlib.contextmanager
        def changed_gate(call_args):
            self.takeover()
            with original_gate(call_args):
                yield
        with mock.patch.object(runtime, "delivery_gate", changed_gate):
            with self.assertRaises(module.Error):
                runtime.deliver(args)
        self.assertEqual(self.git("rev-parse", "release-alpha"), proof["snapshot"]["target"]["oid"])
        self.call("deliver", "--verification", proof["id"])

    def test_delivery_external_target_and_candidate_races_abort_whole_transaction(self):
        self.integration_fixture()
        proof = self.combined_verify()
        module, runtime, args = self.delivery_runtime(proof)
        original = runtime.delivery_transaction
        for ref in (proof["snapshot"]["target"]["ref"], proof["snapshot"]["candidate"]["ref"]):
            expected = self.git("rev-parse", ref)
            changed = proof["snapshot"]["candidate"]["oid"] if ref.endswith("release-alpha") else proof["snapshot"]["target"]["oid"]
            def race(intent):
                self.git("update-ref", ref, changed, expected)
                original(intent)
            with mock.patch.object(runtime, "delivery_transaction", race):
                with self.assertRaises(module.Error):
                    runtime.deliver(args)
            receipt = "refs/manager-runtime/deliveries/" + runtime.delivery_id(proof["id"])
            self.assertEqual(self.git("for-each-ref", "--format=%(refname)", receipt), "")
            if ref.endswith("integration"):
                self.assertEqual(self.git("rev-parse", "release-alpha"), proof["snapshot"]["target"]["oid"])
            self.git("update-ref", ref, expected, changed)
        self.call("deliver", "--verification", proof["id"])

    def test_delivery_symbolic_target_and_unreadable_inventory_are_rejected(self):
        self.integration_fixture()
        proof = self.combined_verify()
        module, runtime, args = self.delivery_runtime(proof)
        original_gate = runtime.delivery_gate
        @contextlib.contextmanager
        def symbolic_gate(call_args):
            with original_gate(call_args):
                self.git("symbolic-ref", "refs/heads/release-alpha", "refs/heads/" + self.git("branch", "--show-current"))
                yield
        with mock.patch.object(runtime, "delivery_gate", symbolic_gate):
            with self.assertRaises(module.Error):
                runtime.deliver(args)
        self.git("symbolic-ref", "--delete", "refs/heads/release-alpha")
        self.git("update-ref", "refs/heads/release-alpha", proof["snapshot"]["target"]["oid"])
        original_run = module.run
        for output in (b"", b"worktree /broken\0branch refs/heads/elsewhere\0\0"):
            def malformed(argv, **kwargs):
                if list(argv)[-4:] == ["worktree", "list", "--porcelain", "-z"]:
                    return subprocess.CompletedProcess(argv, 0, output, b"")
                return original_run(argv, **kwargs)
            with mock.patch.object(module, "run", malformed):
                with self.assertRaises(module.Error):
                    runtime.deliver(args)
        with mock.patch.object(runtime, "delivery_inventory", side_effect=module.Error("Cannot read inventory")):
            with self.assertRaises(module.Error):
                runtime.deliver(args)
        self.call("deliver", "--verification", proof["id"])

    def test_delivery_competing_candidates_only_one_updates_shared_target(self):
        from concurrent.futures import ThreadPoolExecutor
        self.integration_fixture()
        self.create_manager("beta")
        self.integration_fixture(manager="beta")
        alpha = self.combined_verify()
        beta = self.combined_verify(manager="beta", target="refs/heads/release-alpha")
        def deliver(pair):
            manager, proof = pair
            command = [sys.executable, str(CLI), "--root", str(self.root), "--manager-id", manager,
                       "--owner-file", str(self.credentials[manager]), "deliver", "--verification", proof["id"]]
            result = subprocess.run(command, env=self.env, capture_output=True)
            return result.returncode, json.loads(result.stdout)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(deliver, (("alpha", alpha), ("beta", beta))))
        self.assertEqual(sorted(code for code, _ in results), [0, 1])
        winner = next(result for code, result in results if code == 0)
        self.assertEqual(self.git("rev-parse", "release-alpha"), winner["new_oid"])
        self.assertEqual(self.git("for-each-ref", "--format=%(refname)", "refs/manager-runtime/deliveries").splitlines(), [winner["receipt_ref"]])
        loser = "beta" if winner["manager_id"] == "alpha" else "alpha"
        tree = self.root / ".manager" / loser / "integration"
        merged = subprocess.run(["git", "-C", str(tree), "merge", "--no-commit", winner["target"]], capture_output=True)
        self.assertEqual(merged.returncode, 1)  # Both managers changed the same base line.
        (tree / "base.txt").write_text("alpha accepted change\nbeta accepted change\n")
        self.git("add", "base.txt", root=tree)
        self.git("commit", "-qm", "Integrate newer target and resolve fixture conflict", root=tree)
        renewed = self.combined_verify(manager=loser, target=winner["target"])
        delivered = self.call("deliver", "--verification", renewed["id"], manager=loser)
        self.assertEqual(delivered["old_oid"], winner["new_oid"])
        self.assertEqual(self.git("rev-parse", winner["target"]), delivered["new_oid"])

    def test_delivery_different_roots_share_control_and_maintenance_lock(self):
        self.integration_fixture()
        alpha_root, alpha_home = self.root, self.home
        linked = self.directory / "second-root"
        self.git("worktree", "add", "-b", "second-root", str(linked), "HEAD")
        self.root, self.home = linked, linked / ".manager" / "beta"
        try:
            self.create_manager("beta")
            self.integration_fixture(manager="beta")
            beta = self.combined_verify(manager="beta", target="refs/heads/release-alpha")
        finally:
            self.root, self.home = alpha_root, alpha_home
        alpha = self.combined_verify()
        module, runtime, args = self.delivery_runtime(alpha)
        with module.lock(runtime.control / "maintenance.lock"):
            blocked = self.call("deliver", "--verification", beta["id"], root=linked, manager="beta", ok=False)
            self.assertIn(str(runtime.control / "maintenance.lock"), blocked["error"])
        result = self.call("deliver", "--verification", beta["id"], root=linked, manager="beta")
        self.assertEqual(result["git_common_dir"], str(runtime.common))
        self.call("deliver", "--verification", alpha["id"], ok=False)

    def test_delivery_long_checks_hold_no_common_gate(self):
        self.integration_fixture()
        self.create_manager("beta")
        self.integration_fixture(manager="beta")
        beta = self.combined_verify(manager="beta")
        process, finish = self.start_verify(action=["integration", "verify", "--target", "refs/heads/release-alpha", "--source", "T001"])
        self.call("deliver", "--verification", beta["id"], manager="beta")
        self.spawn("T002", manager="beta")
        self.finish_verify(process, finish, passed=True)

    def test_delivery_interrupted_intent_reconciles_without_inventing_success(self):
        self.integration_fixture()
        proof = self.combined_verify()
        module, runtime, args = self.delivery_runtime(proof)
        with mock.patch.object(runtime, "delivery_transaction", side_effect=RuntimeError("Fixture interruption before transaction")):
            with self.assertRaises(RuntimeError):
                runtime.deliver(args)
        self.assertEqual(self.call("reconcile")["deliveries"][0]["state"], "not_committed")
        self.assertEqual(self.git("rev-parse", "release-alpha"), proof["snapshot"]["target"]["oid"])
        self.takeover()
        self.assertEqual(self.call("deliver", "--verification", proof["id"])["state"], "committed")

    def test_delivery_process_death_after_transaction_recovers_receipt(self):
        self.integration_fixture()
        proof = self.combined_verify()
        marker = self.directory / "committed-marker"
        script = self.directory / "delivery-crash.py"
        script.write_text("import runpy, sys, pathlib, time, argparse\n"
            "sys.path.insert(0, " + repr(str(CLI.parent)) + ")\n"
            "m = runpy.run_path(" + repr(str(CLI)) + ")\n"
            "r = m['Runtime'](" + repr(str(self.root)) + ", 'alpha')\n"
            "def pause(*args):\n pathlib.Path(" + repr(str(marker)) + ").write_text('transaction complete')\n time.sleep(30)\n"
            "r.save_delivery_result = pause\n"
            "r.deliver(argparse.Namespace(verification=" + repr(proof["id"]) + ", owner_file=" + repr(str(self.credentials["alpha"])) + "))\n")
        process = subprocess.Popen([sys.executable, str(script)], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(marker.exists())
        finally:
            process.kill()
            process.communicate(timeout=10)
        result = self.call("reconcile")["deliveries"][0]
        self.assertEqual(result["state"], "committed")
        self.assertEqual(self.call("deliver", "--verification", proof["id"]), result)

    def test_delivery_missing_wrong_or_symbolic_receipts_never_infer_success(self):
        self.integration_fixture()
        proof = self.combined_verify()
        result = self.call("deliver", "--verification", proof["id"])
        for state in ("wrong", "symbolic", "missing"):
            if state == "wrong":
                self.git("update-ref", result["receipt_ref"], result["old_oid"])
            elif state == "symbolic":
                self.git("symbolic-ref", result["receipt_ref"], result["target"])
            else:
                self.git("symbolic-ref", "--delete", result["receipt_ref"])
                self.git("update-ref", result["target"], result["old_oid"])
            self.call("deliver", "--verification", proof["id"], ok=False)
            self.assertEqual(self.call("reconcile")["deliveries"][0]["state"], "ambiguous")
        self.assertEqual(self.git("rev-parse", result["target"]), result["old_oid"])

    def test_delivery_missing_receipt_with_external_target_change_is_diagnostic(self):
        self.integration_fixture()
        proof = self.combined_verify()
        module, runtime, args = self.delivery_runtime(proof)
        with mock.patch.object(runtime, "delivery_transaction", side_effect=RuntimeError("Fixture interruption")):
            with self.assertRaises(RuntimeError):
                runtime.deliver(args)
        self.git("update-ref", "refs/heads/release-alpha", proof["snapshot"]["candidate"]["oid"])
        self.assertEqual(self.call("reconcile")["deliveries"][0]["state"], "external_change")
        self.call("deliver", "--verification", proof["id"], ok=False)
        self.assertEqual(self.git("for-each-ref", "--format=%(refname)", "refs/manager-runtime/deliveries"), "")

    def test_delivery_control_symlinks_and_corrupt_intents_are_preserved(self):
        self.integration_fixture()
        proof = self.combined_verify()
        module, runtime, args = self.delivery_runtime(proof)
        outside = self.directory / "outside-deliveries"
        outside.mkdir()
        directory = runtime.control / "deliveries"
        directory.symlink_to(outside)
        self.call("deliver", "--verification", proof["id"], ok=False)
        self.assertEqual(list(outside.iterdir()), [])
        directory.unlink()
        with mock.patch.object(runtime, "delivery_transaction", side_effect=RuntimeError("Fixture interruption")):
            with self.assertRaises(RuntimeError):
                runtime.deliver(args)
        intent = directory / runtime.delivery_id(proof["id"]) / "intent.json"
        value = json.loads(intent.read_text())
        value["new_oid"] = value["old_oid"]
        intent.write_text(json.dumps(value))
        original = intent.read_bytes()
        self.call("deliver", "--verification", proof["id"], ok=False)
        self.call("reconcile", ok=False)
        self.assertEqual(intent.read_bytes(), original)

    def test_delivery_preexisting_and_racing_receipts_are_not_adopted(self):
        self.integration_fixture()
        proof = self.combined_verify()
        module, runtime, args = self.delivery_runtime(proof)
        receipt = "refs/manager-runtime/deliveries/" + runtime.delivery_id(proof["id"])
        candidate = proof["snapshot"]["candidate"]["oid"]
        self.git("update-ref", receipt, candidate)
        self.call("deliver", "--verification", proof["id"], ok=False)
        self.assertFalse((runtime.control / "deliveries").exists())
        self.git("update-ref", "-d", receipt, candidate)
        original = runtime.delivery_transaction
        def race(intent):
            self.git("update-ref", receipt, candidate)
            original(intent)
        with mock.patch.object(runtime, "delivery_transaction", race):
            with self.assertRaises(module.Error):
                runtime.deliver(args)
        for _ in range(2):
            self.assertEqual(self.call("reconcile")["deliveries"][0]["state"], "ambiguous")
            self.call("deliver", "--verification", proof["id"], ok=False)
        self.assertEqual(self.git("rev-parse", "release-alpha"), proof["snapshot"]["target"]["oid"])

    def test_delivery_lost_receipt_after_common_result_before_manager_receipt_stays_ambiguous(self):
        self.integration_fixture()
        proof = self.combined_verify()
        module, runtime, args = self.delivery_runtime(proof)
        original = module.atomic_json
        def interrupt(path, value):
            if path.parent == self.home / "delivery":
                raise RuntimeError("Fixture interruption before manager receipt")
            original(path, value)
        with mock.patch.object(module, "atomic_json", interrupt):
            with self.assertRaises(RuntimeError):
                runtime.deliver(args)
        identity = runtime.delivery_id(proof["id"])
        self.assertFalse((self.home / "delivery" / (identity + ".json")).exists())
        self.git("update-ref", "-d", "refs/manager-runtime/deliveries/" + identity)
        self.git("update-ref", "refs/heads/release-alpha", proof["snapshot"]["target"]["oid"])
        for _ in range(2):
            self.assertEqual(self.call("reconcile")["deliveries"][0]["state"], "ambiguous")
            self.call("deliver", "--verification", proof["id"], ok=False)
        self.assertEqual(self.git("rev-parse", "release-alpha"), proof["snapshot"]["target"]["oid"])

    def legacy_fixture(self):
        self.root = (self.directory / "legacy repo").resolve()
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Migration Fixture")
        self.git("config", "user.email", "migration@example.invalid")
        (self.root / "base.txt").write_text("legacy base\n")
        (self.root / ".gitignore").write_text("cache/\n.manager/\n")
        self.git("add", "base.txt", ".gitignore")
        self.git("commit", "-qm", "Legacy base")
        base = self.git("rev-parse", "HEAD")
        key = hashlib.sha256(str(self.root).encode()).hexdigest()[:12]
        source = self.root / ".manager"
        source.mkdir()
        (source / ".lock").touch()
        for name in ("events", "inbox", "tasks", "worktrees"):
            (source / name).mkdir()
        (source / "plan.md").write_text("Historical plan with v1 report command and old paths.\n")
        (source / "unknown-note.txt").write_text("Preserve unknown ordinary files.\n")
        state = {"version": 1, "root": str(self.root), "session": "manager-" + key,
                 "created_at": "2026-10-01T00:00:00+00:00", "tasks": {}}
        for identity, attempt, task_state in (("T001", 1, "done"), ("T002", 2, "working"), ("T003", 0, "queued")):
            branch = "manager/" + key + "/" + identity
            tree = source / "worktrees" / identity
            directory = source / "tasks" / identity
            directory.mkdir()
            (source / "inbox" / identity).mkdir()
            (source / "events" / identity).mkdir()
            item = {"task_id": identity, "title": "Legacy fixture", "kind": "implementation", "agent": "codex",
                    "dependencies": ["T001"] if identity == "T003" else [], "base": base,
                    "branch": branch, "worktree": str(tree), "window": "mgr-" + identity,
                    "attempt": attempt, "state": task_state, "summary": "Legacy status", "pane": None,
                    "accepted": "2026-10-01T00:00:00+00:00" if identity == "T001" else None,
                    "verification": {"passed": True, "legacy": True} if identity == "T001" else None}
            state["tasks"][identity] = item
            (directory / "brief.md").write_text("Legacy report --root old-root, task " + identity + "\n")
            (directory / "log.txt").write_text("Verbatim legacy log 紀錄\n")
            report = {"task_id": identity, "attempt": attempt, "state": task_state,
                      "summary": "Legacy report", "updated_at": "2026-10-01T00:00:00+00:00", "question": None, "acks": []}
            if attempt:
                (directory / ".report.lock").touch()
                self.git("worktree", "add", "-b", branch, str(tree), base)
                (directory / "assignment.json").write_text(json.dumps({"task_id": identity, "attempt": attempt,
                    "root": str(self.root), "worktree": str(tree), "runtime": "legacy-manager", "auto_commit": True}))
            if identity == "T001":
                (tree / "base.txt").write_text("legacy committed change\n")
                self.git("commit", "-qam", "Legacy accepted commit", root=tree)
                (tree / "base.txt").write_text("legacy staged change\n")
                (tree / "staged.txt").write_text("blob only in index\n")
                self.git("add", "base.txt", "staged.txt", root=tree)
                (tree / "base.txt").write_text("legacy unstaged change\n")
                (tree / "notes.txt").write_text("legacy untracked\n")
                (tree / "cache").mkdir()
                (tree / "cache" / "output").write_text("legacy ignored cache\n")
                (tree / "link").symlink_to("cache/output")
                (tree / "notes.txt").chmod(0o755)
                (directory / "result.md").write_text("Legacy accepted result.\n")
                (directory / "accepted.json").write_text(json.dumps({"task_id": identity, "at": item["accepted"]}))
                history_tree = self.git("rev-parse", "HEAD^{tree}", root=tree)
                historical = subprocess.run(["git", "-C", str(self.root), "commit-tree", history_tree],
                    input=b"Historical unreachable evidence commit\n", capture_output=True, check=True).stdout.decode().strip()
                (directory / "old-proof.json").write_text(json.dumps({"head": historical, "passed": True}))
                message = "a" * 32
                report["acks"] = [message]
                (source / "inbox" / identity / (message + ".json")).write_text(json.dumps({"message_id": message,
                    "task_id": identity, "attempt": attempt, "text": "Historical correction", "delivery": "inbox"}))
            if identity == "T002":
                message = "b" * 32
                history = directory / "history" / "attempt-1"
                history.mkdir(parents=True)
                (history / "status.json").write_text(json.dumps({"task_id": identity, "attempt": 1, "acks": [message]}))
                (source / "inbox" / identity / (message + ".json")).write_text(json.dumps({"message_id": message,
                    "task_id": identity, "attempt": 1, "text": "Earlier attempt correction"}))
            (directory / "status.json").write_text(json.dumps(report))
            (source / "events" / identity / (identity + ".json")).write_text(json.dumps({"type": "legacy.event", "task_id": identity}))
        (source / "state.json").write_text(json.dumps(state))
        self.home = source / "converted"
        return source, state

    def migrate(self, *args, ok=True):
        return self.call("migrate", *args, manager="converted", owner=False, ok=ok)

    def migration_runtime(self):
        module = self.runtime_module()
        runtime = module.Runtime(self.root, "converted", inventory=True)
        return module, module.migration.Migration(runtime)

    def migration_args(self, preview, resume=None):
        return argparse.Namespace(dry_run=False, expect_source=preview["source_sha256"], source_quiesced=True, resume=resume)

    def claim_migrated(self):
        credential = self.directory / "converted.owner.json"
        self.call("owner", "claim", "--session-id", "migration-test", "--credential-file", str(credential),
                  manager="converted", owner=False)
        self.credentials["converted"] = credential

    def test_migration_dry_run_is_readonly_and_preserves_dirty_main_checkout(self):
        source, state = self.legacy_fixture()
        (self.root / "base.txt").write_text("user main dirty\n")
        (self.root / "personal.txt").write_text("user main untracked\n")
        before = self.snapshot(source), self.snapshot(self.root / ".git")
        preview = self.migrate("--dry-run")
        self.assertEqual(preview["blockers"], [])
        self.assertEqual(before, (self.snapshot(source), self.snapshot(self.root / ".git")))
        self.assertIn("unknown-note.txt", preview["inventory"]["unknown_artifacts"])
        (self.root / "base.txt").write_text("unrelated user edit\n")
        self.assertEqual(self.migrate("--dry-run")["source_sha256"], preview["source_sha256"])
        self.assertFalse((self.root / ".git" / "manager-runtime").exists())

    def test_migration_complete_preserves_content_index_history_and_objects(self):
        source, state = self.legacy_fixture()
        module, migration = self.migration_runtime()
        preview = self.migrate("--dry-run")
        snapshot = preview["inventory"]["tasks"]["T001"]["snapshot"]
        result = self.migrate("--expect-source", preview["source_sha256"], "--source-quiesced")
        self.assertEqual(result["phase"], "completed")
        tree = self.home / "worktrees" / "T001"
        self.assertEqual(migration.scan(tree, skip=(".git",)), snapshot["content"])
        self.assertEqual(hashlib.sha256(Path(snapshot["private_git"], "index").read_bytes()).hexdigest(), snapshot["index_sha256"])
        old_ref = "refs/heads/" + state["tasks"]["T001"]["branch"]
        self.assertEqual(self.git("rev-parse", old_ref), snapshot["head"])
        self.assertEqual(self.git("branch", "--show-current", root=tree), migration.r.namespace.branch("T001"))
        self.assertFalse(Path(state["tasks"]["T001"]["worktree"]).exists())
        self.assertFalse((self.home / "worktrees" / "T003").exists())
        self.assertEqual((self.home / "plan.md").read_bytes(), (source / "plan.md").read_bytes())
        self.assertEqual((self.home / "tasks/T001/brief.md").read_bytes(), (source / "tasks/T001/brief.md").read_bytes())
        self.assertEqual((self.home / "tasks/T001/history/v1/accepted.json").read_bytes(), (source / "tasks/T001/accepted.json").read_bytes())
        self.assertFalse((self.home / "tasks/T001/accepted.json").exists())
        journal = json.loads(Path(result["journal"]).read_text())
        self.assertEqual(json.loads(Path(result["journal"]).with_name("inventory.json").read_text()), preview["inventory"])
        archive = Path(result["backup"]) / "objects.idx"
        self.assertFalse((Path(result["backup"]) / "worktrees/T001/.git").exists())
        listing = self.git("verify-pack", "-v", str(archive))
        staged_blob = self.git("rev-parse", ":staged.txt", root=tree)
        historical = json.loads((source / "tasks/T001/old-proof.json").read_text())["head"]
        self.assertIn(staged_blob, listing)
        self.assertIn(historical, listing)
        self.assertIn(staged_blob, journal["object_roots"])
        before = self.snapshot(source), self.snapshot(migration.r.control)
        self.assertTrue(self.migrate()["noop"])
        self.assertEqual(before, (self.snapshot(source), self.snapshot(migration.r.control)))
        self.call("init", manager="fresh", owner=False)
        self.assertEqual(sorted(x["manager_id"] for x in self.call("managers", manager=None, owner=False)["managers"]), ["converted", "fresh"])

    def test_migration_history_is_not_current_acceptance_or_worker_identity(self):
        source, state = self.legacy_fixture()
        preview = self.migrate("--dry-run")
        self.migrate("--expect-source", preview["source_sha256"], "--source-quiesced")
        self.claim_migrated()
        migrated = self.state(manager="converted")
        self.assertEqual(migrated["state"], "verification")
        self.assertEqual(migrated["acceptance_eligibility"], "reverify_required")
        self.assertIsNone(migrated["verification"])
        self.assertIsNone(migrated["accepted"])
        self.assertIsNotNone(migrated["accepted_history"])
        self.call("accept", "T001", manager="converted", ok=False)
        self.call("report", "T001", "--attempt", "1", "--state", "done", "--summary", "Old writer", manager="converted", ok=False)
        self.call("spawn", "--id", "T003", manager="converted", ok=False)
        messages = self.call("inbox", "T001", manager="converted", owner=False)
        self.assertTrue(messages[0]["acknowledged"])
        self.assertFalse(messages[0]["current_attempt"])
        previous = self.call("inbox", "T002", manager="converted", owner=False)
        self.assertTrue(previous[0]["acknowledged"])
        self.assertFalse(previous[0]["current_attempt"])
        self.verify(manager="converted", command="test -f staged.txt")
        accepted = self.call("accept", "T001", manager="converted")
        self.assertEqual(accepted["acceptance_eligibility"], "current")
        self.call("spawn", "--id", "T003", manager="converted")
        retried = self.call("retry", "T002", manager="converted")
        self.assertEqual(retried["attempt"], 3)
        assignment = json.loads((self.home / "tasks/T002/assignment.json").read_text())
        self.assertTrue(assignment["reporting_enabled"])
        self.call("report", "T002", "--attempt", "3", "--state", "working", "--summary", "New v2 writer", manager="converted")
        before = self.snapshot(self.home)
        self.assertTrue(self.migrate()["noop"])
        self.assertEqual(before, self.snapshot(self.home))

    def test_migration_requires_assertion_hash_and_ref_destination_freshness(self):
        source, state = self.legacy_fixture()
        preview = self.migrate("--dry-run")
        self.migrate("--expect-source", preview["source_sha256"], ok=False)
        self.migrate("--source-quiesced", ok=False)
        (source / "unknown-note.txt").write_text("changed source\n")
        self.migrate("--source-quiesced", "--expect-source", preview["source_sha256"], ok=False)
        self.assertFalse((source / ".migration.json").exists())
        preview = self.migrate("--dry-run")
        ref = preview["inventory"]["tasks"]["T001"]["new_ref"]
        self.git("update-ref", ref, preview["inventory"]["tasks"]["T001"]["snapshot"]["head"])
        blocked = self.migrate("--dry-run")
        self.assertIn("Destination ref already exists: " + ref, blocked["blockers"])
        self.migrate("--source-quiesced", "--expect-source", preview["source_sha256"], ok=False)

    def test_migration_rejects_live_and_unknown_panes_without_stopping_them(self):
        source, state = self.legacy_fixture()
        session = state["session"]
        subprocess.run(["tmux", "new-session", "-d", "-s", session, "-n", "mgr-T001", "sleep 60"], env=self.env, check=True, capture_output=True)
        # fake tmux creates the session first and records windows separately.
        if not USE_REAL:
            subprocess.run(["tmux", "new-window", "-d", "-t", session + ":", "-n", "mgr-T001", "sleep 60"], env=self.env, check=True, capture_output=True)
        before = self.snapshot(source)
        preview = self.migrate("--dry-run")
        self.assertTrue(any("Live legacy pane" in b for b in preview["blockers"]))
        self.migrate("--source-quiesced", "--expect-source", preview["source_sha256"], ok=False)
        self.assertEqual(before, self.snapshot(source))
        self.assertTrue(any("Live legacy pane" in b for b in self.migrate("--dry-run")["blockers"]))

    def test_migration_rejects_busy_source_locks_without_modifying_data(self):
        source, state = self.legacy_fixture()
        module, migration = self.migration_runtime()
        for path in (source / ".lock", source / "tasks/T001/.report.lock"):
            with module.lock(path):
                before = self.snapshot(source)
                preview = self.migrate("--dry-run")
                self.assertTrue(any("Busy legacy" in b for b in preview["blockers"]))
                self.migrate("--source-quiesced", "--expect-source", preview["source_sha256"], ok=False)
                self.assertEqual(before, self.snapshot(source))

    def test_migration_resumes_after_each_phase_and_git_side_effect(self):
        source, state = self.legacy_fixture()
        module, migration = self.migration_runtime()
        preview = self.migrate("--dry-run")
        args = self.migration_args(preview)
        for phase in ("backed_up", "refs_prepared", "worktrees_moved", "data_converted", "validated", "completed"):
            original = migration.phase
            def crash(name):
                if name == phase:
                    raise RuntimeError("Fixture interruption before phase commit: " + name)
                original(name)
            with mock.patch.object(migration, "phase", crash):
                with mock.patch.dict(os.environ, self.env, clear=True):
                    with self.assertRaises(RuntimeError):
                        migration.execute(args)
            args.resume = migration.journal["id"]
            observed = self.migrate("--dry-run")
            self.assertEqual(observed["migration_id"], args.resume)
            self.call("init", manager="other", owner=False, ok=False)
            self.call("owner", "claim", "--session-id", "blocked", "--credential-file", str(self.directory / "blocked.json"),
                      manager="converted", owner=False, ok=False)
            self.migrate("--source-quiesced", ok=False)
            self.migrate("--resume", args.resume, ok=False)
        result = self.migrate("--resume", args.resume, "--source-quiesced")
        self.assertEqual(result["phase"], "completed")
        self.assertTrue(self.migrate()["noop"])

    def interrupted_migration(self, phase="backed_up"):
        source, state = self.legacy_fixture()
        module, migration = self.migration_runtime()
        preview = self.migrate("--dry-run")
        args = self.migration_args(preview)
        original = migration.phase
        def crash(name):
            original(name)
            if name == phase:
                raise RuntimeError("Fixture interruption after phase: " + phase)
        with mock.patch.object(migration, "phase", crash), mock.patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(RuntimeError):
                migration.execute(args)
        return source, state, migration, migration.journal["id"]

    def test_migration_preflight_rejects_schema_control_symlinks_and_destinations(self):
        source, state = self.legacy_fixture()
        path = source / "state.json"
        original = path.read_bytes()
        for patch in ({"version": 99}, {"version": 1.0}, {"root": "/foreign"}, {"session": "foreign"}):
            path.write_text(json.dumps({**state, **patch}))
            before = self.snapshot(source)
            self.assertTrue(self.migrate("--dry-run")["blockers"])
            self.assertEqual(before, self.snapshot(source))
        path.write_bytes(original)
        self.home.mkdir()
        self.assertIn("Destination manager already exists", self.migrate("--dry-run")["blockers"])
        self.home.rmdir()
        outside = self.directory / "outside-control"
        outside.write_text("private original\n")
        note = source / "unknown-note.txt"
        original_note = note.read_bytes()
        note.unlink()
        note.symlink_to(outside)
        self.assertTrue(self.migrate("--dry-run")["blockers"])
        self.assertEqual(outside.read_text(), "private original\n")
        note.unlink()
        note.write_bytes(original_note)
        corrupted = json.loads(original)
        corrupted["tasks"]["T001"]["dependencies"] = ["T003"]
        path.write_text(json.dumps(corrupted))
        self.assertTrue(any("Cyclic" in b for b in self.migrate("--dry-run")["blockers"]))
        path.write_bytes(original)
        foreign = source / "tasks" / "UNKNOWN"
        foreign.mkdir()
        self.assertTrue(any("Unknown" in b for b in self.migrate("--dry-run")["blockers"]))

    def test_migration_preflight_rejects_missing_locked_git_operations_and_submodules(self):
        source, state = self.legacy_fixture()
        tree = Path(state["tasks"]["T001"]["worktree"])
        saved = self.directory / "saved-legacy-tree"
        tree.rename(saved)
        self.assertTrue(self.migrate("--dry-run")["blockers"])
        saved.rename(tree)
        self.git("worktree", "lock", str(tree))
        self.assertTrue(any("Locked" in b for b in self.migrate("--dry-run")["blockers"]))
        self.git("worktree", "unlock", str(tree))
        private = Path(self.git("rev-parse", "--absolute-git-dir", root=tree))
        marker = private / "MERGE_HEAD"
        marker.write_text(self.git("rev-parse", "HEAD", root=tree) + "\n")
        self.assertTrue(any("in-progress" in b for b in self.migrate("--dry-run")["blockers"]))
        marker.unlink()
        (tree / ".gitmodules").write_text('[submodule "nested"]\n path = nested\n url = invalid\n')
        self.assertTrue(any("Submodule" in b for b in self.migrate("--dry-run")["blockers"]))
        (tree / ".gitmodules").unlink()
        self.assertEqual(self.migrate("--dry-run")["blockers"], [])

    def test_migration_changed_ignored_content_or_index_invalidates_preview(self):
        source, state = self.legacy_fixture()
        tree = Path(state["tasks"]["T001"]["worktree"])
        preview = self.migrate("--dry-run")
        (tree / "cache/output").write_text("new ignored bytes\n")
        self.assertNotEqual(self.migrate("--dry-run")["source_sha256"], preview["source_sha256"])
        self.migrate("--expect-source", preview["source_sha256"], "--source-quiesced", ok=False)
        self.assertFalse((source / ".migration.json").exists())
        preview = self.migrate("--dry-run")
        (tree / "staged.txt").write_text("new staged bytes\n")
        self.git("add", "staged.txt", root=tree)
        self.assertNotEqual(self.migrate("--dry-run")["source_sha256"], preview["source_sha256"])
        self.migrate("--expect-source", preview["source_sha256"], "--source-quiesced", ok=False)

    def test_migration_damaged_completion_becomes_failed_without_fabricating_acceptance(self):
        source, state = self.legacy_fixture()
        (source / "tasks/T001/status.json").write_text("broken json")
        (source / "tasks/T001/result.md").unlink()
        (source / "tasks/T002/status.json").write_text("[]")
        preview = self.migrate("--dry-run")
        self.assertEqual(preview["blockers"], [])
        self.migrate("--expect-source", preview["source_sha256"], "--source-quiesced")
        self.claim_migrated()
        task = self.state(manager="converted")
        self.assertEqual(task["state"], "failed")
        self.assertIsNone(task["verification"])
        self.assertEqual(task["acceptance_eligibility"], "reverify_required")
        self.assertEqual((self.home / "tasks/T001/history/v1/status.json").read_text(), "broken json")
        self.assertEqual(self.state("T002", manager="converted")["state"], "failed")
        self.assertEqual((self.home / "tasks/T002/history/v1/status.json").read_text(), "[]")
        self.call("verify", "T001", "--review", str(self.review), "--command", "true", manager="converted", ok=False)

    def test_migration_source_change_after_backup_is_preserved_and_resume_refused(self):
        source, state, migration, identity = self.interrupted_migration()
        backup = self.snapshot(migration.directory / "backup")
        note = source / "unknown-note.txt"
        note.write_text("external source mutation\n")
        self.migrate("--resume", identity, "--source-quiesced", ok=False)
        self.assertEqual(note.read_text(), "external source mutation\n")
        self.assertEqual(backup, self.snapshot(migration.directory / "backup"))
        self.assertEqual(self.git("for-each-ref", "--format=%(refname)", "refs/heads/manager/" + migration.r.key + "/converted"), "")
        self.assertFalse(migration.probe_lock(source / ".lock"))

    def test_migration_backup_and_moved_tree_changes_are_never_overwritten(self):
        source, state, migration, identity = self.interrupted_migration("worktrees_moved")
        tree = self.home / "worktrees" / "T001"
        note = tree / "notes.txt"
        original = note.read_bytes()
        note.write_text("external destination mutation\n")
        self.migrate("--resume", identity, "--source-quiesced", ok=False)
        self.assertEqual(note.read_text(), "external destination mutation\n")
        note.write_bytes(original)
        mode = self.home.stat().st_mode & 0o7777
        self.home.chmod(mode ^ 0o100)
        self.migrate("--resume", identity, "--source-quiesced", ok=False)
        self.assertEqual(self.home.stat().st_mode & 0o7777, mode ^ 0o100)
        self.home.chmod(mode)
        backup_note = migration.directory / "backup/manager/plan.md"
        backup_note.write_text("damaged backup\n")
        before = self.snapshot(migration.directory / "backup")
        self.migrate("--resume", identity, "--source-quiesced", ok=False)
        self.assertEqual(before, self.snapshot(migration.directory / "backup"))

    def test_migration_recovers_ref_move_switch_and_partial_conversion_intents(self):
        source, state = self.legacy_fixture()
        module, migration = self.migration_runtime()
        args = self.migration_args(self.migrate("--dry-run"))
        original_git = migration.git
        for action in ("move", "switch"):
            def crash(root, *argv):
                value = original_git(root, *argv)
                if (action == "move" and argv[:2] == ("worktree", "move")) or (action == "switch" and argv[:2] == ("symbolic-ref", "HEAD")):
                    raise RuntimeError("Fixture interruption after Git side effect: " + action)
                return value
            with mock.patch.object(migration, "git", crash), mock.patch.dict(os.environ, self.env, clear=True):
                with self.assertRaises(RuntimeError):
                    migration.execute(args)
            args.resume = migration.journal["id"]
        original_write = module.atomic_json
        def partial(path, value):
            original_write(path, value)
            if path == self.home / "tasks/T002/status.json":
                raise RuntimeError("Fixture interruption after partial conversion")
        with mock.patch.object(module, "atomic_json", partial), mock.patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(RuntimeError):
                migration.execute(args)
        args.resume = migration.journal["id"]
        self.assertEqual(self.migrate("--resume", args.resume, "--source-quiesced")["phase"], "completed")

    def test_migration_ref_race_and_corrupt_mapping_cannot_adopt_or_escape(self):
        source, state, migration, identity = self.interrupted_migration()
        entry = migration.journal["inventory"]["tasks"]["T001"]
        self.git("update-ref", entry["new_ref"], entry["snapshot"]["head"])
        self.migrate("--resume", identity, "--source-quiesced", ok=False)
        self.assertTrue(Path(entry["old_tree"]).exists())
        self.git("update-ref", "-d", entry["new_ref"])
        journal_path = migration.directory / "journal.json"
        journal = json.loads(journal_path.read_text())
        outside = self.directory / "escape-target"
        journal["inventory"]["tasks"]["T001"]["new_tree"] = str(outside)
        journal["source_sha256"] = migration.digest(journal["inventory"])
        journal_path.write_text(json.dumps(journal))
        self.migrate("--resume", identity, "--source-quiesced", ok=False)
        self.assertFalse(outside.exists())

    def test_migration_sigkill_after_move_releases_locks_and_resumes(self):
        source, state = self.legacy_fixture()
        preview = self.migrate("--dry-run")
        marker = self.directory / "moved-marker"
        script = self.directory / "migration-crash.py"
        script.write_text("import runpy, sys, pathlib, time, argparse\n"
            "sys.path.insert(0, " + repr(str(CLI.parent)) + ")\n"
            "m = runpy.run_path(" + repr(str(CLI)) + ")\n"
            "r = m['Runtime'](" + repr(str(self.root)) + ", 'converted', inventory=True)\n"
            "migration = m['migration'].Migration(r)\noriginal = migration.git\n"
            "def pause(root, *args):\n value = original(root, *args)\n if args[:2] == ('worktree', 'move'):\n  pathlib.Path(" + repr(str(marker)) + ").write_text('moved')\n  time.sleep(30)\n return value\n"
            "migration.git = pause\n"
            "migration.execute(argparse.Namespace(dry_run=False, resume=None, source_quiesced=True, expect_source=" + repr(preview["source_sha256"]) + "))\n")
        process = subprocess.Popen([sys.executable, str(script)], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 20
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(marker.exists())
        finally:
            process.kill()
            process.communicate(timeout=10)
        identity = json.loads((source / ".migration.json").read_text())["id"]
        self.assertEqual(self.migrate("--resume", identity, "--source-quiesced")["phase"], "completed")

    def test_migration_unknown_dead_pane_and_post_preview_ref_race_are_rejected(self):
        source, state = self.legacy_fixture()
        preview = self.migrate("--dry-run")
        module, migration = self.migration_runtime()
        original = migration.prepare_refs
        def race():
            for entry in migration.journal["inventory"]["tasks"].values():
                if entry["snapshot"]:
                    self.git("update-ref", entry["new_ref"], entry["snapshot"]["head"])
            return original()
        with mock.patch.object(migration, "prepare_refs", race), mock.patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(module.Error):
                migration.execute(self.migration_args(preview))
        identity = migration.journal["id"]
        for _ in range(2):
            self.migrate("--resume", identity, "--source-quiesced", ok=False)
        self.assertTrue(Path(state["tasks"]["T001"]["worktree"]).exists())
        self.executable("tmux", "#!/usr/bin/env python3\nprint('unknown-window\\t%999\\t1')\n")
        with mock.patch.dict(os.environ, self.env, clear=True):
            _, blockers = migration.panes(state["tasks"])
            self.assertTrue(any("Unknown legacy pane" in b for b in blockers))

    def test_migration_failed_and_cancelled_done_claims_remain_nonaccepted(self):
        source, state = self.legacy_fixture()
        state["tasks"]["T001"]["state"] = "cancelled"
        state["tasks"]["T002"]["state"] = "failed"
        state["tasks"]["T002"]["accepted"] = None
        report = json.loads((source / "tasks/T002/status.json").read_text())
        report["state"] = "done"
        (source / "tasks/T002/status.json").write_text(json.dumps(report))
        (source / "tasks/T002/result.md").write_text("Old done claim after failure.\n")
        (source / "state.json").write_text(json.dumps(state))
        preview = self.migrate("--dry-run")
        self.migrate("--expect-source", preview["source_sha256"], "--source-quiesced")
        self.claim_migrated()
        observed = self.call("reconcile", manager="converted")["tasks"]
        statuses = {t["task_id"]: t for t in observed}
        self.assertEqual(statuses["T001"]["state"], "cancelled")
        self.assertEqual(statuses["T002"]["state"], "failed")
        self.assertEqual(statuses["T002"]["acceptance_eligibility"], "unaccepted")

    def composition_fixture(self):
        source, legacy = self.legacy_fixture()
        (self.root / "base.txt").write_text("user staged version\n")
        self.git("add", "base.txt")
        (self.root / "base.txt").write_text("user working version\n")
        (self.root / "personal.txt").write_text("user untracked file\n")
        main_snapshot = {name: (self.root / name).read_bytes()
                         for name in ("base.txt", "personal.txt", ".git/index", ".git/HEAD", ".gitignore")}
        preview = self.migrate("--dry-run")
        result = self.migrate("--expect-source", preview["source_sha256"], "--source-quiesced")
        self.claim_migrated()
        base = legacy["tasks"]["T001"]["base"]
        self.git("branch", "release-converted", base)
        integration = self.call("integration", "init", "--base", base, manager="converted")
        self.combined_verify(manager="converted", ok=False)  # History cannot qualify as a source.
        self.verify(manager="converted", command="test -f staged.txt && test -L link")
        self.call("accept", "T001", manager="converted")
        tree, worker = Path(integration["worktree"]), self.home / "worktrees/T001"
        # Transfer the reviewed dirty snapshot without staging or changing the accepted source.
        for name in ("base.txt", "staged.txt", "notes.txt", "link"):
            shutil.copy2(worker / name, tree / name, follow_symlinks=False)
        self.git("add", "base.txt", "staged.txt", "notes.txt", "link", root=tree)
        self.git("commit", "-qm", "Integrate reverified migrated snapshot", root=tree)
        return result, integration, main_snapshot

    def test_composition_migration_dependency_handoff_and_competing_delivery(self):
        migration, integration, main_snapshot = self.composition_fixture()
        target = "refs/heads/release-converted"
        tree = Path(integration["worktree"])
        source_before = self.snapshot(self.home / "worktrees/T001")
        history_before = self.snapshot(self.home / "tasks/T001/history/v1")
        backup_before = self.snapshot(Path(migration["backup"]))
        old_ref = self.git("for-each-ref", "--format=%(refname) %(objectname)",
                           "refs/heads/manager/" + hashlib.sha256(str(self.root).encode()).hexdigest()[:12] + "/T001")
        # Migration preserves queued definitions, including their old base. Replan
        # with a fresh task rather than silently rewriting a historical definition.
        self.call("spawn", "--id", "T003", "--base", integration["branch"], manager="converted", ok=False)
        self.assertFalse((self.home / "worktrees/T003").exists())
        dependent = self.spawn("T004", manager="converted", depends_on="T001", base=integration["branch"])
        worker = Path(dependent["worktree"])
        self.assertEqual((worker / "base.txt").read_text(), "legacy unstaged change\n")
        self.assertEqual((worker / "staged.txt").read_text(), "blob only in index\n")
        self.worker_done("T004", manager="converted")
        self.verify("T004", manager="converted")
        message = self.call("send", "T004", "Add dependent artifact", "--inbox-only", manager="converted")
        self.call("accept", "T004", manager="converted", ok=False)
        environment = self.worker_env("converted", "T004")
        self.call("report", "T004", "--attempt", "1", "--state", "working", "--summary", "Correction received",
                  "--ack", message["message_id"], manager="converted", owner=False, env=environment)
        self.assertTrue(self.call("inbox", "T004", manager="converted")[0]["acknowledged"])
        (worker / "dependent.txt").write_text("Depends on migrated snapshot\n")
        self.git("add", "dependent.txt", root=worker)
        self.git("commit", "-qm", "Dependent artifact", root=worker)
        self.worker_done("T004", manager="converted")
        self.verify("T004", manager="converted", command="test -f dependent.txt && test -f staged.txt")
        self.call("accept", "T004", manager="converted")
        self.git("cherry-pick", dependent["branch"], root=tree)
        proof = self.combined_verify(manager="converted", sources=["T001", "T004"],
                                     command="test -f dependent.txt && test -f staged.txt")

        self.create_manager("beta")
        beta_source, beta = self.integration_fixture(manager="beta")
        beta_proof = self.combined_verify(manager="beta", target=target)
        beta_before = self.snapshot(self.root / ".manager/beta")
        previous = self.credentials["converted"]
        self.call("owner", "release", manager="converted")
        new = self.directory / "composition-successor.json"
        self.call("owner", "claim", "--session-id", "successor", "--credential-file", str(new),
                  manager="converted", owner=False)
        self.call("deliver", "--verification", proof["id"], manager="converted", ok=False)
        self.credentials["converted"] = new
        self.assertNotEqual(previous, new)
        self.assertTrue(self.call("integration", "status", manager="converted")["eligible"])
        self.assertEqual(beta_before, self.snapshot(self.root / ".manager/beta"))
        delivered_beta = self.call("deliver", "--verification", beta_proof["id"], manager="beta")
        self.call("deliver", "--verification", proof["id"], manager="converted", ok=False)
        self.assertEqual(self.git("rev-parse", target), delivered_beta["new_oid"])
        self.assertFalse(self.call("integration", "status", manager="converted")["eligible"])

        merge = subprocess.run(["git", "-C", str(tree), "merge", "--no-commit", target], capture_output=True)
        self.assertEqual(merge.returncode, 1)  # Both candidates changed base.txt.
        (tree / "base.txt").write_text("legacy unstaged change\nbeta accepted change\n")
        self.git("add", "base.txt", root=tree)
        self.git("commit", "-qm", "Resolve shared target conflict", root=tree)
        fresh = self.combined_verify(manager="converted", sources=["T001", "T004"],
                                     command="test -f dependent.txt && test -f staged.txt && grep -q beta base.txt")
        receipt = self.call("deliver", "--verification", fresh["id"], manager="converted")
        self.assertEqual(receipt["old_oid"], delivered_beta["new_oid"])
        self.assertEqual(self.git("rev-parse", receipt["receipt_ref"]), self.git("rev-parse", target))
        self.assertEqual(self.call("deliver", "--verification", fresh["id"], manager="converted"), receipt)
        self.assertEqual(self.call("reconcile", manager="converted")["deliveries"], [receipt])
        self.assertEqual(source_before, self.snapshot(self.home / "worktrees/T001"))
        self.assertEqual(history_before, self.snapshot(self.home / "tasks/T001/history/v1"))
        self.assertEqual(backup_before, self.snapshot(Path(migration["backup"])))
        self.assertEqual(old_ref, self.git("for-each-ref", "--format=%(refname) %(objectname)", old_ref.split()[0]))
        for name, content in main_snapshot.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        before = self.snapshot(self.root / ".manager"), self.snapshot(self.root / ".git")
        for manager in ("converted", "beta"):
            for args in (("init",), ("status",), ("owner", "status"), ("integration", "status"),
                         ("inbox", "T001"), ("events",)):
                self.call(*args, manager=manager, owner=False)
        self.call("managers", manager=None, owner=False)
        self.assertTrue(self.migrate()["noop"])
        self.assertEqual(before, (self.snapshot(self.root / ".manager"), self.snapshot(self.root / ".git")))

    def test_composition_migrated_long_checks_handoff_reports_capacity_and_delivery(self):
        migration, integration, main_snapshot = self.composition_fixture()
        self.create_manager("beta")
        self.integration_fixture(manager="beta")
        beta_proof = self.combined_verify(manager="beta")
        (self.root / ".manager.yml").write_text(json.dumps({"manager": {"max_workers": 1}}))
        process, finish = self.start_verify(manager="converted", action=["integration", "verify", "--target",
                                          "refs/heads/release-converted", "--source", "T001"])
        self.takeover(manager="converted")
        retried = self.call("retry", "T002", "--agent", "claude", manager="converted")
        beta_worker = self.spawn("T002", manager="beta", agent="codex")
        self.assertEqual((retried["attempt"], retried["agent"]), (3, "claude"))
        self.assertEqual(beta_worker["agent"], "codex")
        for manager in ("converted", "beta"):
            capacity = self.call("status", manager=manager, owner=False)["worker_capacity"]
            self.assertEqual(capacity, {"active": 1, "max_workers": 1, "scope": "manager"})
            self.call("spawn", "--id", "T004", "--title", "Beyond limit", "--brief", str(self.brief),
                      manager=manager, ok=False)
        message = self.call("send", "T002", "Continue new assignment", "--inbox-only", manager="converted")
        environment = self.worker_env("converted", "T002")
        self.call("report", "T002", "--attempt", "3", "--state", "working", "--summary", "Fresh assignment",
                  "--ack", message["message_id"], manager="converted", owner=False, env=environment)
        before_beta = self.snapshot(self.root / ".manager/beta")
        self.call("report", "T002", "--attempt", "1", "--state", "working", "--summary", "Wrong manager",
                  manager="beta", owner=False, env=environment, ok=False)
        self.assertEqual(before_beta, self.snapshot(self.root / ".manager/beta"))
        delivered = self.call("deliver", "--verification", beta_proof["id"], manager="beta")
        self.assertEqual(delivered["state"], "committed")  # Long checks hold no common delivery gate.
        reconciled = self.call("reconcile", manager="converted")
        self.assertIn({"resource": "integration", "issue": "operation_busy"}, reconciled["notices"])
        record = self.finish_verify(process, finish, passed=False)
        self.assertEqual(record["outcome"], "fenced")
        self.call("deliver", "--verification", record["id"], manager="converted", ok=False)
        self.call("reconcile", manager="converted")
        self.assertEqual(self.call("owner", "status", manager="converted")["pending_operations"], [])
        fresh = self.combined_verify(manager="converted", command="test -f staged.txt")
        self.call("deliver", "--verification", fresh["id"], manager="converted")
        self.assertTrue(self.call("status", manager="beta")["observed"]["tasks"][1]["alive"])
        self.assertTrue(self.migrate()["noop"])
        for name, content in main_snapshot.items():
            self.assertEqual((self.root / name).read_bytes(), content)

    def test_migration_selector_examples_agree_and_conflicts_are_readonly(self):
        self.legacy_fixture()
        before = self.snapshot(self.root / ".manager"), self.snapshot(self.root / ".git")
        global_preview = self.migrate("--dry-run")
        local_preview = self.call("migrate", "--manager-id", "converted", "--dry-run", manager=None, owner=False)
        both_preview = self.migrate("--manager-id", "converted", "--dry-run")
        self.assertEqual(global_preview, local_preview)
        self.assertEqual(global_preview, both_preview)
        error = self.migrate("--manager-id", "different", "--dry-run", ok=False)
        self.assertIn("Conflicting migration manager selectors", error["error"])
        self.assertEqual(before, (self.snapshot(self.root / ".manager"), self.snapshot(self.root / ".git")))

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
