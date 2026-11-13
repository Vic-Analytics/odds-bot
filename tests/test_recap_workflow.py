"""Guards for the results-recap workflow: schedule, secret separation, the "already sent" marker, staying alive
(smart start), and the recap alarm ping."""

import re
from pathlib import Path

import yaml

import recap

PATH = Path(__file__).parent.parent / ".github" / "workflows" / "recap.yml"
TEXT = PATH.read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(TEXT)
STEPS = WORKFLOW["jobs"]["recap"]["steps"]


def step(name_start):
    matches = [s for s in STEPS if s.get("name", "").startswith(name_start) or s.get("uses", "").startswith(name_start)]
    assert len(matches) == 1, f"expected one step starting with {name_start!r}, found {len(matches)}"
    return matches[0]


def index(name_start):
    return STEPS.index(step(name_start))


def test_the_workflow_file_is_valid_and_has_the_expected_triggers():
    triggers = WORKFLOW.get("on") or WORKFLOW.get(True)            # YAML reads a bare `on:` as the boolean True
    assert set(triggers) == {"schedule", "workflow_dispatch"}      # never on pull requests or pushes
    assert triggers["workflow_dispatch"]["inputs"]["date"]["default"] == ""


def hours_in(field):
    hours = set()
    for part in field.split(","):
        low, _, high = part.partition("-")
        hours.update(range(int(low), int(high or low) + 1))
    return hours


def crons():
    return [entry["cron"].split() for entry in (WORKFLOW.get("on") or WORKFLOW.get(True))["schedule"]]


def test_the_timer_is_a_safety_net_every_30_minutes_never_at_the_top_of_the_hour_and_covers_the_window_in_both_seasons():
    minutes, hours = crons()[0][:2]
    assert minutes == "7,37"                                       # GitHub is busiest at :00
    # 6 PM to 10 AM Central is 23:00-15:59 UTC in summer (UTC-5) and 00:00-15:59 UTC in winter (UTC-6).
    assert {23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15} == hours_in(hours)


def test_there_is_one_schedule_entry_because_github_starts_at_most_one_run_an_hour_anyway():
    # Nov 10: two slots an hour gave exactly one run an hour. Extra slots only add load and clutter.
    assert len(crons()) == 1


def test_it_can_only_read_the_code_and_never_runs_two_timer_started_copies_at_once():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    concurrency = WORKFLOW["concurrency"]
    assert concurrency["cancel-in-progress"] is False             # a running night is never cut short by a newer run
    group = concurrency["group"]
    # Timer runs share one group (so they queue instead of both sending); a manual run gets its own group so the
    # "Run workflow" button never waits behind a night of checking.
    assert "github.event_name == 'schedule' && 'results-recap'" in group
    assert "results-recap-manual-{0}', github.run_id" in group


def test_it_is_one_job_with_no_hand_over_because_the_smart_start_never_needs_more_than_one_stretch():
    assert "strategy" not in WORKFLOW["jobs"]["recap"]             # no matrix of parts: one run covers the whole wait


def watch_flags():
    run = step("Send the recap")["run"]
    scheduled = run.split("else")[0]
    return (float(re.search(r"--keep-waiting (\d+)", scheduled).group(1)),
            float(re.search(r"--start-within (\d+)", scheduled).group(1)))


def test_a_run_that_starts_in_time_can_always_wait_until_every_game_is_final_or_given_up_on():
    keep_waiting, start_within = watch_flags()
    # The checker starts at most start_within minutes before (latest start + 90 min) and must last until the
    # latest game is given up on (latest start + 5 hours).
    longest_needed = recap.GIVE_UP_HOURS * 60 - (recap.EARLIEST_FINAL_MINUTES - start_within)
    assert keep_waiting >= longest_needed
    limit = WORKFLOW["jobs"]["recap"]["timeout-minutes"]
    assert keep_waiting + 15 <= limit < 360                        # room for setup; GitHub stops any job at 6 hours


def test_smart_start_has_a_margin_that_a_once_an_hour_timer_cannot_step_over():
    keep_waiting, start_within = watch_flags()
    # GitHub starts at most one run an hour, 5 to 70 minutes late. On Nov 12 the only evening run came 79 minutes
    # before the earliest possible finish; a 30-minute margin made it exit and nothing ran again until 4:40 AM.
    assert start_within >= 90
    # ...but the margin cannot be so wide that the longest wait no longer fits into one job (see the next test).
    assert start_within <= 150


def test_the_key_file_is_private_and_deleted_after_the_download():
    run = step("Download the odds")["run"]
    assert "chmod 600 ~/.ssh/data_deploy_key" in run and run.rstrip().endswith("rm -f ~/.ssh/data_deploy_key")
    assert "--clone data-repo" in run


def test_nothing_from_a_person_is_pasted_into_a_shell_command():
    for s in STEPS:
        if "run" in s:
            assert "${{" not in s["run"], f"step {s.get('name')!r} puts an expression inside its shell script"
    assert step("Is it time to look?")["env"]["REQUESTED_DAY"] == "${{ inputs.date }}"      # reaches the script as an env var
    assert 'recap_gate.py "$EVENT" "$REQUESTED_DAY"' in step("Is it time to look?")["run"]


def test_scheduled_runs_keep_watching_for_the_last_game_and_leave_a_marker_but_manual_runs_send_what_is_final():
    run = step("Send the recap")["run"]
    scheduled, manual = run.split("else")
    assert "--marker-file recap.marker" in scheduled and "--no-wait" not in scheduled
    assert "--keep-waiting" in scheduled and "--keep-waiting" not in manual     # a manual run answers at once
    assert "--start-within" in scheduled and "--start-within" not in manual     # and is never held back by smart start
    assert "--no-wait" in manual and "--marker-file" not in manual
    assert "--data-dir data-repo" in run


def test_the_already_sent_marker_uses_the_same_key_to_read_and_write_and_is_saved_only_when_it_exists():
    read, write = step("Was today's recap already sent?"), step("Remember that this day's recap is done")
    assert read["with"]["key"] == write["with"]["key"] == "recap-sent-${{ steps.gate.outputs.day }}"
    assert "github.event_name == 'schedule'" in read["if"] and "github.event_name == 'schedule'" in write["if"]
    assert "hashFiles('recap.marker') != ''" in write["if"]
    assert "cache-hit != 'true'" in write["if"]


def test_nothing_runs_after_the_gate_says_no_or_after_the_recap_was_already_sent():
    for name in ("actions/setup-python", "Install requirements", "Download the odds", "Send the recap"):
        condition = step(name)["if"]
        assert "steps.gate.outputs.go == 'true'" in condition
        assert "steps.already.outputs.cache-hit != 'true'" in condition


# ---------- the recap alarm (the second healthchecks.io check) ----------

def test_the_recap_ping_runs_only_after_the_recap_is_done_and_the_marker_is_saved():
    ping = step("Tell healthchecks.io")
    condition = ping["if"]
    assert "github.event_name == 'schedule'" in condition                  # a manual run is not the nightly recap
    assert "steps.gate.outputs.go == 'true'" in condition
    assert "steps.already.outputs.cache-hit != 'true'" in condition        # the run that sent it pings; later runs do not
    assert "hashFiles('recap.marker') != ''" in condition                  # only when the day is done
    assert ping["timeout-minutes"] == 1                                    # it can never hold anything up


def test_the_recap_ping_reads_the_secret_the_workflow_gives_it():
    ping = step("Tell healthchecks.io")
    name = re.search(r"--url-env (\w+)", ping["run"]).group(1)
    assert name in ping["env"] and ping["env"][name] == "${{ secrets.HEALTHCHECK_RECAP_PING_URL }}"
    assert ping["run"].startswith("python scripts/ping_healthcheck.py")
