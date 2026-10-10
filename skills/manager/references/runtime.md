# Runtime reference (v2 namespace, MM-02)

## Current support

The CLI creates isolated manager namespaces, routes workers by complete launch identity, lists managers, and provides read-only inspection. Basic `owner claim` and credential checks are available so management commands can run under an explicit owner. Owner release/takeover, long-operation handoff, integration/delivery commands, and migration are still pending. Keep the credential file: there is currently no takeover command if it is lost. Do not use this version to migrate v1 data or claim that the complete multi-manager design is implemented.

Python 3.9+ and Git on a POSIX host are required. Starting workers additionally requires tmux and an installed, authenticated `codex` or `claude`. Default operation uses the Python standard library; YAML `.manager.yml` requires PyYAML in the same interpreter. JSON syntax in that file needs no additional dependency. Missing YAML support is an explicit error, never silently ignored.

## Start, select, and inspect

Supply the project checkout as `--root` before the subcommand; workers use that same root, not their own worktree. Examples assume `manager` resolves to `scripts/manager`; otherwise use `python3 /absolute/path/to/scripts/manager`.

```sh
manager --root /project init
manager --root /project --manager-id feature-login init
manager --root /project managers
manager --root /project --manager-id feature-login owner status
manager --root /project --manager-id feature-login owner claim \
  --session-id session-a --credential-file /tmp/session-a.owner.json
manager --root /project --manager-id feature-login status
manager --root /project --manager-id feature-login peek T001
manager --root /project --manager-id feature-login inbox T001
manager --root /project --manager-id feature-login events
```

No-ID `init` always creates a new ID and returns `manager_id`, canonical root, home/state paths, schema version, initial released owner, and per-manager worker limit. Save and display that ID. Explicit-ID `init` creates or opens that manager without claiming ownership or reconciling. A missing or damaged state/layout is an error, never an invitation to recreate artifacts. Later commands require a selector even if only one manager exists. There is no global current-manager pointer.

IDs use 1–64 lowercase ASCII letters, digits, `_`, or `-`, starting with a letter/digit. Runtime directory names are reserved; separators, dots, uppercase aliases, and symlink control paths are rejected. Identity is `(canonical project root, manager_id)`; different linked checkouts are different manager roots even when they share the repository.

`managers`, `owner status`, `status`, `peek`, `events`, and `inbox` do not write state, events, ignore files, or lock files. `status.tasks` is persisted manager state; `status.observed` contains live diagnostic tasks/notices/orphans. An observed completion is still a worker claim, not acceptance. Use owner-only `reconcile` to persist observations. `peek` reads the matching pane without reconciliation. Concurrent changes to files read by inspection return an inconsistent/busy error instead of silently repairing data. Git inspection disables optional index refresh writes.

`managers` reports corrupt namespaces per entry and preserves them; detected legacy artifacts are diagnostics. V1 `.manager/state.json` blocks normal v2 operations with explicit migration guidance. Migration is not yet implemented: keep the original files and use an appropriate previously installed v1 runtime if continuing legacy work; do not move them manually or initialize over them.

## Owner and management commands

Claim writes a private 0600 credential at the caller's chosen path, outside manager artifacts and worker worktrees. The file contains root, manager ID, generation and a random token; output/events contain no raw token. An active owner cannot be claimed again, even with the same session label. `init` does not claim. Keep and reuse the same credential across compaction/session recovery; do not put it in the plan or worker prompt.

Every management write requires `--owner-file` or `MANAGER_OWNER_FILE`; the explicit argument wins. Root/manager/generation/token must match the active owner. Query `owner status` with a credential to inspect `credential_valid`; the query remains read-only. Current ownership is a cooperative gate, not an OS sandbox. Release/takeover and failure-recovery refinements belong to MM-03; do not attempt a second controller for the same ID.

```sh
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  task --id T001 --title 'Inspect auth flow' --kind research --brief /tmp/T001.md
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  spawn --id T001
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  spawn --id T002 --title 'Login validation' --brief /tmp/T002.md \
  --depends-on T001 --base integration-ref
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  send T002 'Cover the empty state.'
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  send T002 --message-file /tmp/review.md --inbox-only
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  verify T002 --review /tmp/manager-review.md --command 'pnpm test'
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json accept T002
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json stop T002
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json retry T002 --agent claude
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json reconcile
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  escalate T002 --reason 'Product behavior needs user input'
```

All commands return JSON; errors and failed verification exit nonzero (argument syntax errors use argparse diagnostics). `task` registers without launching. `spawn` can register and launch or start a queued task; it cannot overwrite existing definitions. Dependencies must already exist and be manager-accepted, with current eligibility, before launch. Their code is not automatically transferred into the next worker's committed base. There is no automatic scheduler.

Writes serialize with a per-manager POSIX lock. Initialization/shared exclude and worktree creation additionally use the common Git maintenance lock; waits are bounded. Worker reports use a separate task lock, so they can be submitted during long verification. The current verify still holds the registry lock across checks: moving those checks outside the lock with operation fencing is pending MM-03. There is no automatic expiry, takeover, or manager wakeup.

## State and evidence

```text
.manager/{manager-id}/
  state.json                   v2 registry and task graph
  owner.json                   controller generation and token digest
  plan.md                      owner-written outcome/decisions
  events/{task-or-manager}/     namespaced durable events
  inbox/{task}/                messages bound to attempt/assignment
  tasks/{task}/
    brief.md
    assignment.json            root/manager/task/attempt/assignment identity
    status.json                structured worker claim
    result.md
    log.txt
    verification/{run}/         independent review, commands, fingerprint
    accepted.json
    stopped.json
    history/attempt-{n}/        retained report/ack history after retry
  worktrees/{task}/             isolated Git worktree
```

V2 initialization adds `/.manager/` only to shared Git `info/exclude` when needed, preserving the user's `.gitignore` and dirty checkout. Common control data is under `<git-common-dir>/manager-runtime/`; root keys are checked against full canonical roots. Branches are `manager/{project-key}/{manager-id}/tasks/{task-id}`. tmux sessions are `manager-{project-key}-{manager-id}`, with `mgr-{task-id}` windows. Session metadata must match full root/manager before inspection or control; an unmarked or foreign session is not adopted.

Manager and worker state differ. Worker `done` is displayed in observed/reconciled state as `verification`; only `accept` records manager `done` and current acceptance eligibility. `send` clears obsolete completion/question/verification; acknowledgment is separate from terminal paste. `stop` preserves artifacts and cancels unaccepted work. Accepted work cannot be retried.

`verify` requires a valid completion/result, a nonempty independent review, and at least one reviewed command (explicit or `.manager.yml`). Checks run in the task worktree with a per-command timeout (default 600 seconds); full logs/exit codes and before/after fingerprints cover HEAD, working/staged diffs, untracked files, report/result, and review. Nonzero exits, timeouts, or snapshot changes fail verification. Ignored cache output is excluded; submodule dirty contents are not deeply fingerprinted and require independent inspection.

`accept` rechecks identity, attempt/assignment, snapshot and review, stops the matching worker, then checks for shutdown-time changes. This validates evidence consistency, not review quality. It accepts isolated task results only. Manager still owns integration under repository/user authorization, using a separate isolated delivery/integration tree and combined verification; dedicated integration/delivery CLI support is pending. Do not integrate concurrent managers into the user's shared checkout.

## Worker identity and messages

Launch prompt, assignment, and environment carry canonical root, manager ID, task ID, attempt and random assignment ID. Every launch/retry changes assignment ID. Workers only report and read their own inbox; explicit CLI identity must match the launch environment. `MANAGER_OWNER_FILE` is removed from the child environment. Additional writable directories are limited to that manager's task/inbox/event directories, never the owner credential or full registry.

```sh
manager --root /project --manager-id feature-login report T001 \
  --attempt 1 --assignment-id ASSIGNMENT_ID --state working --summary 'Implementing'
manager --root /project --manager-id feature-login inbox T001
```

Assignment ID can default from `MANAGER_WORKER_ASSIGNMENT`; an explicit conflicting ID fails. Reports with no selector, wrong manager, stale attempt/assignment, disabled assignment, or foreign ack are rejected before report/event writes. Operator inbox reads need no owner token; worker inbox reads additionally check the active launch identity. Inbox entries expose `current_attempt`; old messages remain history and cannot be acknowledged as new-attempt delivery. Prior acknowledgment is retained in attempt history after retry.

`send` saves a durable message before best-effort bracketed tmux paste/Enter. A busy TUI or native permission/trust/login prompt may intercept it; inspect readiness or use `--inbox-only`. Only a valid worker `report --ack MESSAGE_ID` proves receipt. Pane text is diagnostic evidence, never a machine completion state.

Adapters still use interactive `codex [prompt]` / `claude [prompt]`, preserving native permission checks and Codex workspace-write. Their provider flags are unchanged from the MVP; see the [Codex CLI reference](https://developers.openai.com/codex/cli/reference) and [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference) when diagnosing version differences. Worktrees/identities are cooperative isolation; workers run as the host user and share Git metadata. Host sandbox/approval rules remain separate.

## Configuration and recovery

`.manager.yml` is shared project configuration. Unsupported sections/keys/values fail. Defaults are four workers **per manager**, 15-minute stale reporting, two restarts after the initial attempt, auto provider selection (Codex then Claude), worktree isolation, and no verification commands. Two managers can jointly exceed four workers; there is no repository-wide capacity cap. Status exposes active/max counts and their manager scope.

```yaml
manager:
  max_workers: 4
  stale_seconds: 900
  max_retries: 2
agents:
  default: auto
  research: claude
  implementation: codex
git:
  isolation: worktree
  auto_commit: true
  auto_merge: false
  auto_push: false
verification:
  test: pnpm test
  typecheck: pnpm typecheck
  lint: pnpm lint
escalation:
  product_decisions: ask
  architecture: recommend_then_ask
  destructive_actions: always_ask
```

A task's explicit agent overrides role/default routing. Roles are research/implementation/review/verification. Auto-commit is guidance under repository policy, not blanket staging. Other isolation modes, auto-merge/push, and alternative escalation modes remain unsupported.

Owner `reconcile` inventories only its namespace, flags stale/missing/corrupt workers and registrations, and preserves orphans. It never adopts another manager's worktrees/panes. A valid completion can be independently verified after a worker exits. Stale means inspect, not kill. Retry needs a failed/cancelled task, valid retained worktree, and remaining retry allowance; it starts a new interactive conversation, keeps history/results/messages, and rejects obsolete reports. Missing/corrupt state or moved projects require deliberate repair. Do not delete artifacts, manually rewrite credentials, or reinitialize over them.

## Validation

From the skill directory:

```sh
python3 scripts/test_manager.py
MANAGER_TEST_REAL_TMUX=1 python3 scripts/test_manager.py
```

Tests use real temporary Git repos with fake providers. Default mode uses fake tmux; real mode uses an isolated temporary socket/server and fake interactive workers, preserving the host's existing tmux server and invoking no models/APIs. Host permission may be needed to create real tmux sockets. Deterministic or real-tmux fixture success does not replace the pending real-provider smoke test.
