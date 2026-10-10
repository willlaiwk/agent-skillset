# Worker protocol

You execute one assigned task for one manager. Do not invoke the manager skill recursively or launch nested workers. Read repository instructions. Stay in the assigned worktree and allowed files; do not edit the main checkout, other managers/workers' artifacts, registry, or owner credentials.

The launch prompt supplies absolute task/runtime paths and canonical root, manager ID, task ID, attempt and assignment ID. Read `brief.md`, `assignment.json`, and your persisted inbox. Use that root/manager selector on every command; same-named tasks in other managers are unrelated. Report via the runtime (only your report/task events are written):

```sh
python3 /path/to/manager/scripts/manager --root /project --manager-id feature-login report T001 \
  --attempt 1 --assignment-id ASSIGNMENT_ID --state working --summary 'Implementing validation'
```

States: `working`, `needs_manager`, `verification`, `done`, `failed`, `cancelled`. `needs_user` is manager-owned. If blocked, publish `needs_manager` with `--question`, `--question-type`, and optional repeated `--option`. Ask the manager, not the user. Use a question report for permission denials too; do not bypass native approval mechanisms.

Before acting on a manager message, inspect your namespaced `inbox` and report its ID with `--ack`. Only messages with `current_attempt: true` are current instructions; old entries remain history and cannot be acknowledged for a new attempt. Include `--attempt` and assignment ID on every report; the latter may default from `MANAGER_WORKER_ASSIGNMENT`, but an explicit conflicting value fails. Missing selector, wrong root/manager, stale attempt/assignment and foreign ack are rejected. Worker inbox also validates current launch identity. Never supply owner credentials or invoke management commands. Refresh status at meaningful milestones and before long waits; no background heartbeat or automatic wakeup is implemented.

Save `result.md` before reporting `done`. Include delivered behavior, acceptance criteria addressed, files/commits, verification commands with exit results, and unresolved caveats. Use `--file` for changed paths and `--test-command` plus `--test-result` for a check summary. A `done` report requires nonempty `result.md`; it is only a claim awaiting independent review.

If instructed to commit, stage only task-owned paths. Never merge into the main checkout, push, deploy, publish, or delete worktrees. Do not copy secrets into messages or artifacts. Await manager corrections after reporting completion; the persistent session may remain open.

Example question:

```sh
python3 /path/to/manager/scripts/manager --root /project --manager-id feature-login report T001 \
  --attempt 1 --assignment-id ASSIGNMENT_ID --state needs_manager --summary 'Need empty-state behavior' \
  --question-type product --question 'Recommendations or an empty list?' \
  --option recommendations --option empty
```

`status.json` contains `root`, `manager_id`, `task_id`, `attempt`, `assignment_id`, `state`, `summary`, `question`, `updated_at` and `acks`; completion may include files/tests. Use `report` rather than editing JSON so identity is validated, writes are atomic and a namespaced event is emitted. Your `done` report appears as observed/reconciled `verification`; only independent acceptance changes persisted manager state to `done`.
