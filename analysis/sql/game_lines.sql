-- One row per FINISHED game, with the consensus PRE-GAME lines and the result.
--
-- "Consensus" = the average across sportsbooks, using the newest snapshot taken
-- before the game started (the pregame_odds view hides live odds). Prices are
-- turned into implied win probabilities (they still include the sportsbook's
-- margin, which is roughly equal on both sides, so comparing the two is fair).
--
--   home_prob / away_prob / draw_prob   average implied probability from the moneyline
--   home_spread                         the most common point spread for the home team
--   total_line                          the most common over/under line
--   home_underdog                       1 when the market rated the home team less likely to win
--   went_over                           1 over, 0 under, NULL for a push or no line
--
-- Needs data/odds.db built with scripts/backfill_from_raw.py (odds AND scores).

WITH newest AS (                         -- newest pre-game snapshot of each market of each game
    SELECT event_id, market, MAX(pulled_at) AS pulled_at
    FROM pregame_odds
    GROUP BY event_id, market
),
latest AS (
    SELECT p.*,
           CASE WHEN p.price > 0 THEN 100.0 / (p.price + 100.0)
                ELSE -p.price / (-p.price + 100.0) END AS implied_prob
    FROM pregame_odds p
    JOIN newest n ON n.event_id = p.event_id AND n.market = p.market AND n.pulled_at = p.pulled_at
),
moneyline AS (
    SELECT event_id,
           AVG(CASE WHEN outcome = home_team THEN implied_prob END) AS home_prob,
           AVG(CASE WHEN outcome = away_team THEN implied_prob END) AS away_prob,
           AVG(CASE WHEN outcome = 'Draw'    THEN implied_prob END) AS draw_prob,
           COUNT(DISTINCT bookmaker) AS moneyline_books,
           MAX(pulled_at)            AS moneyline_pulled_at
    FROM latest
    WHERE market = 'h2h'
    GROUP BY event_id
),
total_counts AS (
    SELECT event_id, point, COUNT(*) AS n
    FROM latest WHERE market = 'totals' GROUP BY event_id, point
),
total_line AS (                          -- the most common line (the lower one if tied)
    SELECT event_id, point AS total_line
    FROM (SELECT event_id, point,
                 ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY n DESC, point) AS rn
          FROM total_counts)
    WHERE rn = 1
),
spread_counts AS (
    SELECT event_id, point, COUNT(*) AS n
    FROM latest WHERE market = 'spreads' AND outcome = home_team GROUP BY event_id, point
),
spread_line AS (
    SELECT event_id, point AS home_spread
    FROM (SELECT event_id, point,
                 ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY n DESC, ABS(point)) AS rn
          FROM spread_counts)
    WHERE rn = 1
)
SELECT e.event_id, e.sport_key, e.commence_time, e.home_team, e.away_team,
       m.moneyline_pulled_at, m.moneyline_books, m.home_prob, m.away_prob, m.draw_prob,
       s.home_spread, t.total_line,
       r.home_score, r.away_score, r.status,
       r.home_score + r.away_score                              AS total_points,
       CASE WHEN r.home_score > r.away_score THEN 1 ELSE 0 END  AS home_won,
       CASE WHEN m.home_prob < m.away_prob   THEN 1 ELSE 0 END  AS home_underdog,
       CASE WHEN r.home_score + r.away_score > t.total_line THEN 1
            WHEN r.home_score + r.away_score < t.total_line THEN 0 END AS went_over
FROM events e
JOIN results   r ON r.event_id = e.event_id AND r.completed = 1
JOIN moneyline m ON m.event_id = e.event_id
LEFT JOIN spread_line s ON s.event_id = e.event_id
LEFT JOIN total_line  t ON t.event_id = e.event_id
ORDER BY e.commence_time;
