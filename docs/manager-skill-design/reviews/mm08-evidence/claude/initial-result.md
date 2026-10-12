# T001 result (attempt 1)

## Files changed
- smoke.py — `greeting(name)` now returns `f"Hello, {name}!"`.
- test_smoke.py — added `test_name_lin` asserting `greeting("Lin") == "Hello, Lin!"`.

## Behavior / acceptance
- `greeting("Ada")` -> `Hello, Ada!`
- `greeting("Lin")` -> `Hello, Lin!`
- Second local unittest for Lin added.

## Verification
- `python3 -m unittest -v` (in worktree): 2 tests ran, OK, exit 0.

## Caveats
- No commits made (auto_commit false; no manager instruction to commit).
- Inbox was empty at start; no manager corrections received.
