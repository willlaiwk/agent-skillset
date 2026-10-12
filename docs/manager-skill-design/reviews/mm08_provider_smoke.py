#!/usr/bin/env python3
"""Opt-in real interactive provider smoke fixture; may consume account usage.

prepare creates only a temporary repo; spawn launches one real Codex or Claude worker.
inspect/correct/verify/integrate operate that explicit fixture; no auto approvals.
finish rechecks preservation and stops only its dedicated, idle tmux server.
trust requires --confirm-trust and an explicit human decision for the native prompt.
Artifacts and private owner credentials remain in the returned temporary folder.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

REPOSITORY = Path(__file__).resolve().parents[3]
CLI = REPOSITORY / "skills/manager/scripts/manager"
TASK_FILES = ("smoke.py", "test_smoke.py")


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def snapshot(directory):
    return {str(path.relative_to(directory)): {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mtime_ns": path.stat().st_mtime_ns,
        "mode": path.stat().st_mode,
    } for path in sorted(directory.rglob("*")) if path.is_file() and path.name != "log.txt"}


class Fixture:
    def __init__(self, directory):
        self.directory = directory.resolve()
        run = self.directory / "run.json"
        self.provider = json.loads(run.read_text())["provider"] if run.is_file() else None
        self.root = self.directory / "repo with spaces"
        self.env = dict(os.environ)
        self.env.pop("MANAGER_OWNER_FILE", None)
        for key in list(self.env):
            if key.startswith("MANAGER_WORKER_"):
                self.env.pop(key)
        self.env["PATH"] = str(self.directory / "bin") + os.pathsep + self.env["PATH"]

    def git(self, *args, root=None):
        result = subprocess.run(["git", "-C", str(root or self.root), *args],
                                capture_output=True, text=True, check=True, env=self.env)
        return result.stdout.strip()

    def call(self, *args, manager="alpha", owner=True, expected=0):
        command = [sys.executable, str(CLI), "--root", str(self.root)]
        if manager:
            command += ["--manager-id", manager]
        if owner and manager:
            command += ["--owner-file", str(self.directory / "private" / (manager + ".owner.json"))]
        result = subprocess.run(command + list(args), env=self.env, capture_output=True, text=True)
        with (self.directory / "commands.jsonl").open("a") as stream:
            stream.write(json.dumps({"argv": command + list(args), "exit_code": result.returncode}) + "\n")
        value = json.loads(result.stdout)
        if result.returncode != expected:
            raise RuntimeError(value)
        return value

    def prepare(self, provider):
        self.provider = provider
        for name in ("bin", "private", "evidence"):
            (self.directory / name).mkdir()
        self.root.mkdir()
        real_tmux = shutil.which("tmux")
        if not real_tmux or not shutil.which(provider):
            raise RuntimeError("Real tmux and " + provider + " must be installed")
        wrapper = self.directory / "bin/tmux"
        wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(real_tmux) + " -S " +
                           shlex.quote(str(self.directory / "tmux.sock")) + ' "$@"\n')
        wrapper.chmod(0o755)
        self.git("init", "-q")
        self.git("config", "user.name", "MM-08 Smoke Fixture")
        self.git("config", "user.email", "mm08@example.invalid")
        (self.root / "smoke.py").write_text('def greeting(name):\n    raise NotImplementedError("Fixture task")\n')
        (self.root / "test_smoke.py").write_text(
            'import unittest\nfrom smoke import greeting\n\nclass GreetingTests(unittest.TestCase):\n'
            '    def test_name(self):\n        self.assertEqual(greeting("Ada"), "Hello, Ada!")\n\n'
            'if __name__ == "__main__":\n    unittest.main()\n')
        instructions = (
            "This is an isolated MM-08 smoke fixture. Use only local fixture files and the assigned runtime.\n"
            "Do not browse, install dependencies, use external apps, launch subagents, or inspect credentials.\n"
            "Keep provider native sandbox/approval checks. Do not change global config or permissions.\n"
            "Only smoke.py and test_smoke.py are task-owned; task result/status/inbox use assigned paths.\n")
        # Codex reads AGENTS.md and Claude Code reads CLAUDE.md; keep both identical.
        for name in ("AGENTS.md", "CLAUDE.md"):
            (self.root / name).write_text(instructions)
        (self.root / ".manager.yml").write_text(json.dumps({"manager": {"max_workers": 1},
                                                         "git": {"auto_commit": False}}))
        (self.root / "shared-note.txt").write_text("Original user content\n")
        self.git("add", *TASK_FILES, "AGENTS.md", "CLAUDE.md", ".manager.yml", "shared-note.txt")
        self.git("commit", "-qm", "Initial real provider fixture")
        (self.root / "shared-note.txt").write_text("Staged user content\n")
        self.git("add", "shared-note.txt")
        (self.root / "shared-note.txt").write_text("Unstaged user content\n")
        (self.root / "personal.txt").write_text("Untracked user content\n")
        brief = self.directory / "brief.md"
        brief.write_text(
            "# T001 — tiny greeting task\n\n"
            "Implement greeting(name) in smoke.py to return exactly 'Hello, Ada!' for 'Ada' "
            "and 'Hello, Lin!' for 'Lin'. Add a second local unittest for Lin in test_smoke.py.\n"
            "Allowed code files: smoke.py and test_smoke.py only. No dependencies, external access, "
            "subagents, Git commits, merge/push, or global configuration changes.\n"
            "Read assignment.json and worker protocol. Publish structured working status with the "
            "absolute runtime, canonical root, manager ID, task ID, attempt and assignment ID.\n"
            "Run python3 -m unittest -v in your worktree. Write the assigned task result.md with "
            "files, behavior, tests/exit status and caveats, then report done through runtime.\n"
            "Stay available for a manager correction. For a manager message, read your own inbox, "
            "ack its current message ID through report --ack, implement only that correction, "
            "rerun tests, update result.md and report done again. Never use owner credentials.\n")
        for manager in ("alpha", "beta"):
            self.call("init", manager=manager, owner=False)
            self.call("owner", "claim", "--session-id", "mm08-" + manager, "--credential-file",
                      str(self.directory / "private" / (manager + ".owner.json")), manager=manager, owner=False)
            self.call("task", "--id", "T001", "--title", "Real provider greeting", "--brief", str(brief),
                      "--agent", provider, manager=manager)
        self.call("integration", "init", "--base", "HEAD", manager="beta")
        baseline = {"main": {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                             for name in (*TASK_FILES, "shared-note.txt", "personal.txt", ".git/index", ".git/HEAD")},
                    "beta": snapshot(self.root / ".manager/beta"), "head": self.git("rev-parse", "HEAD")}
        save(self.directory / "baseline.json", baseline)
        save(self.directory / "run.json", {"root": str(self.root), "runtime": str(CLI),
                                           "provider": provider, "isolated_socket": str(self.directory / "tmux.sock")})
        return {"run": str(self.directory), "root": str(self.root), "managers": ["alpha", "beta"]}

    def preserved(self):
        baseline = json.loads((self.directory / "baseline.json").read_text())
        assert self.git("rev-parse", "HEAD") == baseline["head"]
        for name, digest in baseline["main"].items():
            assert hashlib.sha256((self.root / name).read_bytes()).hexdigest() == digest, name
        assert snapshot(self.root / ".manager/beta") == baseline["beta"]
        return {"main_head_index_files_preserved": True, "beta_namespace_tree_preserved": True}

    def action(self, action, confirm_trust=False):
        evidence = self.directory / "evidence"
        if action == "spawn":
            result = self.call("spawn", "--id", "T001")
        elif action == "inspect":
            result = {"status": self.call("status", owner=False), "pane": self.call("peek", "T001", owner=False),
                      "inbox": self.call("inbox", "T001", owner=False)}
        elif action == "trust":
            if not confirm_trust:
                raise ValueError("trust needs --confirm-trust after an explicit human decision")
            if self.provider != "codex":
                raise ValueError("Only the Codex trust prompt is scripted; approve other native prompts "
                                 "yourself in the attached fixture tmux session")
            if (evidence / "trust.json").exists():
                raise ValueError("Native trust was already confirmed; never replay prompt input")
            pane = self.call("peek", "T001", owner=False)
            assert "Trust this folder?" in pane["output"] and str(self.root) in pane["output"]
            assert "1. Trust and continue" in pane["output"]
            state = json.loads((self.root / ".manager/alpha/state.json").read_text())
            pane_id = state["tasks"]["T001"]["pane"]
            # Native trust input only, on this fixture's selected pane/socket.
            # All worker lifecycle management continues through the manager CLI.
            subprocess.run([str(self.directory / "bin/tmux"), "send-keys", "-t", pane_id, "Enter"],
                           env=self.env, check=True)
            result = {"human_confirmed_native_folder_trust": str(self.root), "pane": pane_id}
        elif action == "correct":
            task_home = self.root / ".manager/alpha/tasks/T001"
            report = json.loads((task_home / "status.json").read_text())
            assert report["state"] == "done", "Wait for the initial structured completion"
            assert (task_home / "result.md").read_text().strip()
            save(evidence / "initial-report.json", report)
            shutil.copy2(task_home / "result.md", evidence / "initial-result.md")
            for name in TASK_FILES:
                shutil.copy2(self.root / ".manager/alpha/worktrees/T001" / name, evidence / ("initial-" + name))
            result = self.call("send", "T001",
                "Correction: greeting must strip surrounding whitespace before formatting (e.g. '  Ada  ' -> "
                "'Hello, Ada!'). For a blank/whitespace-only name raise ValueError('name is required'). "
                "Add unittest cases for both. First read your inbox and acknowledge this current message ID "
                "using runtime report --ack with the same launch identity. Edit only your task files, "
                "rerun tests, update result.md, report done and remain available. No commits or external access.")
        elif action == "verify":
            task_home = self.root / ".manager/alpha/tasks/T001"
            report = json.loads((task_home / "status.json").read_text())
            message = json.loads((evidence / "correct.json").read_text())
            assert report["state"] == "done" and message["message_id"] in report["acks"]
            review = self.directory / "review.md"
            assert review.is_file() and review.read_text().strip(), "Write an independent review first"
            hidden = ("from smoke import greeting; assert greeting('  Ada  ') == 'Hello, Ada!'; "
                      "assert greeting('Lin') == 'Hello, Lin!'\n"
                      "try: greeting('   ')\n"
                      "except ValueError as exc: assert str(exc) == 'name is required'\n"
                      "else: raise AssertionError('blank name was accepted')\n")
            result = self.call("verify", "T001", "--review", str(review), "--command", "python3 -B -m unittest -v",
                               "--command", shlex.join([sys.executable, "-B", "-c", hidden]))
            save(evidence / "verification.json", result)
            result = {"verification": result, "acceptance": self.call("accept", "T001"),
                      "preservation": self.preserved()}
        elif action == "integrate":
            review = self.directory / "integration-review.md"
            assert review.is_file() and review.read_text().strip(), "Write a combined review first"
            self.git("branch", "release-smoke", "HEAD")
            integration = self.call("integration", "init", "--base", "HEAD")
            tree = Path(integration["worktree"])
            source = self.root / ".manager/alpha/worktrees/T001"
            before = snapshot(source)
            for name in TASK_FILES:
                shutil.copy2(source / name, tree / name)
            self.git("add", *TASK_FILES, root=tree)
            self.git("commit", "-qm", "Integrate reviewed real provider greeting", root=tree)
            proof = self.call("integration", "verify", "--target", "refs/heads/release-smoke", "--source", "T001",
                              "--review", str(review), "--command", "python3 -B -m unittest -v")
            assert before == snapshot(source)
            result = {"integration": integration, "proof": proof,
                      "status": self.call("integration", "status", owner=False), "preservation": self.preserved()}
        elif action == "finish":
            integration = self.call("integration", "status", owner=False)
            assert integration["eligible"], "Combined evidence must still qualify"
            reconciled = self.call("reconcile")
            statuses = {manager: self.call("status", manager=manager, owner=False)
                        for manager in ("alpha", "beta")}
            for status in statuses.values():
                assert not any(task["alive"] for task in status["observed"]["tasks"])
            assert statuses["alpha"]["tasks"][0]["state"] == "done"
            assert statuses["beta"]["tasks"][0]["state"] == "queued"
            result = {"integration": integration, "reconciled": reconciled,
                      "statuses": statuses, "preservation": self.preserved()}
            # Only the fixture's dedicated server, after runtime acceptance has
            # stopped all matching workers. Retain Git trees, state and evidence.
            subprocess.run([str(self.directory / "bin/tmux"), "kill-server"], env=self.env, check=True)
            result["dedicated_tmux_server_stopped"] = True
        else:
            raise ValueError(action)
        save(evidence / (action + ".json"), result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "spawn", "inspect", "trust", "correct", "verify", "integrate", "finish"))
    parser.add_argument("--run", type=Path)
    parser.add_argument("--agent", choices=("codex", "claude"), default="codex",
                        help="prepare only: the real provider recorded in run.json")
    parser.add_argument("--confirm-trust", action="store_true", help="Explicit human authorization for native folder trust")
    args = parser.parse_args()
    if args.action == "prepare":
        if args.run:
            parser.error("prepare allocates a fresh temporary folder; omit --run")
        directory = Path(tempfile.mkdtemp(prefix="mm08-real-provider-", dir="/tmp"))
        result = Fixture(directory).prepare(args.agent)
    else:
        if not args.run or not (args.run / "run.json").is_file():
            parser.error("supply the explicit --run folder returned by prepare")
        result = Fixture(args.run).action(args.action, confirm_trust=args.confirm_trust)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
