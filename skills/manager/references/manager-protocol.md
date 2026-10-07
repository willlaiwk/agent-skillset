# Manager protocol

## Planning

Read project instructions before `init`. Initialization creates ignored local state; it does not commit it. Write `.manager/plan.md` with the requested outcome, scope, acceptance criteria, task dependencies, delivery branch/tree, known user changes, decisions, integration progress, and final verification evidence. Use stable task IDs such as `T001`.

Create task briefs using the template. Dependencies must reference previously registered tasks, which keeps the MVP graph acyclic. `task` registers queued work; `spawn` starts work only after dependencies are manager-accepted. The manager schedules runnable tasks itself; there is no background scheduler.

Every worker gets a private worktree. Worktrees are created from `--base` (default current committed `HEAD`), not uncommitted changes. A dependent worker does not automatically receive a dependency's branch: prepare a committed integration ref or pass an explicit base containing the required commits. Record that choice in the plan.

## Supervision loop

1. Run `status` or `reconcile` and read changed reports/events. Only manager state `done` counts as accepted.
2. For `needs_manager`, inspect the question and repository evidence, then `send` an answer. If user judgment is essential, record `escalate`, ask the user, and send their answer when available.
3. Inspect the pane only for diagnostics, including native permission/trust/login prompts. Do not auto-confirm a prompt. A persisted inbox survives failed delivery; `send --inbox-only` avoids pasting into a busy UI. Only send to the terminal when the worker is ready; `inbox` lets you inspect unacknowledged messages.
4. For `verification`, read `result.md`, inspect the diff from the recorded base, and compare work to each acceptance criterion. Inspect commands before running project-configured checks. Save an independent review and run `verify --review ... --command ...`.
5. On failure, `send` a focused correction to the existing session. This invalidates verification. If dead, diagnose, `retry`, and use retained result/worktree/history as context. Two restarts after the initial attempt are the default limit.
6. `accept` requires a successful verification record bound to current worktree contents, report, attempt, and review. It stops the worker and records task acceptance. Integrate using ordinary repository tools, resolve conflicts within scope, and run combined checks in the delivery tree.

The runtime enforces a structural verification gate, not semantic correctness: you remain responsible for the adequacy of review and commands. For a research-only task, independently check cited evidence and use an appropriate artifact validation command rather than inventing irrelevant code tests.

## Recovery

`reconcile` reads reports, inventories project-owned tmux windows and registered Git worktrees, flags stale reports (default 15 minutes), and marks missing/crashed workers or worktrees as failures. Stale means inspect, not automatically kill. It reports orphan panes/directories but does not kill or delete them. Corrupt reports produce explicit errors; they are not interpreted as success.

An interrupted launch is recovered from persisted session/window names. Reconcile can rediscover its pane. `retry` preserves the branch and worktree, increments an attempt generation, and rejects reports from old attempts. A retry begins a fresh interactive conversation with the original brief, prior result, and correction context; it does not promise provider conversation resumption after a process dies.

Do not remove state, branches, logs, or worktrees during recovery. If state is corrupt or a project moved, stop and repair from preserved artifacts with appropriate authorization; do not initialize over it. The runtime does not recreate missing state automatically or claim to restore unrecorded user intent.
