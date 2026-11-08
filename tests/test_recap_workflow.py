"""Guards for the results-recap workflow: schedule, secret separation, and the "already sent" marker."""

from pathlib import Path

import yaml

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


def test_it_wakes_every_20_minutes_but_never_at_the_top_of_the_hour_and_covers_the_window_in_both_seasons():
    cron = (WORKFLOW.get("on") or WORKFLOW.get(True))["schedule"][0]["cron"]
    minutes, hours = cron.split()[:2]
    assert minutes == "7,27,47"                                    # GitHub is busiest at :00
    run_hours = set()
    for part in hours.split(","):
        low, _, high = part.partition("-")
        run_hours.update(range(int(low), int(high or low) + 1))
    # 6 PM to 10 AM Central is 23:00-15:59 UTC in summer (UTC-5) and 00:00-15:59 UTC in winter (UTC-6).
    assert {23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15} == run_hours


def test_it_can_only_read_the_code_and_never_runs_two_copies_at_once():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert WORKFLOW["concurrency"] == {"group": "results-recap", "cancel-in-progress": False}


def test_steps_run_in_the_right_order():
    order = [index("Is it time to look?"), index("Was today's recap already sent?"), index("actions/setup-python"),
             index("Download the odds"), index("Send the recap"), index("Remember that this day's recap is done")]
    assert order == sorted(order)


def test_the_deploy_key_is_used_only_to_download_and_the_telegram_secrets_only_to_send():
    assert TEXT.count("secrets.ODDS_DATA_DEPLOY_KEY") == 1 and TEXT.count("secrets.TELEGRAM_BOT_TOKEN") == 1
    assert TEXT.count("secrets.TELEGRAM_CHAT_ID") == 1
    download, send = step("Download the odds"), step("Send the recap")
    assert list(download["env"]) == ["DEPLOY_KEY"]
    assert "secrets.TELEGRAM" not in str(download) and "DEPLOY_KEY" not in str(send)
    assert {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"} <= set(send["env"])


def test_it_never_touches_the_odds_api_or_the_alarm_secret():
    assert "ODDS_API_KEY" not in TEXT and "HEALTHCHECK" not in TEXT


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


def test_scheduled_runs_wait_for_the_last_game_and_leave_a_marker_but_manual_runs_send_what_is_final():
    run = step("Send the recap")["run"]
    scheduled, manual = run.split("else")
    assert "--marker-file recap.marker" in scheduled and "--no-wait" not in scheduled
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
