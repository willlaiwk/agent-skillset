# Runtime reference (MVP)

## Requirements and invocation

Use Python 3.9+ on a POSIX host with Git and tmux. Workers require an installed, authenticated `codex` or `claude`. Default operation uses only the Python standard library. YAML `.manager.yml` requires PyYAML in the same Python environment; JSON syntax in that file works without dependencies. Missing YAML support is an explicit error, never a fallback to ignored settings.

Run from a committed Git repository. Supply the main project checkout as `--root` **before** the subcommand; worker commands also use that root, not their worktree. The following examples assume `manager` resolves to this skill's `scripts/manager`; otherwise use `python3 /absolute/path/to/scripts/manager`.

```sh
manager --root /project init
manager --root /project task --id T001 --title 'Inspect auth flow' \
  --kind research --brief /tmp/T001.md
manager --root /project spawn --id T001
manager --root /project spawn --id T002 --title 'Implement login validation' \
  --agent codex --brief /tmp/T002.md --depends-on T001 --base integration-ref
manager --root /project send T002 'Cover the empty state.'
manager --root /project send T002 --message-file /tmp/review.md --inbox-only
manager --root /project inbox T002
manager --root /project peek T002
manager --root /project status
manager --root /project escalate T002 --reason 'Product behavior needs user input'
manager --root /project verify T002 --review /tmp/manager-review.md \
  --command 'pnpm test' --command 'pnpm typecheck' --command 'pnpm lint'
manager --root /project accept T002
manager --root /project stop T002
manager --root /project retry T002 --agent claude
manager --root /project reconcile
manager --root /project events
```

`task` registers work without starting a worker. `spawn` can register and start in one call or launch a registered queued task. Existing task definitions cannot be overwritten. Dependencies must already exist and be manager-accepted before spawning; acceptance does not transfer their code into another task's base. There is no automatic scheduler.

All commands return JSON; errors and failed verification exit nonzero. `status` reconciles first, so it reports live state. `peek` captures up to 200 terminal lines for diagnosis. `report` and `inbox` operate without locking the manager registry so workers can report during long checks. Other commands serialize with a project-local POSIX lock; report writes have a separate task lock. Do not run a second manager over a shared plan: the CLI lock serializes operations, not concurrent LLM decisions.

## State and evidence

```text
.manager/
  state.json                   manager registry, task graph, acceptance
  plan.md                      manager-written outcome and decisions
  events/{task-or-manager}/    atomic UUID events, timestamped
  inbox/{task}/               durable messages and delivery metadata
  tasks/{task}/
    brief.md                  copied task brief
    assignment.json           active attempt and absolute paths
    status.json               structured worker claim
    result.md                 worker's evidence
    log.txt                   terminal stream (may omit initial output)
    verification/{run}/       manager review, command logs, record.json
    accepted.json             acceptance marker
    stopped.json              stop marker
  worktrees/{task}/           isolated working tree
```

Initialization appends `/.manager/` to the project's `.gitignore` only if needed. It does not stage/commit that edit. On worktree creation, the runtime also adds the local exclusion to Git's shared `info/exclude`, because uncommitted ignore edits do not enter workers' committed bases. Branches use `manager/{project-hash}/{task}`; sessions use `manager-{project-hash}`. Never delete existing runtime artifacts to recover a task.

Manager state and worker state are distinct. `status.json: done` becomes manager `verification`; only `accept` writes manager `done`. A manager escalation keeps `needs_user` until a response is sent. `send` clears old completion/question state and verification; unacknowledged messages remain discoverable. `stop` cancels unaccepted work while preserving artifacts. Accepted work cannot be retried.

`verify` requires a worker `done` report, a nonempty independent review, and at least one command. Without explicit `--command`, it uses the reviewed configuration's verification commands. It runs shell commands **in the task worktree**, records full output and exit codes, and hashes HEAD, working/staged diffs, untracked files, report, and result before and after. Checks have a per-command timeout (default 600 seconds). Nonzero exits, timeouts, or changes to the snapshot fail verification. Ignored build/cache output is excluded. Dirty submodule contents are not deeply fingerprinted; inspect and verify submodule revisions/content separately or keep them outside delegated scope.

`accept` checks that the snapshot, attempt, and stored review still match, stops the worker, checks for shutdown-time changes, then records acceptance. This gate checks evidence consistency; it cannot judge whether a review or command is meaningful. Integration is manual under the manager's ownership, followed by combined verification in the delivery tree. No automatic merge, push, deployment, or worktree cleanup is implemented.

## Configuration

Read `.manager.yml` before use; invalid values and unsupported keys fail explicitly. Settings are reloaded on each relevant operation. Example:

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

Defaults: four workers, a 15-minute stale threshold, two restarts after the initial attempt, `auto` provider selection (Codex then Claude), worktree isolation, commit guidance enabled, and no verification commands. A task's explicit `--agent` overrides role/default routing. Configurable roles are `research`, `implementation`, `review`, and `verification`. `auto_commit` is a worker instruction subject to repository/user policy, not an automatic blanket staging operation. The MVP rejects other isolation modes, enabled auto-merge/push, and changes to the documented escalation modes.

## Sessions, permissions, and delivery

The adapters start interactive `codex [prompt]` / `claude [prompt]` in tmux, never `codex exec` or `claude -p`. They preserve normal permission checks; Codex is constrained to `workspace-write`. Each worker is granted additional access only to its task, inbox, and event directories, not the entire manager state. Authentication and CLI settings remain host-owned; research sessions do not receive credentials in their brief. The runtime does not strip the host environment or promise credential isolation.

Provider flags are isolated in `scripts/lib/`. They were checked against installed `--help` and the [Codex CLI reference](https://developers.openai.com/codex/cli/reference) and [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference). Inspect a provider's current help when diagnosing version differences; do not replace native safeguards with bypass flags.

`send` always saves the message, then uses bracketed tmux paste and Enter when a live worker exists. Terminal paste is a best-effort operation: login/trust/permission dialogs or a busy TUI can intercept it. Inspect readiness first, or use `--inbox-only`. Only the worker's report with `--ack MESSAGE_ID` proves receipt. No pane text is treated as a machine state signal.

The worker environment prevents accidental manager-only command invocation. It is cooperative routing, not an access-control boundary: local workers still execute as the host user, and Git worktrees share repository metadata. Respect host sandbox/approval limits independently.

## Recovery and boundaries

`reconcile` inventories panes and Git registrations, discovers an interrupted launch's pane, flags stale reports, and preserves orphans. A worker that disappears before `done` is failed; a valid completion claim can still be independently verified after the process exits. Corrupt reports cannot pass the acceptance gate. Missing worktrees or changed branches are diagnosed rather than recreated destructively.

`retry` starts a fresh session in the existing worktree, preserves logs/results/messages, increments its generation, and rejects old reports. It requires a failed/cancelled task and valid worktree. Diagnose before using it. Missing/corrupt state or a moved project requires deliberate repair; CLI state is not inferred from terminal output. Context/session restarts within the same project preserve recorded work; OS reboot loses tmux processes but retains artifacts for retries.

MVP supervision is polling. Persisted events do not automatically wake a stopped manager. DAG scheduling, background watchers, automatic command inference, richer retry strategies, cleanup, and provider-native dead-session resumption remain later-phase work.

## Runtime validation

From the skill directory, run `python3 scripts/test_manager.py` for behavioral tests with real temporary Git repositories and deterministic fake tmux/providers. Set `MANAGER_TEST_REAL_TMUX=1` to exercise a dedicated real tmux socket with fake interactive workers, including message delivery. Tests use no model/API calls, preserve the host's existing tmux server, and remove only their own temporary fixtures/server.
