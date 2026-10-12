# T001 result

Implemented `greeting(name)` to strip surrounding whitespace and return
`Hello, {name}!`, including exactly `Hello, Ada!` for Ada or `  Ada  `,
and `Hello, Lin!` for Lin. Empty and whitespace-only names raise
`ValueError('name is required')`.

Read and acknowledged current manager correction
`4443d5f4ca3d4374b14561d319e52be5` through the assigned runtime before editing.

Files changed:
- `smoke.py`: implemented the greeting, whitespace normalization, and required-name validation.
- `test_smoke.py`: covers Ada, Lin, surrounding whitespace, and blank names
  (empty string, spaces, and tab/newline), including the exact error message.

Verification: `python3 -m unittest -v` in the assigned worktree exited 0.
All 4 tests passed. Reviewed the diff for the two task-owned code files.

No commits created. No dependencies or external access used. No unresolved caveats.
Completion is submitted for independent manager acceptance; available for corrections.
