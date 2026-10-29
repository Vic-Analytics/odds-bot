-- Every sportsbook's moneyline price from the NEWEST pre-game snapshot of each game.
--
-- One row per (game, sportsbook, outcome). dashboard.py / stats.py use it to find which
-- books pay the most and the least and how far apart the books are. Live (in-play)
-- prices are excluded because the pregame_odds view hides them.

WITH newest AS (
    SELECT event_id, MAX(pulled_at) AS pulled_at
    FROM pregame_odds
    WHERE market = 'h2h'
    GROUP BY event_id
)
SELECT p.sport_key, p.event_id, p.bookmaker, p.outcome, p.price
FROM pregame_odds p
JOIN newest n ON n.event_id = p.event_id AND n.pulled_at = p.pulled_at
WHERE p.market = 'h2h';
