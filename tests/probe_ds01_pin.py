#!/usr/bin/env python3
"""DS-01 pin probe: temporary Git fixtures only, no manager/scheduler/provider execution.

Reconstructed after the first run; the original inline script was not saved. Check names
match docs/reviews/ds01-pin-probe/result.json from that run; rerun-result.json there is
this script's output.
"""
import json
from pathlib import Path
import subprocess
import tempfile

checks = {}
def run(root, *args, input=None, ok=True):
    p = subprocess.run(['git', '-C', str(root), *args], input=input, text=True, capture_output=True)
    if ok and p.returncode:
        raise RuntimeError(p.stderr)
    return p

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks[name] = True

def create(root, ref, oid):
    # Expected-missing, no-deref creation, as SPEC-002 §5.3 requires for bind pins.
    return run(root, 'update-ref', '--stdin', input=f'start\noption no-deref\ncreate {ref} {oid}\nprepare\ncommit\n', ok=False)

def commit(root, tree, parent, message):
    return run(root, 'commit-tree', tree, *(['-p', parent] if parent else []), '-m', message).stdout.strip()

with tempfile.TemporaryDirectory(prefix='ds01-pin-') as temporary:
    root = Path(temporary) / 'repo'
    root.mkdir()
    run(root, 'init', '-q')
    run(root, 'config', 'user.name', 'DS-01 Fixture')
    run(root, 'config', 'user.email', 'ds01@example.invalid')
    run(root, 'config', 'gc.auto', '0')
    empty = run(root, 'hash-object', '-t', 'tree', '-w', '--stdin', input='').stdout.strip()
    base = commit(root, empty, None, 'base')
    candidate = commit(root, empty, base, 'candidate')
    unpinned = commit(root, empty, base, 'unpinned candidate')
    run(root, 'update-ref', 'refs/heads/integration', candidate)
    prefix = 'refs/manager-runtime/bases/fixture/alpha/'

    pin = prefix + 'T002'
    first, again = create(root, pin, candidate), create(root, pin, candidate)
    check('expected_missing_pin_created', first.returncode == 0 and again.returncode != 0
          and run(root, 'rev-parse', pin).stdout.strip() == candidate)

    foreign = prefix + 'foreign'
    run(root, 'update-ref', foreign, candidate)
    check('existing_same_oid_not_silently_adopted', create(root, foreign, candidate).returncode != 0)

    # Integration amend/reset: the branch stops reaching candidate; the pin must not move.
    run(root, 'update-ref', 'refs/heads/integration', base)
    run(root, 'update-ref', 'refs/heads/scratch', unpinned)
    run(root, 'update-ref', '-d', 'refs/heads/scratch')
    check('pin_survives_integration_rewrite', run(root, 'rev-parse', pin).stdout.strip() == candidate)

    run(root, 'reflog', 'expire', '--expire=now', '--expire-unreachable=now', '--all')
    run(root, 'gc', '-q', '--prune=now')
    check('candidate_remains_commit_after_gc', run(root, 'cat-file', '-t', candidate).stdout.strip() == 'commit')
    # Control: GC really pruned; without a pin the rewritten candidate is gone.
    check('unpinned_candidate_pruned_control', run(root, 'cat-file', '-e', unpinned, ok=False).returncode != 0)

    run(root, 'update-ref', 'refs/heads/symbolic-source', candidate)
    symbolic = prefix + 'T003'
    run(root, 'symbolic-ref', symbolic, 'refs/heads/symbolic-source')
    check('symbolic_pin_detectable_even_same_oid', run(root, 'rev-parse', symbolic).stdout.strip() == candidate
          and run(root, 'symbolic-ref', '-q', symbolic, ok=False).returncode == 0)

output = {'git_version': subprocess.run(['git', '--version'], text=True, capture_output=True).stdout.strip(),
          'fixture': 'temporary directory, removed after the run', 'checks': checks,
          'scope': 'Git primitive only; scheduler/binding runtime not exercised'}
print(json.dumps(output, ensure_ascii=False, indent=2))
