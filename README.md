# Agent Skillset

Reusable skills for coding agents. This repository packages focused workflows, supporting scripts, and task-specific references to help agents carry engineering work from a request through implementation and verification.

Each skill lives in `skills/<name>/` and provides a `SKILL.md` entry point describing when to use it and how it works. Runtime requirements depend on the selected skill.

## Available Skills

| Skill | Purpose | Requirements |
| --- | --- | --- |
| [Manager](skills/manager/SKILL.md) | Plan repository work, delegate tasks to local Codex or Claude Code workers, supervise questions and corrections, and independently verify their results. | Python 3.9+, Git, tmux, and an installed, authenticated worker CLI on macOS or Linux. |

## Manager

The Manager skill keeps one primary agent responsible for the requested outcome while workers handle focused tasks. It is intended for engineering work that benefits from coordination across multiple tasks.

Its local runtime provides:

- Persistent interactive Codex and Claude Code worker sessions in tmux.
- A separate Git worktree for each worker.
- Explicit manager IDs with isolated task state, worker routing, and read-only inspection.
- Owner claim/release/takeover and generation fencing, with long checks outside the registry lock.
- Task dependencies and configurable worker concurrency limits.
- Structured status reports, durable messages, and message acknowledgments.
- Independent verification records and an acceptance gate that checks whether reviewed results have changed.
- Per-manager integration worktrees and combined evidence bound to accepted sources, candidate and target snapshots.
- A shared local delivery gate with expected-OID transactions and recoverable receipts, limited to existing branches that no registered worktree has checked out.
- Persisted task state, diagnostics, and bounded retries that retain existing work.

Worker completion requires independent manager verification. The manager also owns integration and verification of the combined result. The current runtime uses polling; background scheduling and event-triggered manager wake-up are not implemented.

See the [runtime reference](skills/manager/references/runtime.md) for CLI commands, configuration, and operational limits.

## Getting Started

1. Choose a skill from the catalog and read its `SKILL.md`.
2. Make the complete skill directory available through your coding agent's supported skill-loading mechanism, including its scripts and references.
3. Check the skill's runtime requirements, then ask your agent to use it for your task.

For example:

```text
Use the manager skill to add Google OAuth to this project's login page.
Include loading and error states, add relevant tests, and independently
verify the integrated result before reporting completion.
```

Manager runtime data is stored in `.manager/{manager-id}/` at the managed project's Git root. Initialization uses shared Git `info/exclude` and preserves the user's `.gitignore`. Save the returned ID, explicitly claim ownership, and use that selector and private owner credential for management writes. Workers start from committed Git refs; relevant uncommitted changes must be accounted for in the task plan.

The current v2 implementation is staged: manager namespaces, owner handoff, long-verification fencing, isolated integration/combined verification, the local delivery gate, and explicit v1 migration with backup and forward resume are available. Overall composition and real-provider validation are still pending. Delivery uses existing user/repository authorization and provides no push or PR creation. Migration requires a zero-write preview, matching source hash and quiesced legacy writers; historical acceptance requires fresh verification. See the [migration workflow](skills/manager/references/runtime.md#explicit-v1-migration).

## Development

Run the Manager behavioral tests from the repository root:

```sh
python3 skills/manager/scripts/test_manager.py
```

To exercise a real tmux server with test workers:

```sh
MANAGER_TEST_REAL_TMUX=1 python3 skills/manager/scripts/test_manager.py
```

These tests use temporary Git repositories and fake workers, with no model API calls.

## Contributing

Keep new skills under `skills/<name>/`, with a clear description of their purpose and invocation scope in `SKILL.md`. Include supporting resources only when they serve the workflow, validate executable helpers, and update the skill catalog when adding a skill.
