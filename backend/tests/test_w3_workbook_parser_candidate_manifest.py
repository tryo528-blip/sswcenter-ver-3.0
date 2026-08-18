"""Worktree-or-commit evidence gate for the W3 workbook parser candidate."""

from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_RELATIVE_PATH = (
    "review/evidence/W3_20260818_WORKBOOK_PARSER_CURRENT_CANDIDATE_MANIFEST.sha256"
)
MANIFEST = REPO_ROOT / MANIFEST_RELATIVE_PATH


def _current_dirty_rows() -> dict[str, str]:
    completed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--no-renames",
        ],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    rows: dict[str, str] = {}
    for field in completed.stdout.decode("utf-8").split("\0"):
        if not field:
            continue
        status = field[:2]
        path = field[3:]
        if path != MANIFEST_RELATIVE_PATH and not path.startswith(".codex/"):
            rows[path] = status
    return rows


def _current_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _committed_candidate_rows(base_head: str) -> dict[str, str]:
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_head, "HEAD"],
        cwd=REPO_ROOT,
        check=False,
    )
    assert ancestor.returncode == 0, f"manifest base is not an ancestor: {base_head}"

    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "--no-renames",
            "-z",
            base_head,
            "HEAD",
            "--",
        ],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    fields = completed.stdout.decode("utf-8").split("\0")
    rows: dict[str, str] = {}
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        path = fields[index + 1]
        if path != MANIFEST_RELATIVE_PATH and not path.startswith(".codex/"):
            rows[path] = {"A": "??", "M": " M"}.get(status, status)
        index += 2
    return rows


def test_w3_workbook_parser_candidate_manifest_matches_worktree_or_commit() -> None:
    declared: dict[str, tuple[str, str, int]] = {}
    headers: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and ": " in line:
            key, value = line[2:].split(": ", 1)
            headers[key] = value
            continue
        if not line or line.startswith("#"):
            continue
        status, digest, byte_count, path = line.split("|", 3)
        declared[path] = (status, digest, int(byte_count))

    base_head = headers["head"]
    if _current_head() == base_head:
        current = _current_dirty_rows()
    else:
        dirty = _current_dirty_rows()
        assert not dirty, f"committed candidate worktree is dirty: {dirty}"
        current = _committed_candidate_rows(base_head)
    assert int(headers["entries"]) == len(declared)
    assert set(declared) == set(current)

    for path, (status, expected_digest, expected_bytes) in declared.items():
        assert status == current[path]
        data = (REPO_ROOT / path).read_bytes()
        assert sha256(data).hexdigest() == expected_digest
        assert len(data) == expected_bytes
