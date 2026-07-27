from datetime import date

import pytest

from wingspan.goals import GREEN_POINTS, count_points, placement_points
from wingspan.model import (
    CATEGORY_KEYS,
    Expansion,
    Game,
    GoalSide,
    PlayerScore,
    RoundResult,
    active_categories,
)


def make_score(player_id, **values):
    score = PlayerScore(player_id=player_id, values={k: 0 for k in CATEGORY_KEYS})
    for key, value in values.items():
        score.set(key, value)
    return score


def test_active_categories_gate_on_game_options():
    base = active_categories(nectar_enabled=False, duet_enabled=False)
    assert [c.key for c in base] == [
        "birds",
        "bonus_cards",
        "eggs",
        "food_on_cards",
        "tucked_cards",
    ]

    both = active_categories(nectar_enabled=True, duet_enabled=True)
    assert {"nectar", "duet_tokens"} <= {c.key for c in both}


def test_total_sums_active_categories_plus_goals():
    game = Game.new(date(2025, 5, 4))
    game.scores = [make_score("p1", birds=31, bonus_cards=7, eggs=12, food_on_cards=4, tucked_cards=3)]
    game.round_results = {1: {"p1": RoundResult(placement=1)}}
    game.recompute()

    assert game.scores[0].goal_points == 4
    assert game.scores[0].total == 31 + 7 + 12 + 4 + 3 + 4


def test_disabled_category_never_reaches_the_total():
    """A nectar score entered and then switched off must not count."""
    game = Game.new(date(2025, 5, 4))
    game.nectar_enabled = True
    game.scores = [make_score("p1", birds=10, nectar=9)]
    assert game.recompute().scores[0].total == 19

    game.nectar_enabled = False
    assert game.recompute().scores[0].total == 10


def test_manual_goal_override_survives_recompute():
    game = Game.new(date(2025, 5, 4))
    game.scores = [make_score("p1", birds=10)]
    game.round_results = {1: {"p1": RoundResult(placement=1)}}
    game.scores[0].goal_points = 99
    game.scores[0].goal_points_manual = True
    game.recompute()

    assert game.scores[0].goal_points == 99
    assert game.scores[0].total == 109


@pytest.mark.parametrize("round_no", sorted(GREEN_POINTS))
def test_uncontested_placements_match_the_printed_table(round_no):
    first, second, third = GREEN_POINTS[round_no]
    awarded = placement_points(round_no, {"a": 1, "b": 2, "c": 3})
    assert awarded == {"a": first, "b": second, "c": third}


def test_unplaced_players_score_nothing():
    assert placement_points(2, {"a": 1, "b": None}) == {"a": 5, "b": 0}


def test_two_way_tie_for_first_splits_first_and_second():
    # Round 1 pays 4/1/0, so a tie at the top is (4 + 1) // 2 = 2 each...
    awarded = placement_points(1, {"a": 1, "b": 1, "c": 2})
    assert awarded["a"] == awarded["b"] == 2
    # ...and the next player takes the third slot, not the second.
    assert awarded["c"] == 0


def test_three_way_tie_pools_every_place():
    awarded = placement_points(4, {"a": 1, "b": 1, "c": 1})
    assert awarded == {"a": 4, "b": 4, "c": 4}  # (7 + 4 + 3) // 3


def test_tie_below_first_still_splits_correctly():
    awarded = placement_points(2, {"a": 1, "b": 2, "c": 2, "d": 3})
    assert awarded["a"] == 5
    assert awarded["b"] == awarded["c"] == 1  # (2 + 1) // 2
    assert awarded["d"] == 0  # fourth slot pays nothing


def test_placements_are_read_as_a_ranking_not_literal_places():
    """Gappy input from a hurried tap must score the same as tidy input."""
    tidy = placement_points(3, {"a": 1, "b": 1, "c": 3})
    gappy = placement_points(3, {"a": 1, "b": 1, "c": 2})
    assert tidy == gappy


def test_unknown_round_is_rejected():
    with pytest.raises(ValueError):
        placement_points(5, {"a": 1})


def test_blue_side_scores_one_per_item():
    game = Game.new(date(2025, 5, 4))
    game.goal_side = GoalSide.BLUE
    game.scores = [make_score("p1", birds=10)]
    game.round_results = {
        1: {"p1": RoundResult(raw_count=3)},
        2: {"p1": RoundResult(raw_count=5)},
    }
    game.recompute()

    assert game.scores[0].goal_points == 8
    assert count_points(None) == 0
    assert count_points(-2) == 0


def test_round_points_are_cached_onto_each_result():
    game = Game.new(date(2025, 5, 4))
    game.scores = [make_score("a"), make_score("b")]
    game.round_results = {3: {"a": RoundResult(placement=1), "b": RoundResult(placement=2)}}
    game.recompute()

    assert game.round_results[3]["a"].points == 6
    assert game.round_results[3]["b"].points == 3


def test_winners_reports_ties():
    game = Game.new(date(2025, 5, 4))
    game.scores = [make_score("a", birds=50), make_score("b", birds=50), make_score("c", birds=10)]
    game.recompute()
    assert sorted(game.winners()) == ["a", "b"]


def test_winners_is_empty_without_scores():
    assert Game.new(date(2025, 5, 4)).winners() == []


def test_game_categories_follow_expansion_toggles():
    game = Game.new(date(2025, 5, 4))
    game.expansions = (Expansion.BASE, Expansion.OCEANIA)
    game.nectar_enabled = True
    assert "nectar" in {c.key for c in game.categories}
