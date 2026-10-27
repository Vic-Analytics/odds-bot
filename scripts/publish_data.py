"""
publish_data.py - copy new data files into the private odds-history-data repo.

The bot runs on GitHub's temporary machines, which are wiped after every run.
This script is how the files it saved (data/raw/... and later
data/results_raw/...) get into a permanent home: a separate PRIVATE repo.

    python scripts/publish_data.py --publish data/raw=raw --ssh-key ~/.ssh/key

Each --publish takes SOURCE_FOLDER=FOLDER_IN_THE_DATA_REPO. Rules:
  * Only .json files are copied.
  * Files are only ever ADDED. A file that already exists in the data repo is
    never overwritten, so history can't be damaged by a rerun.
  * If nothing is new, nothing is committed.
  * If someone else pushed first (for example the other workflow), we fetch
    their commit and try again, up to 3 times.

Standard library only.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_REPO = "git@github.com:Vic-Analytics/odds-history-data.git"
COMMIT_NAME = "Vic_Analytics"
COMMIT_EMAIL = "341802042+Vic-Analytics@users.noreply.github.com"


def run_git(args, cwd, env):
    """Run one git command; raise a readable error if it fails."""
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {(result.stderr or result.stdout).strip()[:500]}")
    return result.stdout.strip()


def new_files(pairs, repo_dir):
    """The (source file, destination file) pairs that are not in the data repo yet."""
    todo = []
    for source_dir, dest_name in pairs:
        source_dir = Path(source_dir)
        if not source_dir.is_dir():
            continue
        for path in sorted(source_dir.rglob("*.json")):
            destination = Path(repo_dir) / dest_name / path.relative_to(source_dir)
            if not destination.exists():
                todo.append((path, destination))
    return todo


def publish(pairs, repo_url=DEFAULT_REPO, ssh_key=None, attempts=3, before_push=None):
    """Add any new files to the data repo. Returns how many files were added.

    pairs        list of (source_folder, folder_in_data_repo)
    before_push  for the tests only: called right before each push
    """
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if ssh_key:
        env["GIT_SSH_COMMAND"] = (
            f'ssh -i "{ssh_key}" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes'
        )

    with tempfile.TemporaryDirectory() as temp:
        repo = Path(temp) / "data-repo"
        run_git(["clone", "--quiet", repo_url, str(repo)], temp, env)
        branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo, env)

        for attempt in range(1, attempts + 1):
            todo = new_files(pairs, repo)
            if not todo:
                return 0
            for source, destination in todo:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)

            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            run_git(["add", "-A"], repo, env)
            run_git(["-c", f"user.name={COMMIT_NAME}", "-c", f"user.email={COMMIT_EMAIL}",
                     "commit", "--quiet", "-m", f"Add {len(todo)} data file(s), {stamp}"], repo, env)
            if before_push:
                before_push(attempt)
            try:
                run_git(["push", "--quiet", "origin", f"HEAD:{branch}"], repo, env)
                return len(todo)
            except RuntimeError as error:
                if attempt == attempts:
                    raise
                print(f"push attempt {attempt} was rejected ({error}); fetching and trying again")
                # Someone else pushed first. Start from their version and re-add our files.
                run_git(["fetch", "--quiet", "origin", branch], repo, env)
                run_git(["reset", "--quiet", "--hard", f"origin/{branch}"], repo, env)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Copy new data files into the private data repo.")
    parser.add_argument("--publish", action="append", required=True, metavar="SOURCE=DEST",
                        help="source folder and the folder to put it in inside the data repo")
    parser.add_argument("--repo-url", default=os.environ.get("ODDS_DATA_REPO", DEFAULT_REPO))
    parser.add_argument("--ssh-key", default=None, help="path to the deploy key (private half)")
    args = parser.parse_args(argv)

    pairs = []
    for item in args.publish:
        source, _, dest = item.partition("=")
        if not source or not dest:
            raise SystemExit(f"--publish needs SOURCE=DEST, got: {item}")
        pairs.append((source, dest))

    try:
        added = publish(pairs, args.repo_url, args.ssh_key)
    except RuntimeError as error:
        print(f"publish failed: {error}", file=sys.stderr)
        return 1
    print(f"Published {added} new file(s) to the data repo." if added else "Nothing new to publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
