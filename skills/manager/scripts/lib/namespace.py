"""Manager namespace and cooperative routing identities (not an OS sandbox)."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import uuid

RESERVED = frozenset({"state", "plan", "owner", "events", "inbox", "tasks", "worktrees",
                      "integration", "migrations", "backups", "runtime", "control"})


class NamespaceError(ValueError):
    pass


def manager_id(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value) or value in RESERVED:
        raise argparse.ArgumentTypeError("Manager IDs use 1–64 lowercase letters, digits, '_' or '-'; "
                                         "runtime directory names are reserved")
    return value


def generated_id():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:12]


def reject_symlinks(path):
    """Call with a canonical base plus untrusted children, before reading or writing."""
    path = Path(path)
    for part in (path, *path.parents):
        if part.is_symlink():
            raise NamespaceError("Refusing symlink runtime path: " + str(part))
    return path


class Namespace:
    def __init__(self, root, common, identity=None):
        self.root = Path(root)
        self.common = Path(common)
        self.key = hashlib.sha256(str(root).encode()).hexdigest()[:12]
        self.container = self.root / ".manager"
        self.control = self.common / "manager-runtime"
        self.identity = identity
        if identity is not None:
            manager_id(identity)
        reject_symlinks(self.container)
        reject_symlinks(self.control)
        self.home = self.container / identity if identity is not None else None
        if self.home is not None:
            reject_symlinks(self.home)

    def envelope(self, task=None):
        return {"root": str(self.root), "manager_id": self.identity, "task_id": task}

    def matches(self, record, task=None):
        return all(record.get(k) == v for k, v in self.envelope(task).items())

    def branch(self, task):
        return "manager/" + self.key + "/" + self.identity + "/tasks/" + task

    @property
    def integration_branch(self):
        return "manager/" + self.key + "/" + self.identity + "/integration"

    @property
    def session(self):
        return "manager-" + self.key + "-" + self.identity

    def legacy_check(self):
        reject_symlinks(self.container)
        source = reject_symlinks(self.container / "state.json")
        retired = self.retired_entries()
        if source.exists():
            if not retired:
                raise NamespaceError("Legacy or pending migration state at " + str(source) +
                                     "; preserve it and use migrate --dry-run or explicit --resume")
        if self.container.exists():
            for child in self.container.iterdir():
                if child.name in retired:
                    continue
                if child.name in RESERVED or child.name in (".lock", "plan.md") or not child.is_dir():
                    raise NamespaceError("Legacy or unrecognized runtime artifacts at " + str(child) +
                                         "; preserve them and diagnose before initialization")

    def retired_entries(self):
        """Only a proven completed tombstone permits v2 alongside retained history."""
        marker_path = reject_symlinks(self.container / ".migration.json")
        if not marker_path.exists():
            return set()
        def read(path):
            reject_symlinks(path)
            try:
                value = json.loads(path.read_bytes())
                if not isinstance(value, dict):
                    raise ValueError("expected object")
                return value
            except (OSError, ValueError) as exc:
                raise NamespaceError("Invalid migration artifact: " + str(path)) from exc
        marker = read(marker_path)
        identity, destination = marker.get("id"), marker.get("manager_id")
        if (not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity)
                or marker.get("root") != str(self.root) or marker.get("project_key") != self.key
                or not isinstance(destination, str)):
            raise NamespaceError("Invalid migration marker identity")
        manager_id(destination)
        journal = read(self.control / "migrations" / self.key / identity / "journal.json")
        if (type(journal.get("version")) is not int or journal.get("version") != 1
                or journal.get("id") != identity or journal.get("root") != str(self.root)
                or journal.get("manager_id") != destination or journal.get("git_common_dir") != str(self.common)
                or journal.get("destination") != str(self.container / destination)):
            raise NamespaceError("Migration journal identity mismatch")
        if marker.get("state") != "completed" or journal.get("phase") != "completed":
            raise NamespaceError("Migration pending; inspect migrate --dry-run and --resume " + identity)
        inventory = journal.get("inventory")
        if (not isinstance(inventory, dict) or hashlib.sha256(json.dumps(inventory, sort_keys=True, ensure_ascii=True).encode()).hexdigest() != journal.get("source_sha256")
                or not isinstance(inventory.get("source_entries"), list)
                or any(not isinstance(n, str) or n in ("", ".", "..") or "/" in n for n in inventory["source_entries"])):
            raise NamespaceError("Invalid completed migration inventory")
        tombstone = read(self.container / "state.json")
        state = read(self.container / destination / "state.json")
        if (type(tombstone.get("version")) is not int or tombstone.get("version") != 2 or tombstone.get("kind") != "migration_tombstone"
                or tombstone.get("root") != str(self.root) or tombstone.get("migration_id") != identity
                or tombstone.get("manager_id") != destination or tombstone.get("destination") != str(self.container / destination)
                or type(state.get("version")) is not int or state.get("version") != 2 or state.get("root") != str(self.root) or state.get("manager_id") != destination
                or state.get("migration") or state.get("migrated_from", {}).get("migration_id") != identity):
            raise NamespaceError("Completed migration tombstone/destination mismatch")
        return set(inventory["source_entries"]) | {"state.json", ".migration.json", ".lock"}

    def validate_layout(self):
        reject_symlinks(self.home)
        for name in ("state.json", "owner.json", ".lock", "events", "inbox", "tasks", "worktrees"):
            reject_symlinks(self.home / name)
        if not self.home.is_dir():
            raise NamespaceError("Manager not initialized: " + self.identity + "; run init explicitly")
        for name in ("events", "inbox", "tasks", "worktrees"):
            if not (self.home / name).is_dir():
                raise NamespaceError("Incomplete manager layout; preserve and repair: " + name)
