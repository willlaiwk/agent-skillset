# T001 result (attempt 1, after correction 319bdb539a4c4d08a24e3dafb5e8b3ae)

## Files changed
- smoke.py — `greeting(name)` strips surrounding whitespace, raises `ValueError("name is required")` if the result is empty, otherwise returns `f"Hello, {name}!"`.
- test_smoke.py — tests for Ada, Lin, whitespace stripping (`'  Ada  '`), and blank/whitespace-only names (`''`, `'   '`, `'\t\n'`) raising ValueError.

## Behavior / acceptance
- `greeting("Ada")` -> `Hello, Ada!`; `greeting("Lin")` -> `Hello, Lin!`
- `greeting("  Ada  ")` -> `Hello, Ada!`
- `greeting("")` / `greeting("   ")` -> `ValueError('name is required')`

## Verification
- `python3 -m unittest -v` (in worktree): 4 tests ran, OK, exit 0.

## Caveats
- Manager message 319bdb539a4c4d08a24e3dafb5e8b3ae acknowledged via `report --ack`.
- Non-string input (e.g. None) is not handled specially; it raises AttributeError (out of scope).
- No commits made.
