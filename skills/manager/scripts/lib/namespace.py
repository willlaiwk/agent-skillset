"""Manager namespace and cooperative routing identities (not an OS sandbox)."""
import argparse
import datetime as dt
import hashlib
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
    def session(self):
        return "manager-" + self.key + "-" + self.identity

    def legacy_check(self):
        reject_symlinks(self.container)
        source = reject_symlinks(self.container / "state.json")
        if source.exists():
            raise NamespaceError("Legacy or pending migration state at " + str(source) +
                                 "; preserve it and migrate explicitly (migration is not implemented yet)")
        if self.container.exists():
            for child in self.container.iterdir():
                if child.name in RESERVED or child.name in (".lock", "plan.md") or not child.is_dir():
                    raise NamespaceError("Legacy or unrecognized runtime artifacts at " + str(child) +
                                         "; preserve them and diagnose before initialization")

    def validate_layout(self):
        reject_symlinks(self.home)
        for name in ("state.json", "owner.json", ".lock", "events", "inbox", "tasks", "worktrees"):
            reject_symlinks(self.home / name)
        if not self.home.is_dir():
            raise NamespaceError("Manager not initialized: " + self.identity + "; run init explicitly")
        for name in ("events", "inbox", "tasks", "worktrees"):
            if not (self.home / name).is_dir():
                raise NamespaceError("Incomplete manager layout; preserve and repair: " + name)
