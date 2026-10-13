"""Claude Code interactive CLI adapter; keep native permission checks."""


def command(executable, worktree, writable_dirs, prompt):
    # Repeated flags avoid the variadic --add-dir consuming the positional prompt.
    argv = [executable]
    for directory in writable_dirs:
        argv.extend(["--add-dir", str(directory)])
    return argv + ["--", prompt]
