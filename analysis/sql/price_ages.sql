-- How old each sportsbook's moneyline price was when the bot pulled it.
--
-- One row per (game, sportsbook) from the newest pre-game snapshot of each game:
-- the time of the pull and the time the sportsbook last changed that price
-- (last_update from The Odds API). The difference is the price's age.

WITH newest AS (
    SELECT event_id, MAX(pulled_at) AS pulled_at
    FROM pregame_odds
    WHERE market = 'h2h'
    GROUP BY event_id
)
SELECT p.bookmaker, p.pulled_at, MAX(p.last_update) AS last_update
FROM pregame_odds p
JOIN newest n ON n.event_id = p.event_id AND n.pulled_at = p.pulled_at
WHERE p.market = 'h2h'
GROUP BY p.event_id, p.bookmaker;
