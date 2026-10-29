-- The consensus moneyline of EVERY pre-game snapshot of each game, so the dashboard can
-- see how the price moved between the first pull and the last pull before kickoff.
--
-- One row per (game, pull, outcome). "prob" is the average win chance the odds imply
-- across sportsbooks (it still includes the sportsbooks' margin; stats.py removes it).
-- Live (in-play) prices are excluded because the pregame_odds view hides them.

SELECT p.sport_key, p.event_id, p.commence_time, p.pulled_at, p.home_team, p.away_team, p.outcome,
       AVG(CASE WHEN p.price > 0 THEN 100.0 / (p.price + 100.0)
                ELSE -p.price / (-p.price + 100.0) END) AS prob
FROM pregame_odds p
WHERE p.market = 'h2h'
GROUP BY p.event_id, p.pulled_at, p.outcome;
