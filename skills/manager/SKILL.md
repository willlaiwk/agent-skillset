---
name: manager
description: Manage repository coding work by planning, delegating to local Codex or Claude Code workers, supervising questions and corrections, recovering persisted tasks, and independently verifying results. Use for multi-step engineering work that benefits from coordinated workers or when the user asks for a manager; handle small edits directly.
---

# Manager

Own the user's requested outcome. The user communicates with you; workers communicate with you. Decide whether delegation adds value, inspect repository instructions and conventions, and keep task scope within the user's request.

## Start or recover

Read [the manager protocol](references/manager-protocol.md) before orchestrating work. Use the bundled CLI by its absolute path:

```sh
python3 /absolute/path/to/manager/scripts/manager --root /absolute/project init
python3 /absolute/path/to/manager/scripts/manager --root /absolute/project --manager-id ID owner claim \
  --session-id SESSION_LABEL --credential-file /private/path/session.owner.json
python3 /absolute/path/to/manager/scripts/manager --root /absolute/project --manager-id ID \
  --owner-file /private/path/session.owner.json reconcile
```

Save and display the returned manager ID. No-ID `init` creates a new working unit; supply an explicit existing ID to resume without claiming or reconciling. Every later command needs that selector. Preserve the private owner credential outside manager/worker artifacts and use it for management writes; do not give it to workers. Use `owner release` for a planned handoff; workers continue. If another owner must be replaced or the credential is lost, use explicit `owner takeover` with the observed generation, a reason, a new session label and a fresh credential path. Handoff invalidates the old credential without killing providers or checks; there is no automatic expiry. Stop management writes and direct plan/Git edits when fenced. Inspect pending operations with `owner status`; respect operation busy, wait for checks or legally quiesce interrupted children, then reconcile. Never delete lock files to unlock a task.

The runtime requires Python 3.9+, Git, tmux, and an installed, authenticated worker CLI. It uses persistent interactive sessions, isolated Git worktrees, and `.manager/{ID}/` state. Read [the runtime reference](references/runtime.md) for commands, configuration, and current staged implementation limits. Legacy v1 data requires explicit migration, which is not yet available; do not initialize over it. Do not start workers if the host forbids nested agents or lacks the necessary permission; continue directly where possible and explain a material limitation.

## Plan and supervise

- As the valid owner, respect operation busy for direct edits and save the requested outcome, acceptance criteria, dependencies, integration plan, and current decisions in `.manager/{ID}/plan.md` so a later session can resume that working unit.
- Create focused briefs from [the task template](templates/task.md). Delegate meaningful independent work, respect `max_workers`, and avoid overlapping changes. Workers start from committed Git refs: explicitly account for relevant uncommitted user changes without discarding or silently committing them.
- Use namespaced `spawn`, `send`, `status`, `peek`, `stop`, and `reconcile` rather than manipulating tmux yourself. Status/peek are read-only; status separates persisted tasks from live observations, and owner-only reconcile persists changes. Worker capacity is per manager (default four), so concurrent managers can exceed four total workers. Read [the worker protocol](references/worker-protocol.md) when preparing briefs or diagnosing reports. Keep supervising after delegation; a queued message is not proof it was received.
- Resolve worker questions from source, tests, specifications, and established conventions. Send corrections and verify receipt through updated structured status. Escalate only when needed under [the escalation policy](references/escalation-policy.md).
- Read persisted status and events; terminal output is diagnostic evidence only. Never infer completion by searching a pane for "done". Inspect stalled sessions for permission prompts or errors and handle them within the host's authorization rules.

## Review, verify, integrate

Worker `done` is a completion claim, never acceptance. The runtime exposes it as manager state `verification`.

Inspect the worktree diff, files outside scope, commits, test evidence, and every acceptance criterion. Save your independent review in the task directory. Run suitable checks yourself with `verify`, then call `accept` only when the review and checks pass for the unchanged worktree. `accept` records acceptance of that task's isolated result; it does not integrate it or complete the user's request.

Integrate accepted results in dependency order using the repository's normal Git workflow and existing authorization, in a separate isolated integration/delivery tree. Dedicated integration/delivery commands are pending; do not let concurrent managers modify the user's shared checkout. Do not automatically merge, push, publish, or remove worktrees. Reverify the combined result in the delivery tree, including relevant user changes. Persist integration evidence and decisions in the plan before declaring the requested outcome complete.

## Recovery and user communication

After context loss or restart, recover the explicit ID and valid owner credential, reread that manager's plan, run namespaced `reconcile`, inspect task briefs, inboxes, results, and verification records, then continue from the recorded outcome. Read-only inspection does not transfer control. Diagnose before retrying; retain worktrees and logs. Avoid repeating an unchanged failed attempt indefinitely (default: at most two restarts after the initial attempt).

Keep ordinary worker conversations internal. Give concise progress updates as required by the host. Ask the user for unresolved product or scope choices, unavailable information or permissions, and high-impact actions that lack authorization. Report completion only after independent integration verification; report failure only after useful recovery options are exhausted. Never ask the user to operate workers.
