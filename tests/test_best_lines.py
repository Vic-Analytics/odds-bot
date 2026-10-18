"""Tests for picking the best line across sportsbooks."""

from format_digest import best_moneylines, best_spreads, best_totals
from helpers import book, game, outcome


def test_moneyline_takes_the_highest_price_and_names_the_book():
    g = game("Home", "Away", books=[
        book("A", h2h=[outcome("Home", -110), outcome("Away", 100)]),
        book("B", h2h=[outcome("Home", -105), outcome("Away", 130)]),
        book("C", h2h=[outcome("Home", -120), outcome("Away", 125)]),
    ])
    best = best_moneylines(g)
    # -105 beats -110 and -120; +130 beats +125 and +100
    assert best["Home"] == (-105, "B")
    assert best["Away"] == (130, "B")


def test_moneyline_includes_the_draw_for_soccer():
    g = game("Home", "Away", books=[
        book("A", h2h=[outcome("Home", 150), outcome("Draw", 240), outcome("Away", 180)]),
        book("B", h2h=[outcome("Home", 140), outcome("Draw", 260), outcome("Away", 170)]),
    ])
    assert best_moneylines(g)["Draw"] == (260, "B")


def test_moneyline_empty_when_no_books():
    assert best_moneylines(game("Home", "Away")) == {}


def test_spread_uses_the_most_common_number_not_the_juiciest_price():
    # Three books use -3; one outlier offers -3.5 at a much better price.
    g = game("Home", "Away", books=[
        book("A", spreads=[outcome("Home", -110, -3), outcome("Away", -110, 3)]),
        book("B", spreads=[outcome("Home", -105, -3), outcome("Away", -115, 3)]),
        book("C", spreads=[outcome("Home", -112, -3), outcome("Away", -108, 3)]),
        book("Outlier", spreads=[outcome("Home", 150, -3.5), outcome("Away", -190, 3.5)]),
    ])
    best = best_spreads(g)
    assert best["Home"] == (-3, -105, "B")
    assert best["Away"] == (3, -108, "C")


def test_spread_tie_goes_to_the_number_closest_to_zero():
    g = game("Home", "Away", books=[
        book("A", spreads=[outcome("Home", -110, -3)]),
        book("B", spreads=[outcome("Home", -110, -3.5)]),
    ])
    assert best_spreads(g)["Home"][0] == -3


def test_totals_use_the_most_common_line():
    g = game("Home", "Away", books=[
        book("MyBookie", totals=[outcome("Over", -118, 2.5), outcome("Under", -112, 2.5)]),
        book("Bovada", totals=[outcome("Over", -112, 2.5), outcome("Under", -108, 2.5)]),
        book("BetRivers", totals=[outcome("Over", -114, 2.5), outcome("Under", -112, 2.5)]),
        book("OddOne", totals=[outcome("Over", 105, 3.0), outcome("Under", -125, 3.0)]),
    ])
    # Best Over at 2.5 is -112 (Bovada); best Under at 2.5 is -108 (Bovada).
    assert best_totals(g) == (2.5, -112, "Bovada", -108, "Bovada")


def test_totals_can_pick_different_books_for_over_and_under():
    g = game("Home", "Away", books=[
        book("A", totals=[outcome("Over", -105, 2.5), outcome("Under", -125, 2.5)]),
        book("B", totals=[outcome("Over", -125, 2.5), outcome("Under", -105, 2.5)]),
    ])
    assert best_totals(g) == (2.5, -105, "A", -105, "B")


def test_totals_none_when_not_offered():
    assert best_totals(game("Home", "Away")) is None
    only_h2h = game("Home", "Away", books=[book("A", h2h=[outcome("Home", -110)])])
    assert best_totals(only_h2h) is None


def test_totals_none_when_over_and_under_never_share_a_line():
    g = game("Home", "Away", books=[
        book("A", totals=[outcome("Over", -110, 2.5)]),
        book("B", totals=[outcome("Under", -110, 3.0)]),
    ])
    assert best_totals(g) is None
