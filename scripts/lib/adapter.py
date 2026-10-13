"""Keep agent detection and command construction behind one interface."""
import shutil

from . import claude, codex


def resolve(name):
    candidates = ["codex", "claude"] if name == "auto" else [name]
    for candidate in candidates:
        if candidate not in ("codex", "claude"):
            raise ValueError("Unsupported agent: " + candidate)
        executable = shutil.which(candidate)
        if executable:
            return candidate, executable
    raise ValueError("No installed worker CLI found: " + ", ".join(candidates))


def command(name, executable, worktree, writable_dirs, prompt):
    module = {"codex": codex, "claude": claude}[name]
    return module.command(executable, worktree, writable_dirs, prompt)
