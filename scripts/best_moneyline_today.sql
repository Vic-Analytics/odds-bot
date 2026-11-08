-- Today's best moneyline for each team, across all bookmakers.
--
-- "Today" means games starting today in Central time. SQLite has no time zone
-- database, so this file does not guess an offset (Central is UTC-5 in summer
-- and UTC-6 in winter, and writing either one in by hand goes wrong twice a
-- year). Instead it takes the day as two UTC times, :day_start and :day_end.
-- scripts/best_moneyline_today.py works those out with Python's time zone
-- database, daylight saving included, and runs this query:
--
--   python scripts/best_moneyline_today.py
--   python scripts/best_moneyline_today.py --date 2026-11-08
--
-- (To run it by hand in another SQLite tool, set :day_start and :day_end to
-- the UTC start and end of the Central day, for example '2026-11-08T06:00:00Z'
-- and '2026-11-09T06:00:00Z'.)
--
-- It uses the newest PRE-GAME snapshot of each game (pregame_odds hides
-- prices pulled after kickoff, which are live odds).

WITH latest AS (                          -- newest pre-game snapshot per game
    SELECT event_id, MAX(pulled_at) AS pulled_at
    FROM pregame_odds
    WHERE market = 'h2h'
    GROUP BY event_id
),
ranked AS (                               -- best price first, for each team in each game
    SELECT p.sport_key, p.commence_time, p.home_team, p.away_team,
           p.outcome, p.price, p.bookmaker,
           ROW_NUMBER() OVER (PARTITION BY p.event_id, p.outcome
                              ORDER BY p.price DESC, p.bookmaker) AS rn
    FROM pregame_odds p
    JOIN latest l ON l.event_id = p.event_id AND l.pulled_at = p.pulled_at
    WHERE p.market = 'h2h'
      AND p.commence_time >= :day_start
      AND p.commence_time <  :day_end
)
SELECT sport_key,
       commence_time,
       home_team, away_team,
       outcome   AS team,
       price     AS best_price,
       bookmaker
FROM ranked
WHERE rn = 1
ORDER BY commence_time, home_team, outcome;
