"""
check_emoji.py - which teams in the schedule have NO emoji yet?

Run it now and then (for example when a new season starts and clubs have been
promoted or relegated). It uses only the FREE events endpoint, so it costs
0 credits.

    python check_emoji.py

For each league with emoji it lists the team names the API is using that the
emoji files don't know. Add those to team_emoji.py or soccer_emoji.py.
(MMA is skipped: the feed includes many small-show fighters you don't need.)
"""

import soccer_emoji
from config import SPORTS
from odds_api import fetch_events
from team_emoji import TEAM_EMOJI, emoji_for


def is_mapped(sport_name, key, team):
    """True if this team already has an emoji."""
    if key.startswith("soccer_"):
        return soccer_emoji._norm(team) in soccer_emoji._LOOKUP
    return bool(emoji_for(sport_name, team))


if __name__ == "__main__":
    for sport_name, key in SPORTS.items():
        if not (key.startswith("soccer_") or sport_name in TEAM_EMOJI):
            continue  # this sport has no emoji system (or it's MMA)

        teams = set()
        for event in fetch_events(key):
            teams.update([event["home_team"], event["away_team"]])

        missing = sorted(t for t in teams if not is_mapped(sport_name, key, t))
        status = f"{len(teams) - len(missing)}/{len(teams)} mapped"
        print(f"{sport_name:17} {status}" + (f"  MISSING: {missing}" if missing else ""))
