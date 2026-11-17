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


# ---------- a manual run leaves the "sent today" marker, so a late timer run cannot send it again ----------

def test_every_run_writes_the_marker_after_the_digest_not_just_scheduled_ones():
    send_start = position("- name: Send the digest")
    send = WORKFLOW[send_start:WORKFLOW.index("# 5b.", send_start)]
    assert "python main.py --marker-file sent.marker" in send
    assert "github.event_name" not in send.split("run:")[1].split("env:")[0]       # the command no longer depends on the trigger


def test_the_marker_is_saved_for_manual_runs_too_and_only_when_the_digest_wrote_one():
    start = position("- name: Remember that today's digest was sent")
    block = WORKFLOW[start:]
    condition = next(line for line in block.splitlines() if line.strip().startswith("if:"))
    assert "github.event_name" not in condition                              # a manual run saves it as well
    assert "hashFiles('sent.marker') != ''" in condition                      # a run where everything failed leaves nothing
    assert "steps.gate.outputs.go == 'true'" in condition and "steps.already.outputs.cache-hit != 'true'" in condition


def test_a_manual_run_still_ignores_an_existing_marker_and_always_sends():
    start = position("- name: Was today's digest already sent?")
    block = WORKFLOW[start:position("# 4.")]
    condition = next(line for line in block.splitlines() if line.strip().startswith("if:"))
    assert "github.event_name == 'schedule'" in condition                    # only timer runs read the marker


# ---------- early start: a run before 7 AM waits in the job until the window opens ----------

import re

from config import EARLY_START_MINUTES


def wait_block():
    start = position("- name: Wait for the send window to open")
    return WORKFLOW[start:WORKFLOW.index("# 5.", start)]


def test_an_early_run_waits_after_installing_and_before_sending_but_only_when_it_is_going_to_send():
    assert position("- name: Install requirements") < position("- name: Wait for the send window to open") < position("- name: Send the digest")
    block = wait_block()
    assert "steps.gate.outputs.go == 'true'" in block                       # never on runs the gate turned away
    assert "steps.already.outputs.cache-hit != 'true'" in block             # never when today's digest was already sent
    assert "steps.gate.outputs.wait != '0'" in block                        # never for runs inside the window and manual runs


def test_the_wait_length_reaches_the_shell_through_an_environment_variable():
    block = wait_block()
    assert "WAIT_SECONDS: ${{ steps.gate.outputs.wait }}" in block
    assert 'sleep "$WAIT_SECONDS"' in block
    run_script = block.split("run: |")[1]
    assert "${{" not in run_script                                          # nothing is pasted into the command


def test_the_waiting_fits_in_the_time_limits_and_under_githubs_six_hours():
    job_limit = int(re.search(r"^    timeout-minutes: (\d+)", WORKFLOW, re.M).group(1))
    wait_limit = int(re.search(r"timeout-minutes: (\d+)", wait_block()).group(1))
    assert wait_limit > EARLY_START_MINUTES                                 # the longest wait is allowed to finish
    assert wait_limit + 5 <= job_limit < 360                                # room to install and send; GitHub stops jobs at 6 hours


def test_sending_still_has_its_own_short_time_limit_so_a_hang_is_cut_off_quickly():
    send = WORKFLOW[position("- name: Send the digest"):position("# 5b.")]
    assert "timeout-minutes: 10" in send


def test_a_manual_run_never_waits_because_the_gate_gives_it_wait_zero():
    # gate.py writes wait=0 for any event that is not "schedule" (see tests/test_gate.py); the step then skips itself.
    assert "steps.gate.outputs.wait != '0'" in wait_block()
