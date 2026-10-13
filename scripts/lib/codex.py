"""Codex interactive CLI adapter; do not disable approvals or sandboxing."""


def command(executable, worktree, writable_dirs, prompt):
    argv = [executable, "--cd", str(worktree), "--sandbox", "workspace-write",
            "--no-alt-screen"]
    for directory in writable_dirs:
        argv.extend(["--add-dir", str(directory)])
    return argv + [prompt]
