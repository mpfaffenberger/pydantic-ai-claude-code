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


@pytest.fixture
def fake_curl(tmp_path: Path) -> Path:
    """A `curl` on PATH that logs its URL and prints a GitHub-shaped tarball of the package folder."""
    archive = tmp_path / "repo.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(PACKAGE, "pydantic-ai-claude-code-main/src/pydantic_ai_claude_code", filter=_skip_caches)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(f'#!/bin/sh\nfor arg; do url="$arg"; done\necho "$url" >> "{tmp_path / "urls"}"\ncat "{archive}"\n')
    curl.chmod(0o755)
    return tmp_path


def _skip_caches(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    return None if "__pycache__" in info.name else info


def install(fake_curl: Path, *args: str) -> str:
    env = {**os.environ, "PATH": f"{fake_curl / 'bin'}:{os.environ['PATH']}", "XDG_CONFIG_HOME": str(fake_curl)}
    done = subprocess.run(["sh", str(ROOT / "install.sh"), *args], env=env, capture_output=True, text=True, check=True)
    return done.stdout


def test_installs_the_package_folder_as_claude_code(fake_curl: Path) -> None:
    target = fake_curl / "pydantic-clai2" / "plugins" / "claude_code"
    message = install(fake_curl)
    assert (target / "__init__.py").read_text() == (PACKAGE / "__init__.py").read_text()
    assert f"to {target}." in message
    assert f"/model claude-code:{config.MODELS[0]}." in message, "the hint names the first listed model"
    assert (fake_curl / "urls").read_text().splitlines() == [
        "https://codeload.github.com/mpfaffenberger/pydantic-ai-claude-code/tar.gz/main"
    ]


def test_reinstalling_replaces_the_old_copy_and_can_pin_a_tag(fake_curl: Path) -> None:
    target = fake_curl / "pydantic-clai2" / "plugins" / "claude_code"
    install(fake_curl)
    (target / "stale.py").write_text("")
    assert "(v0.5.0)" in install(fake_curl, "v0.5.0")
    assert not (target / "stale.py").exists()
    assert (target / "clai2.py").exists()
    assert (fake_curl / "urls").read_text().splitlines()[-1].endswith("/tar.gz/v0.5.0")
