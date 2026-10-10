#!/usr/bin/env python3
"""Behavioral tests with real Git repos and fake providers; no model/API calls.

Default: deterministic fake tmux. MANAGER_TEST_REAL_TMUX=1: real isolated tmux
server with the same fake providers, exercising interactive lifecycle and paste.
"""
import argparse
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

    def takeover(self, generation=None, reason="Explicit fixture handoff"):
        if generation is None:
            generation = self.call("owner", "status")["generation"]
        credential = self.directory / ("takeover-" + str(generation) + ".json")
        result = self.call("owner", "takeover", "--expect-generation", str(generation),
                           "--reason", reason, "--session-id", "successor",
                           "--credential-file", str(credential), owner=False)
        self.credentials["alpha"] = credential
        return result

    def start_verify(self):
        started, finish = self.directory / "started", self.directory / "finish"
        code = ("from pathlib import Path; import time, os; "
                "assert 'MANAGER_OWNER_FILE' not in os.environ; "
                "Path(" + repr(str(started)) + ").write_text('ready'); "
                "deadline=time.monotonic()+15\n"
                "while not Path(" + repr(str(finish)) + ").exists():\n"
                " assert time.monotonic()<deadline; time.sleep(.02)\n")
        command = shlex.join([sys.executable, "-c", code])
        process = subprocess.Popen([sys.executable, str(CLI), "--root", str(self.root),
                                   "--manager-id", "alpha", "--owner-file", str(self.credentials["alpha"]),
                                   "verify", "T001", "--review", str(self.review), "--command", command],
                                  env=dict(self.env, MANAGER_OWNER_FILE=str(self.credentials["alpha"])),
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
