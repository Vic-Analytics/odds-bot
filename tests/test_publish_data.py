"""Tests for publishing data files to the private repo, using a local stand-in repo."""

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "publish_data.py"
spec = importlib.util.spec_from_file_location("publish_data", SCRIPT)
publish_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish_data)

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "core.autocrlf=false"]


def git(*args, cwd):
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def remote(tmp_path):
    """A bare 'GitHub' repo that already has one commit on main."""
    bare = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    git("init", "-b", "main", str(seed), cwd=tmp_path)
    (seed / "README.md").write_text("data repo\n")
    git("add", "-A", cwd=seed)
    git("commit", "-m", "start", cwd=seed)
    git("remote", "add", "origin", str(bare), cwd=seed)
    git("push", "origin", "main", cwd=seed)
    return bare


def clone(remote, tmp_path, name="check"):
    target = tmp_path / name
    git("clone", "--quiet", str(remote), str(target), cwd=tmp_path)
    return target


def commit_count(repo):
    out = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=repo, capture_output=True, text=True)
    return int(out.stdout)


@pytest.fixture
def local_data(tmp_path):
    raw = tmp_path / "data" / "raw" / "2026-10-28"
    raw.mkdir(parents=True)
    (raw / "icehockey_nhl__134855Z.json").write_bytes(b'[{"id":"a"}]')
    (raw / "soccer_epl__134901Z.json").write_bytes(b'[{"id":"b"}]')
    (raw / "soccer_epl__134901Z.json.tmp").write_bytes(b"half written")     # must be ignored
    return tmp_path / "data" / "raw"


def test_new_files_are_added_under_the_chosen_folder(remote, local_data, tmp_path):
    added = publish_data.publish([(local_data, "raw")], str(remote))
    assert added == 2
    repo = clone(remote, tmp_path)
    assert (repo / "raw" / "2026-10-28" / "icehockey_nhl__134855Z.json").read_bytes() == b'[{"id":"a"}]'
    assert not list(repo.rglob("*.tmp"))
    assert (repo / "README.md").exists()


def test_publishing_again_adds_nothing_and_makes_no_commit(remote, local_data, tmp_path):
    publish_data.publish([(local_data, "raw")], str(remote))
    first = commit_count(clone(remote, tmp_path, "one"))
    assert publish_data.publish([(local_data, "raw")], str(remote)) == 0
    assert commit_count(clone(remote, tmp_path, "two")) == first


def test_only_the_new_files_are_added_next_time(remote, local_data, tmp_path):
    publish_data.publish([(local_data, "raw")], str(remote))
    (local_data / "2026-10-29").mkdir()
    (local_data / "2026-10-29" / "basketball_nba__141500Z.json").write_bytes(b"[]")
    assert publish_data.publish([(local_data, "raw")], str(remote)) == 1


def test_an_existing_file_is_never_overwritten(remote, local_data, tmp_path):
    publish_data.publish([(local_data, "raw")], str(remote))
    (local_data / "2026-10-28" / "icehockey_nhl__134855Z.json").write_bytes(b"CHANGED")
    assert publish_data.publish([(local_data, "raw")], str(remote)) == 0
    repo = clone(remote, tmp_path)
    assert (repo / "raw" / "2026-10-28" / "icehockey_nhl__134855Z.json").read_bytes() == b'[{"id":"a"}]'


def test_two_folders_go_in_one_commit(remote, local_data, tmp_path):
    results = tmp_path / "data" / "results_raw" / "2026-10-27"
    results.mkdir(parents=True)
    (results / "icehockey_nhl__123700Z.json").write_bytes(b"{}")
    added = publish_data.publish([(local_data, "raw"), (tmp_path / "data" / "results_raw", "results_raw")], str(remote))
    assert added == 3
    repo = clone(remote, tmp_path)
    assert commit_count(repo) == 2                      # the starting commit + one
    assert (repo / "results_raw" / "2026-10-27" / "icehockey_nhl__123700Z.json").exists()


def test_a_missing_source_folder_is_fine(remote, tmp_path):
    assert publish_data.publish([(tmp_path / "nothing_here", "raw")], str(remote)) == 0


def test_if_someone_else_pushes_first_it_retries_and_keeps_both(remote, local_data, tmp_path):
    def competing_push(attempt):
        if attempt == 1:                                # another workflow pushes just before us
            other = clone(remote, tmp_path, "other")
            (other / "results_raw").mkdir()
            (other / "results_raw" / "theirs.json").write_text("{}")
            git("add", "-A", cwd=other)
            git("commit", "-m", "theirs", cwd=other)
            git("push", "origin", "main", cwd=other)

    added = publish_data.publish([(local_data, "raw")], str(remote), before_push=competing_push)
    assert added == 2
    repo = clone(remote, tmp_path)
    assert (repo / "results_raw" / "theirs.json").exists()                       # their file is kept
    assert (repo / "raw" / "2026-10-28" / "soccer_epl__134901Z.json").exists()   # and ours was added


def test_a_failing_remote_raises_a_readable_error(local_data, tmp_path):
    with pytest.raises(RuntimeError, match="git clone failed"):
        publish_data.publish([(local_data, "raw")], str(tmp_path / "does_not_exist.git"))


def test_the_command_line_reports_failure_with_exit_code_1(local_data, tmp_path, capsys):
    code = publish_data.main(["--publish", f"{local_data}=raw", "--repo-url", str(tmp_path / "nope.git")])
    assert code == 1
    assert "publish failed" in capsys.readouterr().err


# ---------- downloading the data repo (for the results recap) ----------

def test_clone_downloads_the_data_and_makes_no_commit(remote, local_data, tmp_path):
    publish_data.publish([(local_data, "raw")], str(remote))
    before = commit_count(clone(remote, tmp_path, "before"))
    destination = tmp_path / "downloaded"
    publish_data.clone(destination, str(remote))
    assert (destination / "raw" / "2026-10-28" / "icehockey_nhl__134855Z.json").exists()
    assert commit_count(destination) == before
    assert commit_count(clone(remote, tmp_path, "after")) == before                # nothing was pushed


def test_clone_refuses_a_folder_that_already_has_files(remote, tmp_path):
    destination = tmp_path / "busy"
    destination.mkdir()
    (destination / "keep.txt").write_text("mine")
    with pytest.raises(RuntimeError, match="not empty"):
        publish_data.clone(destination, str(remote))
    assert (destination / "keep.txt").read_text() == "mine"


def test_the_command_line_can_clone_and_reports_failure(remote, tmp_path, capsys):
    assert publish_data.main(["--clone", str(tmp_path / "got"), "--repo-url", str(remote)]) == 0
    assert (tmp_path / "got" / "README.md").exists()
    assert publish_data.main(["--clone", str(tmp_path / "got2"), "--repo-url", str(tmp_path / "nope.git")]) == 1
    assert "clone failed" in capsys.readouterr().err


def test_the_command_line_needs_exactly_one_of_clone_or_publish(tmp_path):
    with pytest.raises(SystemExit, match="Nothing to do"):
        publish_data.main([])
    with pytest.raises(SystemExit, match="either --clone or --publish"):
        publish_data.main(["--clone", str(tmp_path / "x"), "--publish", "a=b"])


def test_git_env_uses_the_deploy_key_and_never_prompts():
    env = publish_data.git_env("/home/runner/.ssh/key")
    assert "-i \"/home/runner/.ssh/key\"" in env["GIT_SSH_COMMAND"] and "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert publish_data.git_env().get("GIT_SSH_COMMAND") == os.environ.get("GIT_SSH_COMMAND")      # no key: leave ssh alone
