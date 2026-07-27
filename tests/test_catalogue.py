from datetime import date

import pytest

from wingspan import catalogue, repository
from wingspan.goals import GREEN_POINTS, available_places, score_round
from wingspan.model import Expansion, Game, GoalSide, RoundResult

from .conftest import CARD_ANATOMIST, GOAL_FOREST, build_score


def test_catalogues_load_and_are_non_trivial():
    tiles = catalogue.goal_tiles()
    cards = catalogue.bonus_cards()
    assert len(tiles) > 50
    assert len(cards) > 50


def test_every_catalogue_expansion_parses_to_the_enum():
    """A typo in the generated JSON would silently fall back to Base Game."""
    for item in (*catalogue.goal_tiles(), *catalogue.bonus_cards()):
        assert isinstance(item.expansion, Expansion)

    covered = {t.expansion for t in catalogue.goal_tiles()}
    assert covered == set(Expansion)


def test_catalogue_ids_are_unique():
    tile_ids = [t.id for t in catalogue.goal_tiles()]
    card_ids = [c.id for c in catalogue.bonus_cards()]
    assert len(tile_ids) == len(set(tile_ids))
    assert len(card_ids) == len(set(card_ids))


def test_lookup_by_id_and_name():
    assert catalogue.goal_tile(GOAL_FOREST).name == "Birds in forest"
    assert catalogue.goal_tile_name(GOAL_FOREST) == "Birds in forest"
    assert catalogue.bonus_card(CARD_ANATOMIST).name == "Anatomist"
    assert catalogue.goal_tile(None) is None
    assert catalogue.goal_tile_name("nope") == "nope"


def test_filtering_by_expansion_keeps_base_and_the_custom_entry():
    tiles = catalogue.goal_tiles_for([Expansion.OCEANIA])
    expansions = {t.expansion for t in tiles}
    assert expansions <= {Expansion.BASE, Expansion.OCEANIA}
    assert Expansion.ASIA not in expansions
    assert any(t.id == catalogue.CUSTOM_GOAL_ID for t in tiles)

    cards = catalogue.bonus_cards_for([Expansion.ASIA])
    assert {c.expansion for c in cards} <= {Expansion.BASE, Expansion.ASIA}
    assert any(c.id == catalogue.CUSTOM_BONUS_ID for c in cards)


def test_goal_families_are_from_a_known_set():
    families = {t.family for t in catalogue.goal_tiles()}
    assert families <= {"habitat", "eggs", "nests", "birds", "cards", "food", "nectar", "other"}


def test_bonus_scoring_types_are_from_a_known_set():
    assert {c.scoring_type for c in catalogue.bonus_cards()} <= {"tiered", "per_item"}


def test_catalogue_markup_is_fully_rendered():
    """No [token] or HTML should survive into the app-facing text."""
    for tile in catalogue.goal_tiles():
        assert "[" not in tile.green_description
        assert "<" not in tile.green_description
    for card in catalogue.bonus_cards():
        assert "[" not in card.vp_text
        assert "<" not in card.description


# --------------------------------------------------------------- tile-driven scoring


def test_tile_calculate_score_matches_the_board():
    tile = catalogue.goal_tile(GOAL_FOREST)
    awarded = tile.calculate_score({"a": 1, "b": 2, "c": 3}, 3, round_no=2)
    assert awarded == {"a": 5, "b": 2, "c": 1}


def test_tile_calculate_score_blue_side_uses_counts():
    tile = catalogue.goal_tile(GOAL_FOREST)
    awarded = tile.calculate_score(
        None, 2, round_no=1, side=GoalSide.BLUE, counts={"a": 4, "b": 0}
    )
    assert awarded == {"a": 4, "b": 0}


def test_two_player_game_has_no_third_place():
    assert available_places(2) == 2
    assert available_places(5) == 3
    assert available_places(None) == 3

    # Both players tie for first in round 2: the pot is 1st + 2nd only.
    awarded = score_round(round_no=2, side=GoalSide.GREEN, placements={"a": 1, "b": 1}, player_count=2)
    assert awarded == {"a": 3, "b": 3}  # (5 + 2) // 2


def test_player_with_none_of_the_item_does_not_place():
    """Official rule: you need at least one of the goal item to place at all."""
    awarded = score_round(
        round_no=4, side=GoalSide.GREEN, placements={"a": 1, "b": None, "c": 2}, player_count=3
    )
    assert awarded["b"] == 0
    # b not placing must not push c down a slot.
    assert awarded["a"] == GREEN_POINTS[4][0]
    assert awarded["c"] == GREEN_POINTS[4][1]


def test_unknown_scoring_type_is_rejected():
    with pytest.raises(ValueError):
        score_round(round_no=1, side=GoalSide.GREEN, placements={"a": 1}, scoring_type="mystery")


# ------------------------------------------------------------------------ bonus cards


def test_bonus_total_is_derived_from_the_individual_cards(players):
    ant, _ = players
    game = Game.new(date(2025, 7, 1))
    game.scores = [build_score(ant.id, birds=10, bonus={"b1000": 7, "b1004": 5})]
    game.recompute()

    assert game.scores[0].get("bonus_cards") == 12
    assert game.scores[0].total == 22


def test_typed_bonus_total_is_kept_when_no_cards_were_recorded(players):
    """Not every game gets card-level detail; a lump sum still works."""
    ant, _ = players
    game = Game.new(date(2025, 7, 1))
    game.scores = [build_score(ant.id, birds=10, bonus_cards=9)]
    game.recompute()

    assert game.scores[0].get("bonus_cards") == 9
    assert game.scores[0].total == 19


def test_bonus_cards_survive_the_round_trip(conn, sample_game):
    repository.save_game(conn, sample_game)
    loaded = repository.load_game(conn, sample_game.id)

    polly = loaded.scores[1]
    assert sorted(polly.bonus_card_ids) == ["b1000", "b1004"]
    assert polly.get("bonus_cards") == 11
    assert {b.bonus_card_id: b.points for b in polly.bonus_card_scores} == {
        "b1000": 7,
        "b1004": 4,
    }


def test_editing_bonus_cards_replaces_the_old_rows(conn, sample_game):
    repository.save_game(conn, sample_game)
    sample_game.scores[1].bonus_card_scores.pop()
    repository.save_game(conn, sample_game)

    loaded = repository.load_game(conn, sample_game.id)
    assert len(loaded.scores[1].bonus_card_scores) == 1


def test_load_game_recomputes_totals_from_components(conn, sample_game):
    """Stored totals are a cache; a tampered one must not be believed."""
    repository.save_game(conn, sample_game)
    conn.execute("UPDATE game_players SET total = 9999, bonus_cards = 9999")

    loaded = repository.load_game(conn, sample_game.id)
    assert loaded.scores[0].total != 9999
    assert loaded.scores[0].get("bonus_cards") == 7
    assert loaded.scores[0].total == loaded.category_total(loaded.scores[0]) + loaded.scores[0].goal_points


def test_goal_points_use_the_games_player_count(conn, players):
    """A two-player tie must not be scored as if a third place existed."""
    ant, polly = players
    game = Game.new(date(2025, 7, 2))
    game.scores = [build_score(ant.id, seat=0), build_score(polly.id, seat=1)]
    game.round_results = {
        2: {ant.id: RoundResult(placement=1), polly.id: RoundResult(placement=1)}
    }
    repository.save_game(conn, game)

    loaded = repository.load_game(conn, game.id)
    assert [s.goal_points for s in loaded.scores] == [3, 3]
