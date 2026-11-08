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


# ---------- the missed-digest alarm (healthchecks.io ping) ----------

PING_STEP = "- name: Tell healthchecks.io the digest was delivered"


def ping_block():
    start = position(PING_STEP)
    end = position("# 6.")
    return WORKFLOW[start:end]


def test_the_ping_comes_right_after_the_digest_and_before_saving_data():
    assert position("- name: Send the digest") < position(PING_STEP) < position("- name: Save the raw odds to the private data repo")


def test_the_digest_step_has_an_id_so_manual_runs_can_check_that_it_succeeded():
    send = WORKFLOW[position("- name: Send the digest"):position(PING_STEP)]
    assert "id: send" in send


def test_the_ping_can_neither_fail_the_run_nor_hang_it():
    block = ping_block()
    assert "continue-on-error: true" in block
    assert "timeout-minutes: 1" in block


def test_the_ping_only_happens_after_a_digest_was_delivered():
    block = ping_block()
    assert "if: always()" in block                                  # also after a partly failed digest
    assert "steps.gate.outputs.go == 'true'" in block               # never on runs outside the send window
    assert "steps.already.outputs.cache-hit != 'true'" in block     # an earlier run already pinged today
    assert "hashFiles('sent.marker') != ''" in block                # scheduled run: the digest wrote its marker
    assert "github.event_name == 'workflow_dispatch' && steps.send.outcome == 'success'" in block   # manual run


def test_the_ping_url_is_a_secret_used_in_one_place_and_never_pasted_into_the_command():
    assert WORKFLOW.count("secrets.HEALTHCHECK_PING_URL") == 1
    block = ping_block()
    assert "HEALTHCHECK_PING_URL: ${{ secrets.HEALTHCHECK_PING_URL }}" in block
    run_line = next(line for line in block.splitlines() if line.strip().startswith("run:"))
    assert "${{" not in run_line and run_line.strip() == "run: python scripts/ping_healthcheck.py"


def test_the_digest_steps_do_not_depend_on_the_alarm():
    assert "healthcheck" not in WORKFLOW[:position("# 5b.")].lower()      # nothing before the ping step mentions it
    assert "needs:" not in WORKFLOW


# ---------- the daily results workflow ----------

RESULTS = (Path(__file__).parent.parent / ".github" / "workflows" / "results.yml").read_text(encoding="utf-8")


def test_results_job_saves_files_only_then_publishes_even_if_a_league_failed():
    fetch = RESULTS.index("python results.py --files-only")
    save = RESULTS.index("- name: Save the scores to the private data repo")
    assert fetch < save
    block = RESULTS[save:]
    assert "if: always()" in block and "hashFiles('data/results_raw/**/*.json') != ''" in block
    assert "--publish data/results_raw=results_raw" in block


def test_results_job_uses_the_deploy_key_only_where_needed_and_avoids_the_top_of_the_hour():
    assert RESULTS.count("secrets.ODDS_DATA_DEPLOY_KEY") == 1
    assert "secrets.ODDS_API_KEY" not in RESULTS           # it never touches the Odds API
    assert 'cron: "37 12 * * *"' in RESULTS


def test_the_days_input_reaches_the_script_through_an_environment_variable():
    # Not pasted straight into the shell command, which would allow command injection.
    assert 'DAYS: ${{ inputs.days || \'2\' }}' in RESULTS
    assert '--days "$DAYS"' in RESULTS
