# Independent manager review — MM-08 T001 (Claude Code)

Reviewed the original fixture, first completion, persisted correction/inbox ack,
current smoke.py/test_smoke.py diff, final result.md and full launch identity.
Only smoke.py and test_smoke.py changed; no untracked files or bytecode exist in
the worktree. Worker HEAD remains at base 3addd35: no worker commits,
dependencies, merge/push or project configuration edits. The worker transcript
shows only Bash tool calls (no subagent), each allowed by the host's native
Claude Code auto permission mode inherited from user settings.

The implementation strips the string before formatting, raises ValueError with
exact text "name is required" for empty/whitespace-only values, and preserves
Ada/Lin greeting punctuation. Four unittests cover Ada, Lin, surrounding spaces,
and empty/spaces/tab-newline error cases. The correction ack matches message
319bdb539a4c4d08a24e3dafb5e8b3ae, manager alpha, T001, attempt 1 and assignment
74aab1e376264db0a29d85c3f0c36e22; done is a worker claim. Non-string input
raising AttributeError is out of the correction's scope and acceptable.

Run the tests independently through manager verify with -B, plus an independent
assertion command checking exact trim output, unchanged Lin output and exact
blank error. Accept only if both commands pass and the runtime rechecks the
unchanged evidence snapshot.
