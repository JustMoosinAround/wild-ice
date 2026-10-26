import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "push_with_retry.sh"


def _bash():
    if os.name == "nt":  # avoid C:\Windows\System32\bash.exe (WSL)
        git = shutil.which("git")
        if git:
            for cand in (Path(git).parent.parent / "bin" / "bash.exe",
                         Path(git).parent.parent / "usr" / "bin" / "bash.exe"):
                if cand.exists():
                    return str(cand)
    return shutil.which("bash")


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None or shutil.which("git") is None,
                                reason="needs bash and git")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def _clone(origin, path):
    subprocess.run(["git", "clone", "-q", str(origin), str(path)], check=True,
                   capture_output=True)
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "commit.gpgsign", "false")


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    seed = tmp_path / "seed"
    _clone(origin, seed)
    git(seed, "symbolic-ref", "HEAD", "refs/heads/main")
    (seed / "README").write_text("x\n")
    git(seed, "add", "README")
    git(seed, "commit", "-q", "-m", "init")
    git(seed, "push", "-q", "origin", "main")
    a, b = tmp_path / "a", tmp_path / "b"
    _clone(origin, a)
    _clone(origin, b)
    return origin, a, b


def run_script(cwd, *args, **env):
    return subprocess.run([BASH, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, "PUSH_RETRY_SLEEP": "0", **env})


def test_rebases_over_phone_push(repos):
    origin, a, b = repos
    (a / "site/data").mkdir(parents=True)
    (a / "site/data/status.json").write_text("{}\n")
    (a / "state").mkdir()
    (a / "state/usage.json").write_text("{}\n")
    (b / "ratings").mkdir()
    (b / "ratings/x.json").write_text("{}\n")
    git(b, "add", "ratings/x.json")
    git(b, "commit", "-q", "-m", "rating")
    git(b, "push", "-q", "origin", "main")

    res = run_script(a, "2025-11-12")
    assert res.returncode == 0, res.stdout + res.stderr
    files = git(origin, "ls-tree", "-r", "--name-only", "main").split()
    assert {"site/data/status.json", "state/usage.json", "ratings/x.json"} <= set(files)
    assert git(origin, "log", "-1", "--format=%s", "main").strip() == "data: 2025-11-12"


def test_nothing_to_commit_exits_zero(repos):
    origin, a, _ = repos
    before = git(origin, "rev-parse", "main")
    res = run_script(a, "2025-11-12")
    assert res.returncode == 0, res.stdout + res.stderr
    assert git(origin, "rev-parse", "main") == before


def test_only_state_changed_still_commits(repos):
    origin, a, _ = repos
    (a / "state").mkdir()
    (a / "state/labels.json").write_text("{}\n")
    res = run_script(a, "2025-11-12")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "state/labels.json" in git(origin, "ls-tree", "-r", "--name-only", "main")


def test_gives_up_after_five_failures(repos, tmp_path):
    _, a, _ = repos
    (a / "site/data").mkdir(parents=True)
    (a / "site/data/status.json").write_text("{}\n")
    git(a, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    res = run_script(a, "2025-11-12")
    assert res.returncode == 1
    assert res.stderr.count("push attempt") == 5
