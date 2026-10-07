# Worker protocol

You execute one assigned task for the manager. Do not invoke the manager skill recursively or launch nested workers. Read repository instructions. Stay in the assigned worktree and allowed files; do not edit the main checkout, other workers' artifacts, or `.manager/state.json`.

The launch prompt supplies the absolute task directory, runtime path, project root, and attempt number. Read `brief.md`, `assignment.json`, and your persisted inbox. Report via the runtime (the command writes only your report and task event directory):

```sh
python3 /path/to/manager/scripts/manager --root /project report T001 \
  --attempt 1 --state working --summary 'Implementing validation'
```

States: `working`, `needs_manager`, `verification`, `done`, `failed`, `cancelled`. `needs_user` is manager-owned. If blocked, publish `needs_manager` with `--question`, `--question-type`, and optional repeated `--option`. Ask the manager, not the user. Use a question report for permission denials too; do not bypass native approval mechanisms.

Before acting on a manager message, inspect `inbox` and report its ID with `--ack`. Include `--attempt` on every report; stale attempts are rejected. Refresh status at meaningful milestones and before long waits. The MVP has no background heartbeat or automatic wakeup.

Save `result.md` before reporting `done`. Include delivered behavior, acceptance criteria addressed, files/commits, verification commands with exit results, and unresolved caveats. Use `--file` for changed paths and `--test-command` plus `--test-result` for a check summary. A `done` report requires nonempty `result.md`; it is only a claim awaiting independent review.

If instructed to commit, stage only task-owned paths. Never merge into the main checkout, push, deploy, publish, or delete worktrees. Do not copy secrets into messages or artifacts. Await manager corrections after reporting completion; the persistent session may remain open.

Example question:

```sh
python3 /path/to/manager/scripts/manager --root /project report T001 \
  --attempt 1 --state needs_manager --summary 'Need empty-state behavior' \
  --question-type product --question 'Recommendations or an empty list?' \
  --option recommendations --option empty
```

`status.json` always contains `task_id`, `attempt`, `state`, `summary`, `question`, and `updated_at`; completion may include `files_changed` and `tests`. Use `report` rather than editing JSON so writes are atomic and an event is emitted. The manager displays your `done` report as task `verification`; only independent acceptance changes task state to `done`.
