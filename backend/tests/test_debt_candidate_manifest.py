"""Historical Git-tree evidence gate for the sealed 2026-08-18 DEBT candidate."""

from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_RELATIVE_PATH = "review/evidence/DEBT_20260818_CURRENT_CANDIDATE_MANIFEST.sha256"
MANIFEST = REPO_ROOT / MANIFEST_RELATIVE_PATH
CANDIDATE_COMMIT = "b79939aa2e951ed66028c395f911c18047bbc3f3"


def _committed_candidate_rows(base_head: str, candidate_commit: str) -> dict[str, str]:
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_head, candidate_commit],
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
            candidate_commit,
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


def _blob_at_commit(candidate_commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{candidate_commit}:{path}"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    return completed.stdout


def test_debt_candidate_manifest_matches_sealed_commit() -> None:
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
    current = _committed_candidate_rows(base_head, CANDIDATE_COMMIT)
    descendant = subprocess.run(
        ["git", "merge-base", "--is-ancestor", CANDIDATE_COMMIT, "HEAD"],
        cwd=REPO_ROOT,
        check=False,
    )
    assert descendant.returncode == 0, "sealed DEBT candidate is not an ancestor of HEAD"
    assert int(headers["entries"]) == len(declared)
    assert set(declared) == set(current)

    for path, (status, expected_digest, expected_bytes) in declared.items():
        assert status == current[path]
        data = _blob_at_commit(CANDIDATE_COMMIT, path)
        assert sha256(data).hexdigest() == expected_digest
        assert len(data) == expected_bytes
