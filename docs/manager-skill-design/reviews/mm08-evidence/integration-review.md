# Independent combined review — MM-08

The only source is alpha/T001, accepted after correction ack, independent code
review and runtime verification ead15e392ce04db8b10ff02b76397acc. The source is a
reviewed dirty result; a cherry-pick would omit its code. Deliberately copy only
smoke.py and test_smoke.py into alpha's integration tree, stage those two files
and commit them. Preserve the accepted tree and beta's queued task/integration.

Reviewed source file SHA-256 values:
- smoke.py: 8e68fd611bbdb819d059b28192d3d33ac6414a465993c60056b23ec9278d02fd
- test_smoke.py: 97b64c72c2da97798eeb4fd2ed912d7fdd5c5faf5323b6e030bb179118d50859

The remaining candidate files must retain the explicit initial HEAD base.
The local target refs/heads/release-smoke is a fixture-only direct branch at that
base; combined verification must confirm a clean committed candidate, target
ancestry, unchanged accepted source and current review. Run the four local
unittests with -B to avoid generating new candidate bytecode. Main dirty/staged/
untracked files and index are user-owned fixture sentinels and must be preserved.
This validates integration only; no remote delivery, merge/push or deployment.
