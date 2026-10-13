#!/usr/bin/env python3
"""MM-01 design probe: temporary Git fixtures only, no manager/provider execution."""
import json
from pathlib import Path
import subprocess
import tempfile

results = []
def run(root, *args, input=None, ok=True):
    p = subprocess.run(['git', '-C', str(root), *args], input=input, text=True, capture_output=True)
    if ok and p.returncode:
        raise RuntimeError(p.stderr)
    return p

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    results.append({'check': name, 'passed': True})

with tempfile.TemporaryDirectory(prefix='mm01-git-') as temporary:
    root = Path(temporary) / 'repo'
    root.mkdir()
    run(root, 'init', '-q')
    run(root, 'config', 'user.name', 'MM-01 Fixture')
    run(root, 'config', 'user.email', 'mm01@example.invalid')
    (root / 'base.txt').write_text('base\n')
    (root / '.gitignore').write_text('cache/\n')
    run(root, 'add', 'base.txt', '.gitignore')
    run(root, 'commit', '-qm', 'base')
    base = run(root, 'rev-parse', 'HEAD').stdout.strip()
    run(root, 'branch', 'release')
    (root / 'base.txt').write_text('candidate\n')
    run(root, 'commit', '-qam', 'candidate')
    candidate = run(root, 'rev-parse', 'HEAD').stdout.strip()
    run(root, 'branch', 'candidate', candidate)
    receipt = 'refs/manager-runtime/deliveries/fixture-success'
    transaction = f'start\noption no-deref\nverify refs/heads/candidate {candidate}\noption no-deref\nupdate refs/heads/release {candidate} {base}\noption no-deref\ncreate {receipt} {candidate}\nprepare\ncommit\n'
    run(root, 'update-ref', '--stdin', input=transaction)
    check('expected target + candidate + receipt transaction commits', run(root, 'rev-parse', 'release').stdout.strip() == candidate and run(root, 'rev-parse', receipt).stdout.strip() == candidate)
    failed_receipt = 'refs/manager-runtime/deliveries/fixture-stale'
    failed = run(root, 'update-ref', '--stdin', input=f'start\noption no-deref\nupdate refs/heads/release {base} {base}\noption no-deref\ncreate {failed_receipt} {base}\nprepare\ncommit\n', ok=False)
    check('stale old OID rejects whole transaction including receipt', failed.returncode != 0 and run(root, 'show-ref', '--verify', '--quiet', failed_receipt, ok=False).returncode != 0 and run(root, 'rev-parse', 'release').stdout.strip() == candidate)
    run(root, 'branch', 'uncommitted-target', base)
    aborted_receipt = 'refs/manager-runtime/deliveries/fixture-abort'
    run(root, 'update-ref', '--stdin', input=f'start\noption no-deref\nupdate refs/heads/uncommitted-target {candidate} {base}\noption no-deref\ncreate {aborted_receipt} {candidate}\nprepare\n')
    check('prepared transaction without commit aborts', run(root, 'rev-parse', 'uncommitted-target').stdout.strip() == base and run(root, 'show-ref', '--verify', '--quiet', aborted_receipt, ok=False).returncode != 0)
    run(root, 'update-ref', 'refs/heads/release', base, candidate)
    check('receipt survives later target update', run(root, 'rev-parse', receipt).stdout.strip() == candidate)
    checked = Path(temporary) / 'checked-target'
    run(root, 'worktree', 'add', '-q', str(checked), 'release')
    inventory = run(root, 'worktree', 'list', '--porcelain', '-z').stdout
    check('inventory identifies checked-out target branch', 'branch refs/heads/release\0' in inventory)
    check('linked roots share canonical common directory', Path(run(checked, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.strip()).resolve() == Path(run(root, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.strip()).resolve())
    old = root / '.manager/worktrees/T001'
    new = root / '.manager/legacy/worktrees/T001'
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    legacy_branch = 'manager/fixture/T001'
    v2_branch = 'manager/fixture/legacy/tasks/T001'
    run(root, 'worktree', 'add', '-q', '-b', legacy_branch, str(old), base)
    (old / 'base.txt').write_text('staged\n')
    run(old, 'add', 'base.txt')
    (old / 'base.txt').write_text('unstaged\n')
    (old / 'untracked.txt').write_bytes(b'untracked\x00bytes')
    (old / 'cache').mkdir()
    (old / 'cache/ignored.bin').write_bytes(b'ignored\x00bytes')
    (old / 'user-link').symlink_to('untracked.txt')
    index_before = run(old, 'ls-files', '--stage', '-z').stdout
    bytes_before = {p: (old / p).read_bytes() for p in ['base.txt', 'untracked.txt', 'cache/ignored.bin']}
    run(root, 'branch', v2_branch, base)
    run(root, 'worktree', 'move', str(old), str(new))
    run(new, 'switch', '-q', v2_branch)
    check('dirty move + branch switch preserves HEAD/index/file bytes/symlink', run(new, 'rev-parse', 'HEAD').stdout.strip() == base and run(new, 'ls-files', '--stage', '-z').stdout == index_before and all((new / p).read_bytes() == data for p, data in bytes_before.items()) and (new / 'user-link').readlink() == Path('untracked.txt'))
    check('old ref retained and new ref checked out', run(root, 'rev-parse', legacy_branch).stdout.strip() == base and run(new, 'symbolic-ref', 'HEAD').stdout.strip() == 'refs/heads/' + v2_branch and 'worktree ' + str(new.resolve()) + '\0' in run(root, 'worktree', 'list', '--porcelain', '-z').stdout)
    # Boundary probe: expected OID does not prove that a branch is still a direct ref.
    run(root, 'branch', 'symbolic-source', base)
    run(root, 'symbolic-ref', 'refs/heads/symbolic-target', 'refs/heads/symbolic-source')
    symbolic = run(root, 'update-ref', '--no-deref', 'refs/heads/symbolic-target', candidate, base, ok=False)
    results.append({'check': 'symbolic ref boundary probe', 'update_returncode': symbolic.returncode, 'remains_symbolic': run(root, 'symbolic-ref', '-q', 'refs/heads/symbolic-target', ok=False).returncode == 0, 'note': 'Expected OID alone must not be described as excluding concurrent symbolic-ref conversion.'})

output = {'scope': 'Git primitives only; no manager v2 CLI or provider execution', 'git': subprocess.run(['git', '--version'], text=True, capture_output=True).stdout.strip(), 'checks': results}
print(json.dumps(output, ensure_ascii=False, indent=2))
