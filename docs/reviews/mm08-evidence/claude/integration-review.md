# Independent combined review — MM-08 (Claude Code)

The only source is alpha/T001, accepted after correction ack, independent code
review and runtime verification 210f6a8adbe342d4903e26b88b1a3a75. The source is a
reviewed dirty result; a cherry-pick would omit its code. Deliberately copy only
smoke.py and test_smoke.py into alpha's integration tree, stage those two files
and commit them. Preserve the accepted tree and beta's queued task/integration.

Reviewed source file SHA-256 values:
- smoke.py: 8e68fd611bbdb819d059b28192d3d33ac6414a465993c60056b23ec9278d02fd
- test_smoke.py: a2fb84655640586de79555ec6c4b1fdacf1589523f76e9a2e3ec9ec6cd38f7ee

The remaining candidate files must retain the explicit initial HEAD base.
The local target refs/heads/release-smoke is a fixture-only direct branch at that
base; combined verification must confirm a clean committed candidate, target
ancestry, unchanged accepted source and current review. Run the four local
unittests with -B to avoid generating new candidate bytecode. Main dirty/staged/
untracked files and index are user-owned fixture sentinels and must be preserved.
This validates integration only; no remote delivery, merge/push or deployment.
