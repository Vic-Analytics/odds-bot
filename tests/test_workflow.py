"""Guards for the daily workflow file: order of steps and where the secret is used."""

from pathlib import Path

WORKFLOW = (Path(__file__).parent.parent / ".github" / "workflows" / "daily-odds.yml").read_text(encoding="utf-8")


def position(text):
    assert text in WORKFLOW, f"workflow no longer contains: {text}"
    return WORKFLOW.index(text)


def test_data_is_saved_after_the_digest_is_sent_and_before_the_marker():
    send = position("- name: Send the digest")
    save = position("- name: Save the raw odds to the private data repo")
    marker = position("- name: Remember that today's digest was sent")
    assert send < save < marker


def test_saving_data_runs_even_if_the_digest_step_failed_but_never_on_skipped_runs():
    start = position("- name: Save the raw odds to the private data repo")
    block = WORKFLOW[start:WORKFLOW.index("# 7.", start)]
    assert "if: always()" in block
    assert "steps.gate.outputs.go == 'true'" in block
    assert "steps.already.outputs.cache-hit != 'true'" in block
    assert "hashFiles('data/raw/**/*.json') != ''" in block


def test_the_deploy_key_is_only_exposed_to_the_one_step_that_needs_it():
    assert WORKFLOW.count("secrets.ODDS_DATA_DEPLOY_KEY") == 1
    start = position("- name: Save the raw odds to the private data repo")
    assert position("secrets.ODDS_DATA_DEPLOY_KEY") > start


def test_the_key_is_written_with_private_permissions():
    assert "chmod 600 ~/.ssh/data_deploy_key" in WORKFLOW
