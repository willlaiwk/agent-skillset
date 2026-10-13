# Runtime reference (v2 namespace, ownership, integration, delivery and migration)

## Current support

The CLI creates isolated manager namespaces, routes workers by complete launch identity, lists managers, and provides read-only inspection. Explicit owner claim/release/takeover, recoverable owner journals, task operation locks and long-verification fencing are available. Isolated integration init/status/verify, combined evidence, a shared local delivery gate and explicit v1 migration are available. Deterministic composition is validated through migration, fresh acceptance, dependent work, handoff and competing delivery. On 2026-10-12, real Codex CLI 0.162.1 passed namespaced report/message ack/correction, independent acceptance and isolated integration on macOS; Claude Code 2.1.296 (claude.ai login, host-inherited native `auto` permission mode) passed the same lifecycle the same day; default/manual-approval permission mode was not exercised. This evidence does not validate other provider versions or platforms.

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

`managers` reports corrupt namespaces per entry and preserves them; detected legacy artifacts are diagnostics. V1 `.manager/state.json` blocks normal v2 operations with explicit migration guidance. Follow the migration workflow below; keep artifacts in place until that workflow moves registered trees. Pending migration blocks normal operations for that root. A completed tombstone with a matching journal/destination retires the legacy layout and allows additional v2 managers.

## Owner and management commands

Claim writes a private 0600 credential at the caller's chosen path, outside manager artifacts and worker worktrees. The file contains root, manager ID, generation and a random token; output/events contain no raw token. An active owner cannot be claimed again, even with the same session label. `init` does not claim. Keep and reuse the same credential across compaction/session recovery; do not put it in the plan or worker prompt.

Every management write requires `--owner-file` or `MANAGER_OWNER_FILE`; the explicit argument wins. Root/manager/generation/token must match the active owner. Query `owner status` with a credential to inspect `credential_valid`; the query remains read-only. Current ownership is a cooperative gate, not an OS sandbox. Claim requires a released owner. Release requires its valid credential, clears the token and increments generation. Takeover requires an active owner at the exact expected generation, a nonempty reason, a new session label and a fresh credential file; it rotates the token and increments generation. Stale timestamps/PIDs never grant takeover. Release/takeover do not stop workers, checks or providers, or undo file changes. The old session must stop direct plan/Git edits as well as CLI writes.

```sh
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json owner release
# Claim a released manager using a new credential path.
manager --root /project --manager-id feature-login owner claim \
  --session-id session-b --credential-file /tmp/session-b.owner.json
# Or explicitly replace an active owner, using the generation from owner status.
manager --root /project --manager-id feature-login owner takeover \
  --expect-generation 3 --reason 'Explicit handoff; previous credential lost' \
  --session-id session-c --credential-file /tmp/session-c.owner.json
```

Owner transitions journal an operation ID before committing owner state, write and sync the exclusive private credential before activation, then record the corresponding event under that ID. `owner status` exposes journal state and credential validity without repairs. If interrupted before activation, the credential stays invalid and must not be reused/overwritten; use a fresh path. If activation succeeded but event writing was interrupted, a valid owner's next management command/reconcile repairs the event exactly once. A subsequent claim/takeover also repairs prior owner journals before transferring control. Generation never resets; an uncommitted credential is diagnosed as `not_committed`, never activated by recovery.

The following management examples illustrate individual commands rather than one sequential lifecycle. After handoff, use the new credential path on every subsequent write.

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

All commands return JSON; errors and failed verification exit nonzero (argument syntax errors use argparse diagnostics). `task` registers without launching. `spawn` can register and launch or start a queued task; it cannot overwrite existing definitions. Registration resolves `--base` to a commit immediately, including for queued tasks. To include newly integrated prerequisites, prepare the committed integration base before registering the dependent task. An existing queued definition, including a migrated one, retains its recorded base; there is no task-edit command. If replanning needs another base, register a fresh task ID and retain the old task/history. Dependencies must already exist and be manager-accepted, with current eligibility, before launch. Their code is not automatically transferred into the next worker's committed base. There is no automatic scheduler.

Writes recheck the credential inside the per-manager registry lock. Short external calls have bounded timeouts and retain launch/message/stop/retry/accept intents for diagnosis. Task management uses a nonblocking `.operation.lock` before the registry lock; a busy target fails immediately. Reconcile skips busy tasks and reports `operation_busy`, while other tasks can progress. Initialization/shared exclude and worktree creation additionally use the common Git maintenance lock. Lock order is common maintenance → task operation (sorted resource paths) → registry → task report; common/registry/report waits are bounded. Read commands do not create/acquire write locks.

Long verify reserves a journal/snapshot under short registry/report locks, holds only its task operation lock across checks, then reloads the latest registry for owner/generation/assignment/operation/review/Git/report/result checks. It preserves concurrent changes to other tasks. Worker reports still use only their report lock. `fenced` and `snapshot_changed` runs exit nonzero, retain logs/diagnostics, and cannot become current verification. A previously committed successful verification remains usable by a new owner after the acceptance recheck.

`owner status.pending_operations` lists registry reservations; a finished fenced run may remain listed until the new owner reconciles. Locks are OS advisory locks released by close/process exit; a lock file's existence does not mean busy, and deleting it is unsafe. Reconcile classifies a pending verify only after acquiring its operation lock and checking its journal/snapshot. Interrupted runs never gain success; unknown side effects and pending accept intents remain diagnostic. Abrupt process death may leave check children running: takeover/reconcile do not prove their quiescence or kill them. Respect busy, inspect/wait or handle children through host authorization before task edits. There is no automatic expiry or manager wakeup.

## State and evidence

```text
.manager/{manager-id}/
  state.json                   v2 registry and task graph
  owner.json                   controller generation and token digest
  owner-operations/{id}.json    owner transition journals without raw tokens
  plan.md                      owner-written outcome/decisions
  events/{task-or-manager}/     namespaced durable events
  inbox/{task}/                messages bound to attempt/assignment
  tasks/{task}/
    brief.md
    assignment.json            root/manager/task/attempt/assignment identity
    status.json                structured worker claim
    result.md
    log.txt
    .operation.lock             advisory task operation lock
    verification/{run}/         operation journal, review, commands, fingerprint
    accept-intent.json           retained acceptance side-effect intent
    accepted.json
    stopped.json
    history/attempt-{n}/        retained report/ack history after retry
  worktrees/{task}/             isolated Git worktree
```

V2 initialization adds `/.manager/` only to shared Git `info/exclude` when needed, preserving the user's `.gitignore` and dirty checkout. Common control data is under `<git-common-dir>/manager-runtime/`; root keys are checked against full canonical roots. Branches are `manager/{project-key}/{manager-id}/tasks/{task-id}`. tmux sessions are `manager-{project-key}-{manager-id}`, with `mgr-{task-id}` windows. Session metadata must match full root/manager before inspection or control; an unmarked or foreign session is not adopted.

Manager and worker state differ. Worker `done` is displayed in observed/reconciled state as `verification`; only `accept` records manager `done` and current acceptance eligibility. `send` clears obsolete completion/question/verification; acknowledgment is separate from terminal paste. `stop` preserves artifacts and cancels unaccepted work. Accepted work cannot be retried.

`verify` requires a valid completion/result, a nonempty independent review, and at least one reviewed command (explicit or `.manager.yml`). Checks run in the task worktree with a per-command timeout (default 600 seconds); full logs/exit codes and before/after fingerprints cover HEAD, working/staged diffs, untracked files, report/result, and review. Nonzero exits, timeouts, or snapshot changes fail verification. Ignored cache output is excluded; submodule dirty contents are not deeply fingerprinted and require independent inspection.

`accept` rechecks identity, attempt/assignment, snapshot and review, stops the matching worker, then checks for shutdown-time changes. This validates evidence consistency, not review quality. It accepts isolated task results only. Manager still owns integration and delivery under repository/user authorization, using its dedicated integration tree and combined verification below. Do not integrate concurrent managers into the user's shared checkout.

## Isolated integration and combined verification

```sh
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  integration init --base COMMITTED_BASE
# Integrate current accepted work in the returned tree using authorized Git commands.
# Commit the reviewed candidate; retain the accepted source trees unchanged.
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  integration verify --target refs/heads/release --source T001 --source T002 \
  --review /tmp/combined-review.md --command 'pnpm test' --command 'pnpm typecheck'
manager --root /project --manager-id feature-login integration status
manager --root /project --manager-id feature-login integration status --verification RUN_ID
```

`integration init` requires an explicit committed base and the active owner. It creates `.manager/{ID}/integration/` with branch `manager/{project-key}/{ID}/integration`, recording the resolved base/identity in `integration.json`. Repeating the same base checks identity and returns `initialized: false` without reset, checkout edits or a new initialization event. A different base, unregistered existing branch/tree, or foreign registration is rejected. Creation intent is durable before Git worktree creation; interrupted init resumes only if there are no side effects yet, or the matching tree/ref exists cleanly at the original base. Partial/changed side effects remain diagnostic. Main checkout dirty/staged/untracked files stay in place.

The manager transfers reviewed accepted commits or task-owned dirty/untracked changes using normal repository tools under existing authorization, then deliberately commits the combined candidate. No runtime command automatically stages/imports/merges sources, resolves conflicts, pushes or updates a target. Dependent workers can use this committed integration branch as `spawn --base`; acceptance does not put source code in a later worker automatically. Dependency launch now rechecks accepted source evidence/fingerprint before creating its worktree.

`integration verify` accepts one or more distinct same-manager current accepted task IDs, an independent nonempty review and reviewed check commands (explicit or shared verification configuration). It rechecks each source's attempt/assignment, accepted marker, verification record/review, HEAD and fingerprint; dirty accepted content is allowed only while that original snapshot is unchanged. Review must explain how sources map to the candidate: snapshot checks do not prove integration adequacy.

Candidate must be committed and clean, including staged/untracked files and nested submodule content, with no merge/rebase/cherry-pick/revert/bisect/sequencer in progress. Submodules must be initialized at their committed revisions. Ignored caches may be generated by checks. Target must be an existing **full direct local branch ref** pointing directly to a commit, outside manager/runtime/backup namespaces, and an ancestor of the candidate. Symbolic refs, tags, remote refs, missing refs and divergent targets fail. Verification can prepare against a checked-out branch without changing it; the final delivery gate below rejects checked-out targets.

Control files stay outside the Git tree:

```text
.manager/{ID}/
  .integration.operation.lock          nonblocking advisory resource lock
  integration.json                    creation intent/base/identity/current run/hash index
  integration/                        candidate Git worktree
  integration-verification/{RUN_ID}/   operation.json, review.md, record.json, check logs
```

Combined checks hold only `.integration.operation.lock`; short registry/source report locks protect reservation and final snapshots. Common maintenance is held only for creation, never across checks. Other tasks/managers and worker reports can continue. Same-integration management fails busy; owner handoff remains possible. Finalization reloads current state and metadata, rechecks generation/token, operation ID/journal, candidate/target/source/review, and preserves concurrent task writes. Fenced or changed runs keep diagnostics and exit nonzero without current qualification.

`integration status` is read-only and returns `eligible` for retained **evidence** after rechecking the committed record hash and current snapshots. It also appears under project `status.integration` and `reconcile.integration`. Changing candidate, target, source acceptance/content or review invalidates eligibility; an old run is not refreshed by recomputing its fingerprint. Completed unchanged evidence survives takeover. Failed checks/timeouts/interrupted runs never gain eligibility from their journal: the owner must complete a new verify. Reconcile skips a busy integration or, after acquiring its resource lock, checks the pending journal/snapshot and records interrupted/fenced diagnostics. Quiesce surviving check children separately before editing the tree; do not delete locks.

`eligible: true` does not mean delivered or authorized to deliver. Use the gate below only within existing delivery authorization. External push/PR workflows remain separate.

## Local delivery and recovery

```sh
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  deliver --verification COMBINED_RUN_ID
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json reconcile
```

`deliver` only uses the recorded successful combined verification for that manager. It has no candidate/target override, force option, branch creation, push or PR creation. It fast-forwards an existing local target only when **no registered worktree has it checked out**, including missing, locked or prunable entries. Detached worktrees do not check out a branch. For a checked-out main branch, keep the committed candidate and use the repository's existing authorized PR/MR or handoff workflow; that external workflow is not a runtime receipt.

Initial evidence checks happen outside common locks. The final gate takes canonical common `maintenance.lock`, common `delivery.lock`, the manager's integration operation lock, then registry and source report locks. It reloads owner/state and rechecks the committed evidence hash, clean candidate, source acceptance/fingerprint, review, target type/OID/ancestry and complete worktree inventory. Locks wait at most five seconds each; the integration operation lock fails busy immediately. Checks, user decisions and Git integration stay outside the common gate. Different linked roots share these common locks.

Before ref changes, the gate durably writes `<git-common-dir>/manager-runtime/deliveries/{ID}/intent.json` with root/manager/generation, verification/evidence hash, old/new OIDs, target/candidate refs, receipt ref and observed inventory. ID is stable for canonical root/manager/verification. One `git update-ref --stdin` transaction, using explicit `no-deref`, verifies candidate OID, updates target with expected old OID, and creates `refs/manager-runtime/deliveries/{ID}`. Any expected-ref mismatch aborts all three operations. Unknown existing receipt refs are refused. Common `result.json` and `.manager/{ID}/delivery/{DELIVERY_ID}.json` record completion. Receipt refs/journals are retained; no automatic cleanup runs.

`reconcile.deliveries` diagnoses each of this manager's intents under the same short gate, without automatically updating refs. A matching direct receipt proves `committed`, even if target/candidate/source later change. A missing receipt with target still at old OID yields `not_committed`; a `deliver` retry must pass all final checks again. Wrong/symbolic/lost completed receipts yield `ambiguous`; a missing receipt with a changed/missing/symbolic target yields `external_change`. Neither state guesses success from target equality or automatically rewrites refs. Explicit transaction rejection is retained so an externally raced receipt cannot later become proof of success. A completed retry returns the original receipt without re-delivery. Damaged intent/evidence or unsafe paths are errors; busy delivery reconciliation is reported as `operation_busy` while task reconciliation can continue.

A stale target requires deliberate integration of the latest target and a **new** combined verification. Owner credentials and evidence are consistency checks, not new authorization. Git advisory locks do not stop external tools: during the short gate, participants must coordinate worktree creation/checkout and direct/symbolic ref-type changes through common maintenance. Expected OID detects external OID races but cannot prevent a same-OID symbolic conversion or external checkout race. The runtime does not claim atomicity across Git refs and worktree registration.

## Explicit v1 migration

```sh
manager --root /project migrate --manager-id feature-login --dry-run
# After stopping all legacy management writes, providers and check children:
manager --root /project migrate --manager-id feature-login \
  --expect-source SOURCE_SHA256 --source-quiesced
# If interrupted, use the ID in .manager/.migration.json / the common journal:
manager --root /project migrate --manager-id feature-login \
  --resume MIGRATION_ID --source-quiesced
manager --root /project --manager-id feature-login owner claim \
  --session-id session-a --credential-file /tmp/session-a.owner.json
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json reconcile
```

The destination selector must be explicit, either globally or on `migrate`; conflicting selectors fail. Dry-run returns inventory, `source_sha256`, ref/path mapping and blockers without creating locks, changing Git/ignore files or stopping panes. The hash covers raw controls, file modes, tracked/staged/untracked/ignored contents, symlink values, index/private Git metadata and the observed pane inventory. Changing source data requires a fresh preview. Dry-run on a pending migration reports its stored inventory and resume ID rather than claiming a new source snapshot.

`--source-quiesced` asserts that every legacy Session, provider and surviving child has stopped writing. It does not stop them or prove their absence by PID/time. Known live panes, unknown panes even when dead, busy v1 locks, unsafe control symlinks, unsupported schemas, unknown task/worktree ownership, existing destination/ref, missing/locked/prunable trees, Git operations and submodules block migration. The v1 tmux session must be inspectable; tmux is required, even though migration never starts a provider. Dirty/staged/untracked/ignored worktree files are supported. Actual execution holds common maintenance → v1 registry → sorted task report locks and rechecks snapshots; external writers must honor the cooperative quiescence prerequisite.

Durable data lives outside the source at `<git-common-dir>/manager-runtime/migrations/{project-key}/{migration-id}/journal.json` and `backup/`. Journal phases are `preflight → backed_up → refs_prepared → worktrees_moved → data_converted → validated → completed`; ref/move/switch/copy intents and result fingerprints make interrupted effects reviewable. Backup preserves raw controls/human files, complete tree contents and modes, symlink values, each private Git directory/index, plus historical commit and staged-blob objects in a verified `objects.pack`/`objects.idx`. Unique `refs/manager-backup/migrations/...` pins retain those objects. Backup trees omit their active `.git` pointer; its original bytes are saved separately under `worktree-pointers/` so the backup cannot act as another handle to the live index.

Old task refs remain at their original OIDs. New `manager/{project-key}/{ID}/tasks/{T}` refs are created transactionally at the same commits. Git moves linked worktrees into the namespace; switching only symbolic HEAD to the identical-OID branch preserves the original index and tree bytes. No reset, stash, force or source ref deletion runs. Queued attempt-zero tasks have no new worktree until launch. Unknown ordinary source files are retained. Original controls remain retired history at the source, and raw copies are available in `.manager/{ID}/history/v1/` and each task's `history/v1/`; briefs/logs/events are not rewritten to update old commands.

All current acceptance and verification fields are cleared. Old accepted evidence becomes `accepted_history` with hashes. Valid completed results become `verification` with `reverify_required`; interrupted or damaged completion becomes `failed`. Existing failed/cancelled tasks stay so, while queued tasks remain queued. Historical acknowledgments remain visible but current acks are empty. Converted `origin: migration` assignments have `reporting_enabled: false`: managers can independently verify retained valid completion, but workers cannot report/ack with that identity. Only a new spawn/retry enables reporting with a fresh assignment. Dependency/integration gates require new current acceptance; old prompts and provider conversations cannot resume as v2 workers.

Completion writes a v2 migration tombstone to the old `.manager/state.json`, releases the new owner, and binds marker/journal/destination. Old v1 init/load fail; old paths do not route reports into v2. After any interruption, resume only the recorded migration ID with the same quiescence assertion. Changes to source, moved trees, refs, backup or converted artifacts cause an error with both sides preserved. No automatic rollback, cleanup, repair or ref adoption runs. Once completed, repeating `migrate` for the same destination is a zero-write no-op after verifying identity and immutable backup/pins; it permits subsequent legitimate v2 task changes. Preserve all history and backup refs for deliberate recovery.

### Continue from migrated acceptance to dependent work

After migration and explicit claim, inspect the retained result/diff and write a new independent review. This example assumes `T001` has a valid migrated completion, `refs/heads/release` already exists, and `T004` is a fresh task ID. Replace the uppercase placeholders with the paths/ref returned by the CLI and use checks appropriate to the project.

```sh
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  verify T001 --review /tmp/T001-review.md --command 'python3 -m unittest'
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json accept T001
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  integration init --base refs/heads/release
# In INTEGRATION_TREE, transfer the reviewed accepted snapshot and commit it.
# A cherry-pick alone does not include dirty/staged/untracked accepted content.
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  spawn --id T004 --title 'Dependent change' --brief /tmp/T004.md \
  --depends-on T001 --base INTEGRATION_BRANCH
# Supervise T004, review its result, then verify and accept its unchanged snapshot.
# Integrate T004 in INTEGRATION_TREE and commit the combined candidate.
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  integration verify --target refs/heads/release --source T001 --source T004 \
  --review /tmp/combined-review.md --command 'python3 -m unittest'
manager --root /project --manager-id feature-login integration status --verification COMBINED_RUN_ID
manager --root /project --manager-id feature-login --owner-file /tmp/session-a.owner.json \
  deliver --verification COMBINED_RUN_ID
```

Delivery requires existing authorization and an un-checked-out target. If another manager delivers first, integrate its latest target into this manager's candidate, resolve any conflicts, commit and run a new combined verification. A handoff uses a fresh owner credential for subsequent writes; unchanged completed evidence can survive it. A run still checking at handoff is fenced and needs a new verification after reconcile. Migration reruns remain no-ops after these v2 changes; they do not reset tasks, ownership or delivery history.

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

From the repository root (development tests are under `tests/`):

```sh
python3 -B tests/test_manager.py
MANAGER_TEST_REAL_TMUX=1 python3 -B tests/test_manager.py
```

Tests use real temporary Git repos with fake providers. Default mode uses fake tmux; real mode uses an isolated temporary socket/server and fake interactive workers, preserving the host's existing tmux server and invoking no models/APIs. Host permission may be needed to create real tmux sockets. These regressions are separate from the dated real-Codex smoke result above; they do not validate authenticated providers by themselves. Real-provider smoke testing uses account usage and preserves native trust/permission checks.
