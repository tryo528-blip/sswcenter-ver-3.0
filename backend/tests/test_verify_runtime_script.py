"""Fail-closed contracts for scripts/verify-runtime.ps1.

The runtime verifier must reject an ``-NpmExecutable`` value whose basename is
not a real npm launcher, must require that npm live next to the resolved
``node`` executable, and must not treat arbitrary non-empty ``--version``
output as npm semver.  Canonical absolute path pinning and npm binary/lock
hashing are outside the current contract because Linux and Windows official
Node installs use different paths and wrapper names.  The behavioral probe is
deliberately limited to Linux so Windows hosts do not accidentally assume
``/usr/bin/printf`` exists.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_RUNTIME = REPO_ROOT / "scripts" / "verify-runtime.ps1"
RUNTIME_VERSION_MODULE = REPO_ROOT / "scripts" / "RuntimeVersion.psm1"


def _script_source() -> str:
    return VERIFY_RUNTIME.read_text(encoding="utf-8")


def _module_source() -> str:
    return RUNTIME_VERSION_MODULE.read_text(encoding="utf-8")


def test_verify_runtime_rejects_non_npm_executable_basename() -> None:
    source = _script_source()

    assert "SSWCENTER_RUNTIME_NPM_EXECUTABLE_BASENAME_INVALID" in source
    assert "SSWCENTER_RUNTIME_NPM_NOT_SIBLING_OF_NODE" in source
    assert "GetFileName($NpmExecutable)" in source
    assert '"npm.cmd"' in source
    assert '"npm.exe"' in source
    assert '$NpmExecutableName -cne "npm"' in source
    assert "Join-Path $NodeDirectory $SiblingName" in source
    assert "RuntimeVersion.psm1" in source
    assert "Import-Module $RuntimeVersionModule -Force" in source

    sibling_default = source.index("if ([string]::IsNullOrWhiteSpace($NpmExecutable))")
    basename_guard = source.index("$NpmExecutableName = [System.IO.Path]::GetFileName")
    sibling_compare = source.index("$NpmDirectoryComparable -cne $NodeDirectoryComparable")
    postgres_import = source.index("Import-Module $PostgresModule -Force")
    semver_import = source.index("Import-Module $RuntimeVersionModule -Force")
    npm_version = source.index("$NpmVersion = Invoke-Version -Executable $NpmExecutable")
    assert (
        sibling_default
        < basename_guard
        < sibling_compare
        < postgres_import
        < semver_import
        < npm_version
    )


# Official SemVer 2.0.0 grammar from https://semver.org/#backusnaur-form-grammar-for-valid-semver-versions
# Extracted from scripts/verify-runtime.ps1 so a loose [0-9]+ core regex cannot
# silently return.  .NET -cmatch and Python re are equivalent for this pattern.
SSWCENTER_STRICT_SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

VALID_SEMVER_VECTORS = (
    "0.0.0",
    "1.2.3",
    "11.17.0",
    "1.0.0-alpha",
    "1.0.0-alpha.1",
    "1.0.0-0",
    "1.0.0-0alpha",
    "1.0.0-alpha-beta",
    "1.0.0-rc.1.2",
    "1.0.0+001",
    "1.0.0+build.01",
    "1.0.0-alpha+001",
    "1.0.0-alpha.1+build.01.sha",
)

INVALID_SEMVER_VECTORS = (
    "",
    "01.2.3",
    "1.02.3",
    "1.2.03",
    "1.2.3-01",
    "1.2.3-alpha.01",
    "1.2.3-alpha..1",
    "1.2.3-.alpha",
    "1.2.3-alpha.",
    "1.2.3+",
    "1.2.3+.",
    "1.2.3+.build",
    "1.2.3+build.",
    "1.2.3+build..1",
    "1.2",
    "1.2.3.4",
    "v1.2.3",
    "1.2.3-",
    "01.2.3-alpha",
    "1.2.3-alpha_beta",
    "1.2.3+build_01",
)


def _extract_semver_pattern(source: str) -> str:
    marker = "$SswcenterStrictSemVerPattern = '"
    start = source.index(marker) + len(marker)
    end = source.index("'", start)
    return source[start:end]


def test_verify_runtime_requires_strict_npm_semver_output() -> None:
    source = _script_source()
    module_source = _module_source()

    assert "SSWCENTER_RUNTIME_NPM_VERSION_INVALID" in source
    assert "Test-SswcenterStrictSemVer" in source
    assert "Test-SswcenterNumericIdentifier" in module_source
    assert "Test-SswcenterPrereleaseIdentifier" in module_source
    assert "Test-SswcenterBuildIdentifier" in module_source
    assert "^(0|[1-9]\\d*)" in module_source
    assert source.index("$NpmVersion = Invoke-Version -Executable $NpmExecutable") < source.index(
        "if (-not (Test-SswcenterStrictSemVer -Value $NpmVersion))"
    )
    extracted = _extract_semver_pattern(module_source)
    assert extracted == SSWCENTER_STRICT_SEMVER_PATTERN
    # The previous loose core/prerelease regex must not remain as a matcher.
    assert "-cnotmatch '^[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z.-]+)?" not in source
    assert "-cnotmatch '^[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z.-]+)?" not in module_source


def test_verify_runtime_semver_pattern_rejects_sol_counterexamples() -> None:
    extracted = _extract_semver_pattern(_module_source())
    compiled = re.compile(extracted)
    for value in VALID_SEMVER_VECTORS:
        assert compiled.fullmatch(value), value
    for value in INVALID_SEMVER_VECTORS:
        assert compiled.fullmatch(value) is None, value


def test_verify_runtime_behavior_rejects_printf_as_npm_executable() -> None:
    if os.name == "nt":
        pytest.skip("Linux-only behavioral probe for /usr/bin/printf")
    pwsh = shutil.which("pwsh")
    node = shutil.which("node")
    printf = shutil.which("printf")
    if not pwsh or not node or not printf:
        pytest.skip("requires pwsh, node, and printf on PATH")

    completed = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(VERIFY_RUNTIME),
            "-PythonExecutable",
            sys.executable,
            "-NpmExecutable",
            printf,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode != 0
    assert "SSWCENTER_RUNTIME_NPM_EXECUTABLE_BASENAME_INVALID" in completed.stderr


def _pwsh_executable() -> str | None:
    return shutil.which("pwsh")


def test_verify_runtime_semver_helpers_fail_closed_in_pwsh() -> None:
    if os.name == "nt":
        pytest.skip("Linux-only PowerShell SemVer helper probe")
    pwsh = _pwsh_executable()
    if not pwsh:
        pytest.skip("requires pwsh on PATH")

    module_literal = json.dumps(str(RUNTIME_VERSION_MODULE))
    probe = f"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module -Name {module_literal} -Force
$valid = @('0.0.0','1.2.3','11.17.0','1.0.0-alpha.1','1.0.0+001','1.0.0-alpha.1+build.01')
$invalid = @(
    '01.2.3','1.02.3','1.2.03','1.2.3-01','1.2.3-alpha.01','1.2.3-alpha..1',
    '1.2.3-.alpha','1.2.3-alpha.','1.2.3+','1.2.3+.build','1.2.3+build.',
    '1.2.3+build..1','v1.2.3','1.2',''
)
foreach ($value in $valid) {{
    if (-not (Test-SswcenterStrictSemVer -Value $value)) {{
        throw "SSWCENTER_RUNTIME_SEMVER_FALSE_NEGATIVE: $value"
    }}
}}
foreach ($value in $invalid) {{
    if (Test-SswcenterStrictSemVer -Value $value) {{
        throw "SSWCENTER_RUNTIME_SEMVER_FALSE_POSITIVE: $value"
    }}
}}
if (Test-SswcenterNumericIdentifier -Value '01') {{
    throw 'SSWCENTER_RUNTIME_SEMVER_NUMERIC_LEADING_ZERO'
}}
if (Test-SswcenterPrereleaseIdentifier -Value '') {{
    throw 'SSWCENTER_RUNTIME_SEMVER_PRERELEASE_EMPTY'
}}
if (Test-SswcenterPrereleaseIdentifier -Value '01') {{
    throw 'SSWCENTER_RUNTIME_SEMVER_PRERELEASE_LEADING_ZERO'
}}
if (Test-SswcenterBuildIdentifier -Value '') {{
    throw 'SSWCENTER_RUNTIME_SEMVER_BUILD_EMPTY'
}}
Write-Output 'SSWCENTER_RUNTIME_SEMVER_HELPERS_GREEN'
"""
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-Command", probe],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "SSWCENTER_RUNTIME_SEMVER_HELPERS_GREEN" in completed.stdout


def test_verify_runtime_behavior_rejects_invalid_npm_semver_output(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("Linux-only behavioral probe for fake npm --version")
    pwsh = _pwsh_executable()
    node = shutil.which("node")
    if not pwsh or not node:
        pytest.skip("requires pwsh and node on PATH")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_node = fake_bin / "node"
    fake_node.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then\n'
        "  printf '%s\\n' 'v24.19.0'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_node.chmod(0o755)
    fake_npm = fake_bin / "npm"
    fake_npm.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then\n'
        "  printf '%s\\n' '01.2.3'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    completed = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(VERIFY_RUNTIME),
            "-PythonExecutable",
            sys.executable,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    assert completed.returncode != 0
    combined = completed.stderr + completed.stdout
    assert "SSWCENTER_RUNTIME_NPM_VERSION_INVALID" in combined
    assert "01.2.3" in combined
