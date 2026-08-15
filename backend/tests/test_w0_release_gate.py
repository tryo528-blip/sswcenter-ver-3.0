from __future__ import annotations

import json
import re
from pathlib import Path

from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_SCRIPT = REPO_ROOT / "scripts" / "test.ps1"
OPENAPI_SCRIPT = REPO_ROOT / "scripts" / "generate-openapi-types.ps1"
POSTGRES_SCRIPT = REPO_ROOT / "scripts" / "test-w0-postgres-linux.ps1"
GENERATED_TYPES = REPO_ROOT / "frontend" / "src" / "generated" / "sswcenter-api.ts"
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
PACKAGE_LOCK = REPO_ROOT / "frontend" / "package-lock.json"
REQUIREMENTS = REPO_ROOT / "backend" / "requirements.txt"
REQUIREMENTS_LOCK = REPO_ROOT / "backend" / "requirements.lock"


def test_general_verification_flow_invokes_openapi_and_lock_gates() -> None:
    script = TEST_SCRIPT.read_text(encoding="utf-8")
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert "generate-openapi-types.ps1" in script
    assert "-Check" in script
    assert "package-lock.json" in script
    assert "requirements.txt" in script
    assert "requirements.lock" in script
    assert "test:e2e:w0" in script
    assert "e2e/wave0-shell.spec.ts" in package["scripts"]["test:e2e:w0"]
    assert OPENAPI_SCRIPT.is_file()
    assert POSTGRES_SCRIPT.is_file()


def test_openapi_public_paths_match_checked_in_generated_types() -> None:
    document = app.openapi()
    paths = document["paths"]
    generated = GENERATED_TYPES.read_text(encoding="utf-8")
    schemas = document.get("components", {}).get("schemas", {})

    assert "/api/v1/staff" in paths
    assert "StaffResponse" in schemas
    assert '"/api/v1/staff"' in generated
    assert "StaffResponse" in generated

    missing = [path for path in paths if f'"{path}"' not in generated]
    assert missing == [], f"OPENAPI_TYPES_DRIFT: missing generated paths {missing}"


def test_dependency_locks_exist_and_cover_declared_frontend_packages() -> None:
    assert PACKAGE_LOCK.is_file(), "FRONTEND_LOCKFILE_MISSING"
    assert REQUIREMENTS.is_file(), "BACKEND_REQUIREMENTS_MISSING"
    assert REQUIREMENTS_LOCK.is_file(), "BACKEND_TRANSITIVE_LOCK_MISSING"

    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    requirements_lock = REQUIREMENTS_LOCK.read_text(encoding="utf-8")

    assert lock.get("name") == package.get("name")
    assert int(lock.get("lockfileVersion", 0)) >= 2
    lock_packages = lock.get("packages", {})
    for name in package.get("dependencies", {}):
        assert f"node_modules/{name}" in lock_packages, f"FRONTEND_LOCK_GAP: {name}"
    for name in package.get("devDependencies", {}):
        assert f"node_modules/{name}" in lock_packages, f"FRONTEND_LOCK_GAP: {name}"
    assert "fastapi==" in requirements
    assert "sqlalchemy==" in requirements

    def normalize(value: str) -> str:
        return re.sub(r"[-_.]+", "-", value).lower()

    direct_names = {
        normalize(match.group(1))
        for line in requirements.splitlines()
        if (match := re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==", line.strip()))
    }
    locked_names = {
        normalize(match.group(1))
        for line in requirements_lock.splitlines()
        if (match := re.match(r"^([A-Za-z0-9_.-]+)==", line))
    }
    assert direct_names <= locked_names
    assert len(locked_names) > len(direct_names), "BACKEND_TRANSITIVE_LOCK_IS_NOT_TRANSITIVE"
    assert {"anyio", "pydantic", "starlette", "typing-extensions"} <= locked_names
    assert "--hash=sha256:" in requirements_lock

    requirement_blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", requirements_lock)
    locked_blocks = [
        block for block in requirement_blocks if re.match(r"^[A-Za-z0-9_.-]+==", block)
    ]
    assert locked_blocks
    assert all("--hash=sha256:" in block for block in locked_blocks)
