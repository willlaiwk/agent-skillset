# Manager Skill

A local engineering manager for coding agents. The Manager plans repository work, delegates focused tasks to Codex or Claude Code workers, supervises their questions and corrections, and independently verifies and integrates their results.

The user works with one primary agent. Worker completion remains a claim until the Manager reviews and verifies it.

## Repository Layout

This repository develops and distributes one skill, named `manager`. The skill entry point and its runtime resources live at the repository root:

```text
manager-skill/
├── SKILL.md                 Agent instructions and invocation scope
├── agents/                  Agent UI metadata
├── scripts/
│   ├── manager              Public runtime CLI
│   └── lib/                 Runtime helpers and provider adapters
├── references/              Runtime usage and management protocols
├── templates/               Worker task brief
├── tests/                   Behavioral tests, document checks and opt-in probes
└── docs/                    Design, specifications, decisions and validation evidence
```

Read [SKILL.md](SKILL.md) for the Manager workflow and [the runtime reference](references/runtime.md) for commands, configuration and operational limits. Developers should start with [docs/README.md](docs/README.md), [current progress](docs/progress.md) and [the task list](docs/tasks.md).

## Requirements and Installation

The runtime requires Python 3.9+, Git, tmux, and an installed, authenticated `codex` or `claude` CLI on a POSIX host. Real-provider validation is recorded for macOS; other platforms need their own evidence. The default runtime uses the Python standard library; YAML configuration additionally requires PyYAML.

Make the complete repository checkout available as the `manager` skill directory through your coding agent's supported skill-loading mechanism. Keep `SKILL.md`, `agents/`, `scripts/`, `references/` and `templates/` together. The skill entry point is at the checkout root; there is no nested `skills/manager/` package. `docs/` and `tests/` support development and are not required to execute the installed runtime.

Check the CLI from the repository root:

```sh
python3 scripts/manager --help
```

Then ask your coding agent:

```text
Use the manager skill to add Google OAuth to this project's login page.
Include loading and error states, add relevant tests, and independently
verify the integrated result before reporting completion.
```

The repository name is `manager-skill`; the skill name and invocation remain `manager`.

## Current Capabilities

The local runtime provides:

- Persistent interactive Codex and Claude Code worker sessions in tmux, with a separate Git worktree for each worker.
- Explicit manager IDs, isolated task state and routing, and read-only inspection.
- Owner claim/release/takeover and generation fencing, with long checks outside the registry lock.
- Task dependencies, per-manager worker limits, structured reports, durable messages and acknowledgments.
- Independent verification records and acceptance gates bound to reviewed results.
- Per-manager integration worktrees and combined evidence bound to accepted sources, candidate and target snapshots.
- A shared local delivery gate with expected-OID transactions and recoverable receipts, limited to existing branches that no registered worktree has checked out.
- Persisted diagnostics, bounded retries, and explicit v1 migration with backups and forward resume.

Runtime data belongs to the managed project's Git root under `.manager/{manager-id}/`, separately from this repository's development documents. Initialization uses shared Git `info/exclude` and preserves the user's `.gitignore`. Save the returned ID, explicitly claim ownership, and keep the private owner credential outside worker artifacts.

Workers start from committed Git refs. Acceptance does not automatically transfer prerequisite code into later workers; prepare a committed integration base before registering dependent tasks. Delivery follows existing user/repository authorization and provides no push or PR creation. Migration requires a zero-write preview, matching source hash and quiesced legacy writers; historical acceptance requires fresh verification. See the [migration workflow](references/runtime.md#explicit-v1-migration).

The runtime currently uses polling. Automatic scheduling, event-triggered wake-up, automatic verification and expanded routing/retry policies remain Phase 2 work.

Deterministic composition and real Codex CLI 0.162.1 and Claude Code 2.1.296 lifecycles through acknowledgment, correction, independent acceptance and isolated integration are validated on macOS. Claude was validated under the host's native auto permission mode. See [the provider evidence](docs/reviews/MM-08-validation.md) for exact versions and limits.

## Development and Validation

Run behavioral tests and maintained documentation checks from the repository root:

```sh
python3 -B tests/test_manager.py
python3 -B tests/validate_docs.py
```

To exercise a real, isolated tmux server with fake workers:

```sh
MANAGER_TEST_REAL_TMUX=1 python3 -B tests/test_manager.py
```

Behavioral tests use temporary Git repositories and fake providers, with no model API calls. [tests/real_provider_smoke.py](tests/real_provider_smoke.py) is an opt-in real-provider fixture; launching its worker consumes account usage and preserves native trust/permission checks. Follow [the smoke procedure](docs/reviews/MM-08-validation.md) when a real-provider run is needed. [tests/probe_git_primitives.py](tests/probe_git_primitives.py) provides the historical Git mechanism probe separately from runtime tests.

Keep runtime code in `scripts/`, behavioral verification in `tests/`, agent-facing guidance in `references/`, and development specifications and evidence in `docs/`. Follow [the documentation workflow](docs/README.md) for new functionality and update runtime guidance when supported behavior changes.
