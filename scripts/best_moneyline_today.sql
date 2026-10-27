-- Today's best moneyline for each team, across all bookmakers.
--
-- "Today" means games starting today in Central time. SQLite has no time
-- zones, so the offset is written out: Central is UTC-5 from March to early
-- November and UTC-6 the rest of the year. Change '-5 hours' to '-6 hours'
-- (in the three places) in winter.
--
-- It uses the newest PRE-GAME snapshot of each game (pregame_odds hides
-- prices pulled after kickoff, which are live odds).
--
--   sqlite3 data/odds.db < scripts/best_moneyline_today.sql

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
      AND date(p.commence_time, '-5 hours') = date('now', '-5 hours')
)
SELECT sport_key,
       datetime(commence_time, '-5 hours') AS start_central,
       home_team, away_team,
       outcome   AS team,
       price     AS best_price,
       bookmaker
FROM ranked
WHERE rn = 1
ORDER BY commence_time, home_team, outcome;
