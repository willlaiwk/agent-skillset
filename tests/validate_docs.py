#!/usr/bin/env python3
"""Check maintained Markdown links/fences and current CLI example syntax.

Does not execute example commands or validate historical design.md CLI sketches.
Run from any directory with Python 3.9+; no third-party dependencies.
"""
import contextlib
import importlib.util
from importlib.machinery import SourceFileLoader
import io
from pathlib import Path
import re
import shlex
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/manager"


def markdown_parts(path):
    prose, blocks, block = [], [], None
    fence = None
    language = ""
    for number, line in enumerate(path.read_text().splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if marker and fence is None:
            fence, language, block = marker[1], marker[2].strip(), []
        elif marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
            blocks.append((language, "\n".join(block)))
            fence, block = None, None
        elif fence is None:
            prose.append((number, line))
        else:
            block.append(line)
    if fence is not None:
        raise ValueError(str(path.relative_to(ROOT)) + ": unclosed code fence")
    return prose, blocks


def anchors(prose):
    result, counts = set(), {}
    for _, line in prose:
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        title = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", match[1])
        title = re.sub(r"<[^>]+>", "", title).lower()
        slug = "".join(c for c in title if c.isalnum() or c in " _-").replace(" ", "-")
        count = counts.get(slug, 0)
        result.add(slug + ("-" + str(count) if count else ""))
        counts[slug] = count + 1
    return result


def main():
    paths = sorted([ROOT / "README.md", ROOT / "SKILL.md", *ROOT.glob("docs/**/*.md"),
                    *ROOT.glob("references/**/*.md"), *ROOT.glob("templates/**/*.md")])
    parsed = {path: markdown_parts(path) for path in paths}
    errors, links, examples = [], 0, 0
    for path, (prose, _) in parsed.items():
        for number, line in prose:
            for match in re.finditer(r"!?\[[^]\n]*\]\(([^)\n]+)\)", line):
                url = match[1].strip().strip("<>")
                parts = urlsplit(url)
                if parts.scheme or parts.netloc:
                    continue
                target = (path.parent / unquote(parts.path)).resolve() if parts.path else path
                links += 1
                if not target.exists():
                    errors.append(f"{path.relative_to(ROOT)}:{number}: missing link {url}")
                elif parts.fragment and target.suffix == ".md":
                    target_prose = parsed[target][0] if target in parsed else markdown_parts(target)[0]
                    if unquote(parts.fragment) not in anchors(target_prose):
                        errors.append(f"{path.relative_to(ROOT)}:{number}: missing anchor {url}")

    sys.path.insert(0, str(CLI.parent))
    spec = importlib.util.spec_from_loader("manager_docs_check", SourceFileLoader("manager_docs_check", str(CLI)))
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    published = [ROOT / "README.md", ROOT / "SKILL.md", *ROOT.glob("references/**/*.md"),
                 *ROOT.glob("templates/**/*.md"), ROOT / "docs/specs/001-multi-manager-isolation.md"]
    for path in published:
        for language, block in parsed[path][1]:
            if language not in ("sh", "bash", "shell"):
                continue
            for line in block.replace("\\\n", " ").splitlines():
                words = shlex.split(line, comments=True)
                if not words:
                    continue
                if words[0] == "manager":
                    arguments = words[1:]
                elif (len(words) > 1 and words[0] == "python3" and
                      (words[1] == "scripts/manager" or words[1].endswith("/scripts/manager"))):
                    arguments = words[2:]
                else:
                    continue
                # Uppercase ID in SKILL.md is a replacement placeholder, not a legal selector.
                arguments = ["example-id" if word == "ID" else word for word in arguments]
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        runtime.parser().parse_args(arguments)
                except SystemExit as exc:
                    if exc.code != 0:
                        errors.append(f"{path.relative_to(ROOT)}: CLI example failed ({exc.code}): {line}")
                examples += 1
    if errors:
        raise ValueError("\n".join(errors))
    print(f"PASS: {len(paths)} Markdown files, {links} local links/anchors, paired fences, {examples} CLI examples")
    print("CLI parsing only; runtime behavior is covered by test_manager.py. Historical design examples are excluded.")


if __name__ == "__main__":
    main()
