"""`install.sh`, the one-liner install: run offline against a `curl` that serves this checkout as GitHub would."""

from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path

import pytest

import pydantic_ai_claude_code
from pydantic_ai_claude_code import config

ROOT = Path(__file__).parent.parent
PACKAGE = Path(pydantic_ai_claude_code.__file__).parent


PYPI = "https://pypi.org/pypi/pydantic-claude-code/json"
CODELOAD = "https://codeload.github.com/mpfaffenberger/pydantic-ai-claude-code/tar.gz"
# Trimmed from PyPI's real answer: release files also carry keys, but none named "version".
RELEASES = '{"info": {"name": "pydantic-claude-code", "version": "0.7.1"}, "releases": {"0.7.1": [{"size": 1}]}}'


@pytest.fixture
def fake_curl(tmp_path: Path) -> Path:
    """A `curl` on PATH that logs its URL, answers PyPI with `releases.json`, and GitHub with the package folder."""
    archive = tmp_path / "repo.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(PACKAGE, "pydantic-ai-claude-code-main/src/pydantic_ai_claude_code", filter=_skip_caches)
    (tmp_path / "releases.json").write_text(RELEASES)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        f'#!/bin/sh\nfor arg; do url="$arg"; done\necho "$url" >> "{tmp_path / "urls"}"\n'
        f'case "$url" in *pypi.org*) cat "{tmp_path / "releases.json"}" ;; *) cat "{archive}" ;; esac\n'
    )
    curl.chmod(0o755)
    return tmp_path


def _skip_caches(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    return None if "__pycache__" in info.name else info


def install(fake_curl: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": f"{fake_curl / 'bin'}:{os.environ['PATH']}", "XDG_CONFIG_HOME": str(fake_curl)}
    return subprocess.run(["sh", str(ROOT / "install.sh"), *args], env=env, capture_output=True, text=True, check=check)


def urls(fake_curl: Path) -> list[str]:
    return (fake_curl / "urls").read_text().splitlines()


def test_installs_the_latest_release_as_claude_code(fake_curl: Path) -> None:
    target = fake_curl / "pydantic-clai2" / "plugins" / "claude_code"
    message = install(fake_curl).stdout
    assert (target / "__init__.py").read_text() == (PACKAGE / "__init__.py").read_text()
    assert f"(v0.7.1) to {target}." in message
    assert f"/model claude-code:{config.MODELS[0]}." in message, "the hint names the first listed model"
    assert urls(fake_curl) == [PYPI, f"{CODELOAD}/v0.7.1"]


def test_reinstalling_replaces_the_old_copy_and_can_pin_a_ref(fake_curl: Path) -> None:
    target = fake_curl / "pydantic-clai2" / "plugins" / "claude_code"
    install(fake_curl)
    (target / "stale.py").write_text("")
    assert "(main)" in install(fake_curl, "main").stdout
    assert not (target / "stale.py").exists()
    assert (target / "clai2.py").exists()
    assert urls(fake_curl)[-1] == f"{CODELOAD}/main", "a given ref skips the PyPI lookup"


def test_says_what_to_do_when_pypi_has_no_answer(fake_curl: Path) -> None:
    (fake_curl / "releases.json").write_text("")
    done = install(fake_curl, check=False)
    assert done.returncode == 1
    assert "Pass a tag (sh -s -- v0.6.0) or main." in done.stderr
    assert not (fake_curl / "pydantic-clai2").exists()
