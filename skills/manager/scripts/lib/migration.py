"""Explicit, cooperative v1 migration. No provider launch, stop, or rollback."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from .namespace import reject_symlinks


LOCKS = {".lock", ".report.lock", ".operation.lock"}
PHASES = ("preflight", "backed_up", "refs_prepared", "worktrees_moved",
          "data_converted", "validated", "completed")


class Migration:
    def __init__(self, runtime):
        self.r = runtime
        self.api = runtime.load.__func__.__globals__
        self.Error = self.api["Error"]
        self.source = runtime.namespace.container
        self.home = runtime.home
        self.marker = self.source / ".migration.json"
        self.base = runtime.control / "migrations" / runtime.key
        self.journal = None
        self.directory = None
        self.active_intent = None

    def git(self, root, *args):
        return self.api["git"](root, *args)

    def run(self, argv, **kwargs):
        return self.api["run"](argv, **kwargs)

    def read(self, path):
        value = self.api["read_json"](reject_symlinks(path))
        if not isinstance(value, dict):
            raise self.Error("Invalid migration/legacy JSON object: " + str(path))
        return value

    def write(self, path, value):
        self.api["atomic_json"](path, value)

    def digest(self, value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()

    def scan(self, path, control=False, skip=()):
        """Hash modes, empty directories, bytes and link values; never follow links."""
        entries = {}
        def visit(current, relative):
            info = current.lstat()
            entry = {"mode": stat.S_IMODE(info.st_mode)}
            if stat.S_ISLNK(info.st_mode):
                if control:
                    raise self.Error("Symlink control artifact: " + str(current))
                entry.update(kind="symlink", link=os.readlink(current))
            elif stat.S_ISDIR(info.st_mode):
                entry["kind"] = "directory"
                children = sorted(current.iterdir(), key=lambda p: p.name)
                for child in children:
                    name = (relative + "/" if relative else "") + child.name
                    if name in skip or (control and child.name in LOCKS):
                        continue
                    visit(child, name)
                if sorted(p.name for p in current.iterdir()) != [p.name for p in children]:
                    raise self.Error("Source directory changed while reading: " + str(current))
            elif stat.S_ISREG(info.st_mode):
                content = self.api["read_bytes"](current) if control else current.read_bytes()
                entry.update(kind="file", sha256=hashlib.sha256(content).hexdigest(), size=len(content))
                after = current.lstat()
                if (info.st_mode, info.st_size, info.st_mtime_ns) != (after.st_mode, after.st_size, after.st_mtime_ns):
                    raise self.Error("Source file changed while reading: " + str(current))
            else:
                raise self.Error("Unsupported source artifact: " + str(current))
            entries[relative] = entry
        visit(path, "")
        return entries

    def source_control(self, names):
        return {name: self.scan(self.source / name, control=True) for name in names
                if name not in ("worktrees", ".lock", ".migration.json")}

    def probe_lock(self, path):
        """Readonly advisory-lock probe: no creation, append, repair or unlink."""
        reject_symlinks(path)
        if not path.exists():
            return False
        import fcntl
        with path.open("rb") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(stream, fcntl.LOCK_UN)
        return False

    def panes(self, tasks):
        session = "manager-" + self.r.key
        result = self.run(["tmux", "list-panes", "-s", "-t", session,
                           "-F", "#{window_name}\t#{pane_id}\t#{pane_dead}"], check=False)
        if result.returncode:
            error = result.stderr.decode(errors="replace")
            if any(s in error for s in ("no server running", "no sessions", "can't find", "No such file or directory")):
                return [], []
            raise self.Error("Cannot inventory legacy tmux session: " + error.strip())
        inventory, blockers, known = [], [], {"control", *("mgr-" + t for t in tasks)}
        for line in result.stdout.decode().splitlines():
            parts = line.split("\t")
            if len(parts) != 3 or parts[2] not in ("0", "1"):
                raise self.Error("Invalid legacy pane inventory")
            name, pane, dead = parts
            inventory.append({"window": name, "pane": pane, "dead": dead == "1"})
            if name not in known:
                blockers.append("Unknown legacy pane ownership: " + name)
            if dead != "1":
                blockers.append("Live legacy pane must exit before migration: " + name)
        return inventory, blockers

    def worktree_snapshot(self, tree, old_ref, allowed_ref=None):
        tree = reject_symlinks(tree)
        registrations = self.r.worktrees()
        entry = registrations.get(str(tree))
        if not tree.is_dir() or not entry or entry.get("branch") not in (old_ref, allowed_ref):
            raise self.Error("Missing/mismatched source worktree: " + str(tree))
        if not reject_symlinks(tree / ".git").is_file():
            raise self.Error("Source must have a direct linked-worktree Git pointer")
        # Retain locked/prunable fields that the ordinary diagnostic inventory omits.
        raw = self.run(["git", "-C", self.r.root, "worktree", "list", "--porcelain", "-z"]).stdout
        blocks = raw.decode(errors="surrogateescape").strip("\0").split("\0\0")
        block = next((b for b in blocks if b.split("\0")[0] == "worktree " + str(tree)), None)
        if not block or any(f.split(" ")[0] in ("locked", "prunable") for f in block.split("\0")[1:]):
            raise self.Error("Locked/prunable source worktree is unsupported: " + str(tree))
        if Path(self.git(tree, "rev-parse", "--show-toplevel")).resolve() != tree:
            raise self.Error("Source worktree root mismatch")
        common = Path(self.git(tree, "rev-parse", "--git-common-dir"))
        if (common if common.is_absolute() else tree / common).resolve() != self.r.common:
            raise self.Error("Foreign source repository")
        private = Path(self.git(tree, "rev-parse", "--absolute-git-dir"))
        reject_symlinks(private)
        if not private.is_relative_to(self.r.common / "worktrees"):
            raise self.Error("Cannot move a main or foreign worktree")
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD", "rebase-merge",
                     "rebase-apply", "sequencer", "BISECT_LOG", "index.lock", "HEAD.lock"):
            if (private / name).exists():
                raise self.Error("Source has an in-progress Git operation: " + name)
        if self.git(tree, "ls-files", "-u"):
            raise self.Error("Unmerged index is unsupported")
        if (tree / ".gitmodules").exists() or self.git(tree, "submodule", "status", "--recursive"):
            raise self.Error("Submodule worktree migration is unsupported")
        head_ref = self.git(tree, "symbolic-ref", "-q", "HEAD")
        if head_ref not in (old_ref, allowed_ref):
            raise self.Error("Source HEAD branch mismatch")
        head = self.r.direct_commit(head_ref)
        index = reject_symlinks(private / "index")
        if not index.is_file():
            raise self.Error("Missing source index")
        # move changes gitdir; switching an identical-OID branch changes only HEAD.
        preserved = self.scan(private, control=True, skip=("HEAD", "gitdir", "logs/HEAD"))
        return {"head": head, "head_ref": head_ref, "private_git": str(private),
                "content": self.scan(tree, skip=(".git",)), "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
                "private_preserved": preserved}

    def validate_state(self, state):
        if (type(state.get("version")) is not int or state["version"] != 1
                or state.get("root") != str(self.r.root) or state.get("session") != "manager-" + self.r.key
                or not isinstance(state.get("tasks"), dict)):
            raise self.Error("Unsupported/corrupt v1 state or moved root")
        for identity, item in state["tasks"].items():
            self.api["task_id"](identity)
            required = {"task_id", "title", "kind", "agent", "dependencies", "base", "branch",
                        "worktree", "window", "attempt", "state", "summary"}
            if (not isinstance(item, dict) or not required.issubset(item) or item["task_id"] != identity
                    or type(item["attempt"]) is not int or item["attempt"] < 0
                    or item["state"] not in self.api["STATES"]
                    or item["branch"] != "manager/" + self.r.key + "/" + identity
                    or item["worktree"] != str(self.source / "worktrees" / identity)
                    or item["window"] != "mgr-" + identity
                    or not isinstance(item["dependencies"], list)
                    or len(set(item["dependencies"])) != len(item["dependencies"])
                    or any(d not in state["tasks"] or d == identity for d in item["dependencies"])
                    or not isinstance(item["base"], str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", item["base"])):
                raise self.Error("Invalid legacy task identity/schema: " + identity)
            if self.git(self.r.root, "cat-file", "-t", item["base"]) != "commit":
                raise self.Error("Missing legacy base commit: " + identity)
        visiting, visited = set(), set()
        def walk(identity):
            if identity in visiting:
                raise self.Error("Cyclic legacy dependencies")
            if identity in visited:
                return
            visiting.add(identity)
            for dependency in state["tasks"][identity]["dependencies"]:
                walk(dependency)
            visiting.remove(identity)
            visited.add(identity)
        for identity in state["tasks"]:
            walk(identity)

    def preview(self):
        reject_symlinks(self.marker)
        if self.marker.exists():
            marker, journal = self.load_journal()
            if marker["state"] == "completed":
                self.completed(marker, journal)
            return {**self.r.namespace.envelope(), "dry_run": True, "migration_id": journal["id"],
                    "phase": journal["phase"], "source_sha256": journal["source_sha256"],
                    "destination": str(self.home), "inventory": journal["inventory"],
                    "blockers": [] if marker["state"] == "completed" else ["Pending migration; use --resume " + journal["id"]]}
        result = {**self.r.namespace.envelope(), "dry_run": True, "source_version": None,
                  "git_common_dir": str(self.r.common), "destination": str(self.home),
                  "source_sha256": None, "blockers": []}
        try:
            self.api["config"](self.r.root)
            state = self.read(self.source / "state.json")
            result["source_version"] = state.get("version")
            self.validate_state(state)
            if self.home.exists():
                result["blockers"].append("Destination manager already exists")
            names = sorted(p.name for p in self.source.iterdir() if p.name not in LOCKS)
            for name in ("events", "inbox", "tasks", "worktrees"):
                if not reject_symlinks(self.source / name).is_dir():
                    raise self.Error("Incomplete legacy layout: " + name)
            known = {"state.json", "plan.md", "events", "inbox", "tasks", "worktrees"}
            unknown = [name for name in names if name not in known]
            for name in unknown:
                if (self.source / name).is_dir() and (self.source / name / "state.json").exists():
                    raise self.Error("Unknown manager/writer ownership: " + name)
            tasks = {}
            for identity, item in sorted(state["tasks"].items()):
                directory = reject_symlinks(self.source / "tasks" / identity)
                if not directory.is_dir() or not (directory / "brief.md").is_file():
                    raise self.Error("Missing legacy task artifacts: " + identity)
                old_ref, new_ref = "refs/heads/" + item["branch"], "refs/heads/" + self.r.namespace.branch(identity)
                tree = Path(item["worktree"])
                exists = bool(self.git(self.r.root, "for-each-ref", "--format=%(refname)", old_ref))
                if item["attempt"] == 0:
                    if tree.exists() or exists or item["state"] != "queued":
                        raise self.Error("Ambiguous unstarted legacy task artifacts: " + identity)
                    snapshot = None
                else:
                    snapshot = self.worktree_snapshot(tree, old_ref)
                if self.git(self.r.root, "for-each-ref", "--format=%(refname)", new_ref):
                    result["blockers"].append("Destination ref already exists: " + new_ref)
                if self.probe_lock(directory / ".report.lock"):
                    result["blockers"].append("Busy legacy report lock: " + identity)
                tasks[identity] = {"item": item, "snapshot": snapshot, "old_ref": old_ref, "new_ref": new_ref,
                                   "old_tree": str(tree), "new_tree": str(self.home / "worktrees" / identity)}
            expected_trees = {item["old_tree"] for item in tasks.values() if item["snapshot"]}
            for path in self.r.worktrees():
                if Path(path).is_relative_to(self.source) and path not in expected_trees:
                    raise self.Error("Unknown registered legacy worktree ownership: " + path)
            if any(str(p) not in expected_trees for p in (self.source / "worktrees").iterdir()):
                raise self.Error("Unknown legacy worktree artifact")
            if any(p.name not in tasks for p in (self.source / "tasks").iterdir()):
                raise self.Error("Unknown legacy task/writer ownership")
            panes, blockers = self.panes(tasks)
            result["blockers"].extend(blockers)
            if self.probe_lock(self.source / ".lock"):
                result["blockers"].append("Busy legacy registry lock")
            inventory = {"state": state, "source_entries": names, "control": self.source_control(names),
                         "source_mode": stat.S_IMODE(self.source.stat().st_mode),
                         "tasks": tasks, "unknown_artifacts": unknown, "panes": panes}
            result.update(inventory=inventory, source_sha256=self.digest(inventory))
        except (self.Error, OSError, ValueError, TypeError, KeyError) as exc:
            result["blockers"].append(str(exc))
        return result

    def load_journal(self):
        marker = self.read(self.marker)
        identity = marker.get("id")
        if (not self.r.valid_assignment_id(identity) or marker.get("root") != str(self.r.root)
                or marker.get("manager_id") != self.r.manager_id or marker.get("project_key") != self.r.key
                or marker.get("state") not in ("active", "completed")):
            raise self.Error("Migration marker identity mismatch; preserve and diagnose")
        self.directory = reject_symlinks(self.base / identity)
        journal = self.read(self.directory / "journal.json")
        if (journal.get("version") != 1 or not self.r.namespace.matches(journal)
                or journal.get("id") != identity or journal.get("git_common_dir") != str(self.r.common)
                or journal.get("destination") != str(self.home) or journal.get("phase") not in PHASES
                or self.digest(journal.get("inventory")) != journal.get("source_sha256")
                or journal.get("source_version") != 1 or journal.get("target_version") != 2):
            raise self.Error("Migration journal identity/inventory mismatch; preserve and diagnose")
        inventory = journal["inventory"]
        if self.read(self.directory / "inventory.json") != inventory:
            raise self.Error("Migration inventory file/journal mismatch")
        self.validate_state(inventory["state"])
        if (not isinstance(inventory.get("source_entries"), list)
                or any(not isinstance(n, str) or n in ("", ".", "..") or "/" in n for n in inventory["source_entries"])
                or type(inventory.get("source_mode")) is not int or not 0 <= inventory["source_mode"] <= 0o7777
                or set(inventory.get("tasks", {})) != set(inventory["state"]["tasks"])
                or not isinstance(journal.get("steps"), dict) or not isinstance(journal.get("errors"), list)):
            raise self.Error("Invalid migration inventory/schema")
        for identity, entry in inventory["tasks"].items():
            item = inventory["state"]["tasks"][identity]
            if (entry.get("item") != item or entry.get("old_ref") != "refs/heads/" + item["branch"]
                    or entry.get("new_ref") != "refs/heads/" + self.r.namespace.branch(identity)
                    or entry.get("old_tree") != str(self.source / "worktrees" / identity)
                    or entry.get("new_tree") != str(self.home / "worktrees" / identity)):
                raise self.Error("Migration path/ref mapping mismatch")
            if entry.get("snapshot"):
                private = Path(entry["snapshot"]["private_git"])
                if private.parent != self.r.common / "worktrees" or private.resolve() != private:
                    raise self.Error("Migration private Git ownership mismatch")
                reject_symlinks(private)
        if "backup_refs" in journal:
            roots = journal.get("object_roots")
            if not isinstance(roots, list) or any(not isinstance(oid, str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", oid) for oid in roots):
                raise self.Error("Invalid migration object roots")
            expected = {"refs/manager-backup/migrations/" + self.r.key + "/" + journal["id"] + "/" + str(n): oid for n, oid in enumerate(roots)}
            if journal["backup_refs"] != expected:
                raise self.Error("Migration backup ref mapping mismatch")
        self.journal = journal
        return marker, journal

    def save(self):
        self.write(self.directory / "journal.json", self.journal)

    def phase(self, name):
        self.journal["phase"] = name
        self.save()

    def checkpoint(self, name, operation):
        steps = self.journal["steps"]
        existing = name in steps
        if name not in steps:
            steps[name] = {"state": "intent", "at": self.api["now"]()}
            self.save()
        previous = self.active_intent
        self.active_intent = (name, existing)
        try:
            result = operation()  # Completed steps are rechecked, never blindly skipped.
        finally:
            self.active_intent = previous
        fingerprint = self.digest(result) if result is not None else None
        if steps[name]["state"] == "completed" and steps[name].get("result_sha256") != fingerprint:
            raise self.Error("Completed migration step changed: " + name)
        if steps[name]["state"] != "completed":
            steps[name].update(state="completed", completed_at=self.api["now"](), result_sha256=fingerprint)
            self.save()

    def assert_source(self, tombstone=False):
        inventory = self.journal["inventory"]
        if stat.S_IMODE(self.source.stat().st_mode) != inventory["source_mode"]:
            raise self.Error("Source directory mode changed during migration")
        expected = inventory["control"]
        names = inventory["source_entries"]
        actual = self.source_control([name for name in names if not (tombstone and name == "state.json")])
        wanted = {k: v for k, v in expected.items() if not (tombstone and k == "state.json")}
        if actual != wanted:
            raise self.Error("Source hash changed during migration; preserve both sides and diagnose")
        allowed = set(names) | LOCKS | {".migration.json", self.r.manager_id}
        if any(p.name not in allowed for p in self.source.iterdir()):
            raise self.Error("Unexpected source artifact appeared during migration")
        _, blockers = self.panes(inventory["tasks"])
        if blockers:
            raise self.Error("; ".join(blockers))

    def copy(self, source, destination, control=False, skip=()):
        expected = self.scan(source, control=control, skip=skip)
        for relative, entry in sorted(expected.items(), key=lambda pair: (pair[0].count("/"), pair[0])):
            origin, target = source / relative, destination / relative
            reject_symlinks(target.parent)
            if target.exists() or target.is_symlink():
                actual = self.scan(target, control=control)
                if actual[""] != entry:
                    raise self.Error("Backup/conversion destination changed: " + str(target))
                continue
            if entry["kind"] == "directory":
                target.mkdir(parents=True)
                target.chmod(entry["mode"])
            elif entry["kind"] == "symlink":
                os.symlink(entry["link"], target)
            else:
                fd, temporary = tempfile.mkstemp(prefix=".copy-", dir=self.directory)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(origin.read_bytes())
                        stream.flush()
                        os.fchmod(stream.fileno(), entry["mode"])
                        os.fsync(stream.fileno())
                    os.replace(temporary, target)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            self.api["sync_directory"](target.parent)
        if self.scan(destination, control=control) != expected:
            raise self.Error("Backup/conversion content mismatch: " + str(destination))

    def raw_ref(self, ref):
        result = self.run(["git", "-C", self.r.root, "show-ref", "--verify", "--hash", ref], check=False)
        if result.returncode:
            return None
        if self.run(["git", "-C", self.r.root, "symbolic-ref", "-q", ref], check=False).returncode == 0:
            raise self.Error("Symbolic migration ref is unsupported: " + ref)
        return result.stdout.decode().strip()

    def ref_transaction(self, refs, verify=()):
        present = [self.raw_ref(ref) for ref in refs]
        step = self.journal["steps"][self.active_intent[0]]
        if any(value is not None for value in present):
            if not self.active_intent[1] or step.get("ref_conflict") or present != list(refs.values()):
                step["ref_conflict"] = True
                self.save()
                raise self.Error("Ambiguous partial or changed migration refs")
            return refs
        data = "start\n"
        for ref, oid in verify:
            data += "option no-deref\nverify " + ref + " " + oid + "\n"
        for ref, oid in refs.items():
            data += "option no-deref\ncreate " + ref + " " + oid + "\n"
        data += "prepare\ncommit\n"
        result = self.run(["git", "-C", self.r.root, "update-ref", "--stdin"], data=data.encode(), check=False)
        if result.returncode:
            step["ref_conflict"] = True
            self.save()
            raise self.Error("Migration ref transaction rejected: " + result.stderr.decode(errors="replace").strip())
        step["ref_conflict"] = False
        return refs

    def object_roots(self):
        roots = {item["item"]["base"] for item in self.journal["inventory"]["tasks"].values()}
        files = [self.source / name for name in self.journal["inventory"]["source_entries"] if name != "worktrees"]
        for entry in self.journal["inventory"]["tasks"].values():
            if not entry["snapshot"]:
                continue
            roots.add(entry["snapshot"]["head"])
            staged = self.run(["git", "-C", entry["old_tree"], "ls-files", "--stage", "-z"]).stdout
            for field in staged.split(b"\0"):
                if field:
                    roots.add(field.split(b" ")[1].decode())
            files.append(Path(entry["snapshot"]["private_git"]))
        # Historical hashes may refer to commits no longer reachable from a task tip.
        for path in files:
            candidates = path.rglob("*") if path.is_dir() else [path]
            for file in candidates:
                if file.is_file() and not file.is_symlink() and file.name not in LOCKS:
                    for oid in re.findall(rb"(?<![0-9a-f])(?:[0-9a-f]{64}|[0-9a-f]{40})(?![0-9a-f])", file.read_bytes()):
                        kind = self.run(["git", "-C", self.r.root, "cat-file", "-t", oid.decode()], check=False)
                        if kind.returncode == 0 and kind.stdout.strip() == b"commit":
                            roots.add(oid.decode())
        return sorted(roots)

    def backup(self):
        backup = reject_symlinks(self.directory / "backup")
        backup.mkdir(mode=0o700, exist_ok=True)
        self.api["sync_directory"](self.directory)
        inventory = self.journal["inventory"]
        manager = backup / "manager"
        reject_symlinks(manager)
        if manager.exists():
            if stat.S_IMODE(manager.stat().st_mode) != inventory["source_mode"]:
                raise self.Error("Backup directory mode changed")
        else:
            manager.mkdir()
            manager.chmod(inventory["source_mode"])
        for name in inventory["source_entries"]:
            if name != "worktrees":
                self.copy(self.source / name, manager / name, control=True)
        for identity, entry in inventory["tasks"].items():
            if entry["snapshot"]:
                for parent in ("worktrees", "private-git", "worktree-pointers"):
                    (backup / parent).mkdir(exist_ok=True)
                self.copy(Path(entry["old_tree"]), backup / "worktrees" / identity, skip=(".git",))
                # Preserve the original pointer as inert metadata, never as an
                # executable alias of the live linked worktree's private index.
                self.copy(Path(entry["old_tree"]) / ".git", backup / "worktree-pointers" / (identity + ".txt"), control=True)
                self.copy(Path(entry["snapshot"]["private_git"]), backup / "private-git" / identity, control=True)
        if "object_roots" not in self.journal:
            self.journal["object_roots"] = self.object_roots()
            self.journal["backup_refs"] = {"refs/manager-backup/migrations/" + self.r.key + "/" + self.journal["id"] + "/" + str(n): oid
                                           for n, oid in enumerate(self.journal["object_roots"])}
            self.save()
        verify = [(entry["old_ref"], entry["snapshot"]["head"]) for entry in inventory["tasks"].values() if entry["snapshot"]]
        self.checkpoint("backup-refs", lambda: self.ref_transaction(self.journal["backup_refs"], verify))
        if self.journal["object_roots"]:
            pack, index = backup / "objects.pack", backup / "objects.idx"
            reject_symlinks(pack)
            reject_symlinks(index)
            if not pack.exists():
                archive = self.run(["git", "-C", self.r.root, "pack-objects", "--revs", "--stdout"],
                                   data=("\n".join(self.journal["object_roots"]) + "\n").encode()).stdout
                fd, temporary = tempfile.mkstemp(prefix=".pack-", dir=self.directory)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(archive)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, pack)
                self.api["sync_directory"](backup)
            if not index.exists():
                self.git(self.r.root, "index-pack", "--strict", "-o", str(index), str(pack))
            listing = self.git(self.r.root, "verify-pack", "-v", str(index))
            stored = {line.split(" ")[0] for line in listing.splitlines()}
            if not set(self.journal["object_roots"]).issubset(stored):
                raise self.Error("Object archive does not contain all required commits/index objects")
        manifest = self.scan(backup, control=False)
        if self.journal.get("backup_manifest") and manifest != self.journal["backup_manifest"]:
            raise self.Error("Backup hashes changed; preserve and diagnose")
        self.journal["backup_manifest"] = manifest
        self.journal["backup_sha256"] = self.digest(manifest)
        self.save()

    def verify_backup(self):
        manifest = self.scan(self.directory / "backup")
        if manifest != self.journal["backup_manifest"] or self.digest(manifest) != self.journal["backup_sha256"]:
            raise self.Error("Backup hashes changed; preserve and diagnose")
        if any(self.raw_ref(ref) != oid for ref, oid in self.journal["backup_refs"].items()):
            raise self.Error("Backup pins changed; preserve and diagnose")

    def prepare_refs(self):
        entries = [e for e in self.journal["inventory"]["tasks"].values() if e["snapshot"]]
        refs = {e["new_ref"]: e["snapshot"]["head"] for e in entries}
        return self.ref_transaction(refs, [(e["old_ref"], e["snapshot"]["head"]) for e in entries])

    def prepare_destination(self):
        reject_symlinks(self.home)
        mode = self.journal["inventory"]["source_mode"]
        if self.home.exists():
            if not self.active_intent[1] or not self.home.is_dir() or stat.S_IMODE(self.home.stat().st_mode) != mode:
                raise self.Error("Migration destination appeared or its mode changed")
        else:
            self.home.mkdir()
            self.home.chmod(mode)
            self.api["sync_directory"](self.home.parent)
        return {"path": str(self.home), "mode": mode}

    def move_task(self, identity, entry, action="validate"):
        if not entry["snapshot"]:
            return
        old, new = Path(entry["old_tree"]), Path(entry["new_tree"])
        reject_symlinks(old)
        reject_symlinks(new)
        expected = entry["snapshot"]
        if old.exists() == new.exists():
            raise self.Error("Ambiguous worktree move (both or neither tree exists): " + identity)
        tree = old if old.exists() else new
        if action != "move" and tree != new:
            raise self.Error("Completed/next move destination is missing: " + identity)
        if self.active_intent and self.journal["steps"][self.active_intent[0]]["state"] == "completed" and tree != new:
            raise self.Error("Completed migration move was externally changed: " + identity)
        current = self.worktree_snapshot(tree, entry["old_ref"], entry["new_ref"])
        if any(current[k] != expected[k] for k in ("content", "head", "index_sha256", "private_git", "private_preserved")):
            raise self.Error("Worktree/index/HEAD changed during migration: " + identity)
        if self.raw_ref(entry["old_ref"]) != expected["head"] or self.raw_ref(entry["new_ref"]) != expected["head"]:
            raise self.Error("Migration task refs changed: " + identity)
        switched = current["head_ref"] == entry["new_ref"]
        if switched and "switch:" + identity not in self.journal["steps"]:
            raise self.Error("Unjournaled migration branch switch: " + identity)
        if action == "validate" and not switched:
            raise self.Error("Completed migration branch was externally changed: " + identity)
        if action == "switch" and not switched and self.journal["steps"][self.active_intent[0]]["state"] == "completed":
            raise self.Error("Completed migration branch switch was externally changed: " + identity)
        if action == "move" and tree == old:
            new.parent.mkdir(parents=True, exist_ok=True)
            self.git(self.r.root, "worktree", "move", str(old), str(new))
            self.api["sync_directory"](new.parent)
        if action == "switch" and not switched:
            self.git(new, "symbolic-ref", "HEAD", entry["new_ref"])
        after = self.worktree_snapshot(new, entry["new_ref"], entry["old_ref"] if action == "move" else None)
        if any(after[k] != expected[k] for k in ("content", "head", "index_sha256", "private_git", "private_preserved")):
            raise self.Error("Worktree contents/index changed while moving: " + identity)
        if action == "move":
            after.pop("head_ref")
        return {"worktree": str(new), **after}

    def write_new(self, path, value):
        reject_symlinks(path)
        if path.exists():
            if self.read(path) != value:
                raise self.Error("Converted artifact changed: " + str(path))
        else:
            self.write(path, value)

    def identity(self, task, legacy=False):
        return hashlib.sha256((self.journal["id"] + ":" + task + (":legacy" if legacy else ":snapshot")).encode()).hexdigest()[:32]

    def convert(self):
        inventory, stamp = self.journal["inventory"], self.journal["created_at"]
        backup = self.directory / "backup" / "manager"
        reject_symlinks(self.home)
        if not self.home.is_dir() or stat.S_IMODE(self.home.stat().st_mode) != inventory["source_mode"]:
            raise self.Error("Migration destination directory changed")
        for name in ("tasks", "events", "inbox", "worktrees", "history"):
            (self.home / name).mkdir(exist_ok=True)
        history = self.home / "history" / "v1"
        self.copy(backup, history, control=True)
        plan = backup / "plan.md"
        if plan.exists():
            self.copy(plan, self.home / "plan.md", control=True)
        tasks = {}
        for identity, entry in inventory["tasks"].items():
            item = entry["item"]
            directory = self.home / "tasks" / identity
            directory.mkdir(exist_ok=True)
            origin = backup / "tasks" / identity
            raw_history = directory / "history" / "v1"
            self.copy(origin, raw_history, control=True)
            # Preserve human artifacts verbatim; runtime controls receive v2 copies.
            excluded = {"status.json", "assignment.json", "accepted.json", "stopped.json", "history"}
            for path in origin.iterdir():
                if path.name not in excluded:
                    self.copy(path, directory / path.name, control=True)
            attempt = item["attempt"]
            assignment = self.identity(identity) if attempt else None
            try:
                report = self.read(origin / "status.json")
                if not isinstance(report, dict):
                    raise self.Error("Invalid legacy report object")
                valid_done = (attempt > 0 and report.get("task_id") == identity and report.get("attempt") == attempt
                              and report.get("state") == "done" and (origin / "result.md").is_file()
                              and bool((origin / "result.md").read_text().strip()))
            except (self.Error, OSError, ValueError):
                report, valid_done = {}, False
            accepted = item.get("accepted") is not None or (origin / "accepted.json").exists()
            state = ("queued" if attempt == 0 else item["state"] if item["state"] in ("failed", "cancelled")
                     else "verification" if valid_done else "failed")
            eligibility = "reverify_required" if accepted or state == "verification" else "unaccepted"
            diagnostic = ("Valid historical completion requires independent review/verify/accept" if state == "verification"
                          else "Original failed/cancelled state retained" if item["state"] in ("failed", "cancelled")
                          else "Unstarted task retained" if attempt == 0
                          else "Legacy completion is missing, invalid or unfinished; inspect history/v1 before retry")
            task = {**item, **self.r.namespace.envelope(identity), "branch": self.r.namespace.branch(identity),
                    "worktree": entry["new_tree"], "assignment_id": assignment, "pane": None, "alive": False,
                    "state": state, "worker_state": "done" if valid_done else state,
                    "summary": "Migrated: independent verification required" if state == "verification" else "Migrated: " + state,
                    "verification": None, "accepted": None, "accepted_history":
                        {"migration_id": self.journal["id"], "path": "tasks/" + identity + "/history/v1", "sha256": self.digest(self.scan(raw_history, control=True))} if accepted else None,
                    "acceptance_eligibility": eligibility, "operation": None, "report_error": None,
                    "origin": "migration", "migration_diagnostic": diagnostic}
            tasks[identity] = task
            converted = {**report, **self.r.namespace.envelope(identity), "attempt": attempt, "assignment_id": assignment,
                         "state": "done" if valid_done else state, "summary": task["summary"], "acks": [],
                         "updated_at": stamp, "question": None, "origin": "migration"}
            self.write_new(directory / "status.json", converted)
            if attempt:
                self.write_new(directory / "assignment.json", {**self.r.namespace.envelope(identity), "version": 2,
                    "attempt": attempt, "assignment_id": assignment, "worktree": entry["new_tree"],
                    "runtime": str(self.api["HERE"]), "auto_commit": False, "reporting_enabled": False, "origin": "migration"})
            inbox = self.home / "inbox" / identity
            inbox.mkdir(exist_ok=True)
            (self.home / "events" / identity).mkdir(exist_ok=True)
            old_inbox = backup / "inbox" / identity
            if old_inbox.exists():
                for path in old_inbox.iterdir():
                    if path.suffix != ".json" or not self.r.valid_assignment_id(path.stem):
                        continue
                    message = self.read(path)
                    old_attempt = message.get("attempt", attempt)
                    if type(old_attempt) is not int or old_attempt < 1:
                        old_attempt = max(1, attempt)
                    legacy_id = self.identity(identity + ":" + str(old_attempt), legacy=True)
                    self.write_new(inbox / path.name, {**message, **self.r.namespace.envelope(identity),
                        "message_id": path.stem, "attempt": old_attempt, "assignment_id": legacy_id, "origin": "migration"})
                    old_acks = report.get("acks", []) if old_attempt == attempt else []
                    old_status = origin / "history" / ("attempt-" + str(old_attempt)) / "status.json"
                    if old_attempt != attempt and old_status.exists():
                        try:
                            old_report = self.read(old_status)
                            old_acks = old_report.get("acks", []) if isinstance(old_report, dict) else []
                        except (self.Error, OSError, ValueError):
                            old_acks = []
                    self.write_new(directory / "history" / ("attempt-" + str(old_attempt)) / "status.json",
                        {**self.r.namespace.envelope(identity), "attempt": old_attempt, "assignment_id": legacy_id,
                         "acks": old_acks if isinstance(old_acks, list) else [], "origin": "migration"})
            for filename in (".operation.lock", ".report.lock"):
                reject_symlinks(directory / filename).touch(exist_ok=True)
        state = {**self.r.namespace.envelope(), "version": 2, "project_key": self.r.key,
                 "git_common_dir": str(self.r.common), "session": self.r.namespace.session,
                 "created_at": stamp, "updated_at": stamp, "tasks": tasks, "migration": {"id": self.journal["id"]},
                 "migrated_from": {"version": 1, "migration_id": self.journal["id"], "source_sha256": self.journal["source_sha256"]}}
        self.write_new(self.home / "state.json", state)
        self.write_new(self.home / "owner.json", {**self.r.namespace.envelope(), "version": 1,
            "generation": 0, "state": "released", "session_id": None, "token_sha256": None,
            "acquired_at": None, "last_activity_at": None, "released_at": None})
        reject_symlinks(self.home / ".lock").touch(exist_ok=True)
        self.write_new(self.home / "migration-map.json", {**self.r.namespace.envelope(), "migration_id": self.journal["id"],
            "tasks": {identity: {k: entry[k] for k in ("old_ref", "new_ref", "old_tree", "new_tree")} for identity, entry in inventory["tasks"].items()},
            "guidance": "Legacy briefs/events are verbatim history. Retry uses v2 identity; never reuse legacy report commands. Reverify accepted history before dependencies/delivery."})
        binding = self.r.control / "projects" / (self.r.key + ".json")
        self.write_new(binding, {"root": str(self.r.root), "project_key": self.r.key})
        exclude = reject_symlinks(self.r.common / "info" / "exclude")
        content = exclude.read_text() if exclude.exists() else ""
        if "/.manager/" not in content.splitlines():
            self.api["atomic_text"](exclude, content + ("\n" if content and not content.endswith("\n") else "") + "/.manager/\n")
        self.journal["converted_state"] = state
        self.journal["converted_manifest"] = self.scan(self.home, control=True, skip=("worktrees",))
        self.save()

    def validate(self):
        self.verify_backup()
        for identity, entry in self.journal["inventory"]["tasks"].items():
            self.move_task(identity, entry)
        if self.scan(self.home, control=True, skip=("worktrees",)) != self.journal["converted_manifest"]:
            raise self.Error("Converted data changed; preserve and diagnose")
        self.r.load(allow_migration=True)
        if self.r.state != self.journal["converted_state"]:
            raise self.Error("Converted state/counts mismatch")

    def complete(self):
        tombstone = {"version": 2, "kind": "migration_tombstone", "root": str(self.r.root),
                     "manager_id": self.r.manager_id, "destination": str(self.home),
                     "migration_id": self.journal["id"], "project_key": self.r.key}
        source_state = self.read(self.source / "state.json")
        self.assert_source(tombstone=source_state == tombstone)
        if source_state != tombstone:
            self.validate()
            self.write(self.source / "state.json", tombstone)
        elif self.scan(self.home, control=True, skip=("worktrees",)) != self.journal["converted_manifest"]:
            # The only permitted next state is the exact planned ready registry.
            ready = {**self.journal["converted_state"], "migration": None}
            if self.read(self.home / "state.json") != ready:
                raise self.Error("Interrupted completion destination changed")
            manifest = self.scan(self.home, control=True, skip=("worktrees", "state.json"))
            expected = {k: v for k, v in self.journal["converted_manifest"].items() if k != "state.json"}
            if manifest != expected:
                raise self.Error("Interrupted completion artifacts changed")
        ready = {**self.journal["converted_state"], "migration": None}
        if self.read(self.home / "state.json") != ready:
            self.write(self.home / "state.json", ready)
        self.phase("completed")
        self.write(self.marker, {**self.r.namespace.envelope(), "id": self.journal["id"],
                                "project_key": self.r.key, "state": "completed"})

    def completed(self, marker, journal):
        if marker["state"] != "completed" or journal["phase"] != "completed":
            return False
        state = self.read(self.home / "state.json")
        tombstone = self.read(self.source / "state.json")
        if (not self.r.namespace.matches(state) or state.get("version") != 2 or state.get("migration")
                or state.get("migrated_from", {}).get("migration_id") != journal["id"]
                or tombstone.get("kind") != "migration_tombstone" or tombstone.get("migration_id") != journal["id"]
                or tombstone.get("root") != str(self.r.root) or tombstone.get("destination") != str(self.home)):
            raise self.Error("Completed migration identity/destination mismatch")
        self.verify_backup()
        return True

    def execute(self, args):
        if args.dry_run:
            return self.preview()
        if self.marker.exists():
            marker, journal = self.load_journal()
            if self.completed(marker, journal):
                return self.result(noop=True)
            if args.resume != journal["id"]:
                raise self.Error("Pending migration requires --resume " + journal["id"])
        elif args.resume:
            raise self.Error("No matching pending migration")
        if not args.source_quiesced:
            raise self.Error("Migration/resume requires explicit --source-quiesced assertion")
        if self.journal is None and not args.expect_source:
            raise self.Error("Migration requires --expect-source from a fresh dry-run")
        self.r.control.mkdir(exist_ok=True)
        with contextlib.ExitStack() as locks:
            locks.enter_context(self.api["lock"](self.r.control / "maintenance.lock"))
            locks.enter_context(self.api["lock"](self.source / ".lock", nonblocking=True))
            if self.journal is None:
                preview = self.preview()
                # Our own held registry lock is not a source writer.
                blockers = [b for b in preview["blockers"] if b != "Busy legacy registry lock"]
                if blockers or preview["source_sha256"] != args.expect_source:
                    raise self.Error("Migration preflight/hash rejected: " + "; ".join(blockers or ["source_sha256 changed"]))
                inventory = preview["inventory"]
            else:
                inventory = self.journal["inventory"]
            for identity in sorted(inventory["tasks"]):
                locks.enter_context(self.api["lock"](self.source / "tasks" / identity / ".report.lock", nonblocking=True))
            if self.journal is None:
                # Hash files/content again after all v1 report locks are held.
                if self.source_control(inventory["source_entries"]) != inventory["control"]:
                    raise self.Error("Source changed while acquiring legacy locks")
                for entry in inventory["tasks"].values():
                    if entry["snapshot"] and self.worktree_snapshot(Path(entry["old_tree"]), entry["old_ref"]) != entry["snapshot"]:
                        raise self.Error("Source worktree changed while acquiring legacy locks")
                identity = uuid.uuid4().hex
                self.directory = reject_symlinks(self.base / identity)
                self.directory.mkdir(mode=0o700, parents=True)
                self.journal = {**self.r.namespace.envelope(), "version": 1, "id": identity,
                    "source_version": 1, "target_version": 2, "git_common_dir": str(self.r.common),
                    "destination": str(self.home), "source_sha256": args.expect_source,
                    "inventory": inventory, "phase": "preflight", "steps": {}, "errors": [], "created_at": self.api["now"]()}
                self.write(self.directory / "inventory.json", inventory)
                self.save()
                self.write(self.marker, {**self.r.namespace.envelope(), "id": identity, "project_key": self.r.key, "state": "active"})
            else:
                self.load_journal()  # Recheck after acquiring locks; no stale journal writes.
            try:
                rank = PHASES.index(self.journal["phase"])
                if rank < PHASES.index("validated"):
                    self.assert_source()
                if rank < PHASES.index("backed_up"):
                    self.checkpoint("backup", self.backup)
                    self.assert_source()
                    self.phase("backed_up")
                self.verify_backup()
                self.checkpoint("destination", self.prepare_destination)
                if rank < PHASES.index("refs_prepared"):
                    self.checkpoint("task-refs", self.prepare_refs)
                    self.phase("refs_prepared")
                for identity, entry in self.journal["inventory"]["tasks"].items():
                    self.checkpoint("move:" + identity, lambda i=identity, e=entry: self.move_task(i, e, "move"))
                    self.checkpoint("switch:" + identity, lambda i=identity, e=entry: self.move_task(i, e, "switch"))
                if rank < PHASES.index("worktrees_moved"):
                    self.phase("worktrees_moved")
                if rank < PHASES.index("data_converted"):
                    self.assert_source()
                    self.checkpoint("convert", self.convert)
                    self.phase("data_converted")
                if rank < PHASES.index("validated"):
                    self.checkpoint("validate", self.validate)
                    self.phase("validated")
                self.checkpoint("complete", self.complete)
                return self.result()
            except (self.Error, OSError, ValueError, KeyError, TypeError) as exc:
                self.journal["errors"].append({"at": self.api["now"](), "error": str(exc)})
                self.save()
                raise

    def result(self, noop=False):
        return {**self.r.namespace.envelope(), "migration_id": self.journal["id"], "phase": self.journal["phase"],
                "destination": str(self.home), "journal": str(self.directory / "journal.json"),
                "backup": str(self.directory / "backup"), "backup_sha256": self.journal.get("backup_sha256"),
                "noop": noop, "owner": "released; claim explicitly before management writes"}
