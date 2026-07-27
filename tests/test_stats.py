from datetime import date

import pandas as pd
import pytest

from wingspan import charts, repository, stats
from wingspan.model import Game, RoundResult

from .conftest import (
    CARD_ANATOMIST,
    CARD_BIRD_COUNTER,
    GOAL_FOREST,
    GOAL_TOTAL_BIRDS,
    build_score,
)


@pytest.fixture()
def history(conn, players):
    """Four games with a clear pattern: Ant wins three, Polly wins one."""
    ant, polly = players
    plan = [
        (date(2025, 1, 5), 90, 70),
        (date(2025, 2, 5), 95, 80),
        (date(2025, 3, 5), 60, 88),
        (date(2025, 4, 5), 99, 75),
    ]
    for index, (played, ant_birds, polly_birds) in enumerate(plan):
        game = Game.new(played)
        game.scores = [
            build_score(ant.id, seat=0, birds=ant_birds, eggs=10, bonus={CARD_ANATOMIST: 7}),
            build_score(polly.id, seat=1, birds=polly_birds, eggs=8, bonus={CARD_BIRD_COUNTER: 3}),
        ]
        game.round_goals = {1: GOAL_FOREST, 2: GOAL_TOTAL_BIRDS}
        winner, loser = (ant, polly) if ant_birds > polly_birds else (polly, ant)
        game.round_results = {
            1: {winner.id: RoundResult(placement=1), loser.id: RoundResult(placement=2)},
            2: {winner.id: RoundResult(placement=1), loser.id: RoundResult(placement=2)},
        }
        repository.save_game(conn, game)
    return conn


@pytest.fixture()
def frame(history):
    return repository.scores_dataframe(history)


def test_leaderboard_counts_wins_and_averages(frame):
    board = stats.leaderboard(frame)
    ant = board[board["player"] == "Ant"].iloc[0]

    assert ant["games"] == 4
    assert ant["wins"] == 3
    assert ant["win_rate"] == pytest.approx(0.75)
    assert board.iloc[0]["player"] == "Ant"  # sorted by wins


def test_leaderboard_of_an_empty_history_has_the_right_columns():
    board = stats.leaderboard(pd.DataFrame())
    assert list(board.columns) == [
        "player", "games", "wins", "win_rate", "avg_score", "best", "worst"
    ]


def test_score_over_time_adds_a_trailing_mean(frame):
    over_time = stats.score_over_time(frame, window=2)
    assert "rolling_mean" in over_time.columns
    ant = over_time[over_time["player"] == "Ant"].sort_values("played_on")
    # First game's mean is just itself.
    assert ant.iloc[0]["rolling_mean"] == ant.iloc[0]["total"]


def test_head_to_head_is_symmetric_in_games_and_complementary_in_wins(frame):
    matrix = stats.head_to_head(frame)
    ant_vs_polly = matrix[(matrix["player"] == "Ant") & (matrix["opponent"] == "Polly")].iloc[0]
    polly_vs_ant = matrix[(matrix["player"] == "Polly") & (matrix["opponent"] == "Ant")].iloc[0]

    assert ant_vs_polly["games"] == polly_vs_ant["games"] == 4
    assert ant_vs_polly["wins"] + polly_vs_ant["wins"] == 4


def test_head_to_head_of_a_solo_history_is_empty(conn, players):
    ant, _ = players
    game = Game.new(date(2025, 5, 1))
    game.scores = [build_score(ant.id, birds=50)]
    repository.save_game(conn, game)

    assert stats.head_to_head(repository.scores_dataframe(conn)).empty


def test_category_contribution_drops_unscored_categories(frame):
    contribution = stats.category_contribution(frame)
    assert "Nectar" not in set(contribution["label"])
    assert {"Birds", "Eggs", "Bonus cards"} <= set(contribution["label"])


def test_category_contribution_shares_sum_to_one_per_player(frame):
    contribution = stats.category_contribution(frame)
    for _, block in contribution.groupby("player"):
        assert block["share"].sum() == pytest.approx(1.0)


def test_normalised_contribution_is_a_percentage(frame):
    contribution = stats.category_contribution(frame, normalize=True)
    for _, block in contribution.groupby("player"):
        assert block["points"].sum() == pytest.approx(100.0, abs=0.5)


def test_longest_win_streak(frame):
    streaks = stats.longest_win_streak(frame)
    ant = streaks[streaks["player"] == "Ant"].iloc[0]
    assert ant["streak"] == 2  # won Jan and Feb, lost March, won April


def test_personal_bests_name_the_holder(frame):
    bests = stats.personal_bests(frame)
    top = bests[0]
    assert top.label == "Highest total"
    assert top.player == "Ant"
    assert top.value == frame["total"].max()


def test_filter_by_date_range(frame):
    filtered = stats.filter_scores(frame, start=date(2025, 3, 1))
    assert filtered["played_on"].min() >= pd.Timestamp("2025-03-01")


def test_filter_by_player_keeps_whole_games(frame):
    """Dropping the opponent's row would change who won the game."""
    filtered = stats.filter_scores(frame, players=["Ant"])
    assert set(filtered["player"]) == {"Ant", "Polly"}
    assert filtered.groupby("game_id").size().eq(2).all()


def test_filter_by_min_games(frame):
    assert stats.filter_scores(frame, min_games=99).empty
    assert not stats.filter_scores(frame, min_games=4).empty


def test_filter_by_expansion(frame):
    assert not stats.filter_scores(frame, expansions=["Base Game"]).empty
    assert stats.filter_scores(frame, expansions=["Asia"]).empty


def test_filters_on_an_empty_frame_are_safe():
    assert stats.filter_scores(pd.DataFrame(), start=date(2025, 1, 1)).empty


# ------------------------------------------------------------------------ bonus cards


def test_bonus_card_summary(history):
    summary = stats.bonus_card_summary(repository.bonus_cards_dataframe(history))
    anatomist = summary[summary["card"] == "Anatomist"].iloc[0]

    assert anatomist["uses"] == 4
    assert anatomist["avg_points"] == 7.0
    assert anatomist["win_rate"] == pytest.approx(0.75)  # Ant held it and won 3 of 4


def test_bonus_card_summary_respects_min_uses(history):
    frame = repository.bonus_cards_dataframe(history)
    assert stats.bonus_card_summary(frame, min_uses=99).empty


def test_bonus_card_by_player(history):
    by_player = stats.bonus_card_by_player(repository.bonus_cards_dataframe(history))
    assert set(by_player["player"]) == {"Ant", "Polly"}
    assert by_player.iloc[0]["avg_points"] >= by_player.iloc[-1]["avg_points"]


def test_bonus_stats_of_an_empty_history_are_safe():
    assert stats.bonus_card_summary(pd.DataFrame()).empty
    assert stats.bonus_card_by_player(pd.DataFrame()).empty


# ------------------------------------------------------------------------- goal tiles


def test_goal_tile_summary_uses_catalogue_names(history):
    summary = stats.goal_tile_summary(repository.round_results_dataframe(history))
    assert set(summary["goal_name"]) == {"Birds in forest", "Total birds"}
    assert set(summary["goal_family"]) == {"habitat", "birds"}
    assert (summary["plays"] == 8).all()  # 4 games x 2 players


def test_goal_tile_by_player_separates_winners(history):
    by_player = stats.goal_tile_by_player(repository.round_results_dataframe(history))
    ant = by_player[by_player["player"] == "Ant"]
    polly = by_player[by_player["player"] == "Polly"]
    # Ant took first place in three of four games, so scores better on goals.
    assert ant["avg_points"].mean() > polly["avg_points"].mean()


def test_goal_family_summary(history):
    families = stats.goal_family_summary(repository.round_results_dataframe(history))
    assert set(families["goal_family"]) == {"habitat", "birds"}
    assert (families["first_place_rate"] <= 1.0).all()


def test_goal_stats_of_an_empty_history_are_safe():
    assert stats.goal_tile_summary(pd.DataFrame()).empty
    assert stats.goal_family_summary(pd.DataFrame()).empty


# ----------------------------------------------------------------------------- charts


def test_every_chart_builds_a_valid_spec(history, frame):
    """Altair validates on to_dict(), so this catches malformed encodings."""
    colors = stats.player_colors(frame)
    bonus = repository.bonus_cards_dataframe(history)
    rounds = repository.round_results_dataframe(history)

    specs = [
        charts.score_over_time(stats.score_over_time(frame), colors),
        charts.win_rate(stats.leaderboard(frame), colors),
        charts.head_to_head(stats.head_to_head(frame)),
        charts.category_contribution(stats.category_contribution(frame)),
        charts.category_contribution(stats.category_contribution(frame, normalize=True), True),
        charts.category_distribution(stats.category_distribution(frame), colors),
        charts.bonus_card_average(stats.bonus_card_summary(bonus)),
        charts.bonus_card_usage(stats.bonus_card_summary(bonus)),
        charts.bonus_card_win_rate(stats.bonus_card_summary(bonus)),
        charts.bonus_card_spread(bonus),
        charts.goal_tile_average(stats.goal_tile_summary(rounds)),
        charts.goal_tile_by_player(stats.goal_tile_by_player(rounds), colors),
        charts.goal_family_performance(stats.goal_family_summary(rounds), colors),
    ]
    for spec in specs:
        assert spec.to_dict()["$schema"]


def test_charts_render_a_message_instead_of_failing_when_empty():
    empty = pd.DataFrame()
    for spec in (
        charts.score_over_time(empty, {}),
        charts.win_rate(empty, {}),
        charts.head_to_head(empty),
        charts.category_contribution(empty),
        charts.category_distribution(empty, {}),
        charts.bonus_card_average(empty),
        charts.goal_tile_average(empty),
    ):
        assert spec.to_dict()["$schema"]


def test_player_colors_come_from_the_player_record(frame):
    colors = stats.player_colors(frame)
    assert colors == {"Ant": "#c10000", "Polly": "#ffc800"}


def test_category_palette_is_assigned_by_slot_not_cycled():
    """A missing category must not shift the others onto different hues."""
    from wingspan.charts import _category_scale

    full = _category_scale(["Birds", "Bonus cards", "Eggs"])
    partial = _category_scale(["Birds", "Eggs"])

    assert full.range[0] == partial.range[0]  # Birds keeps slot 1
    assert full.domain[:1] == partial.domain[:1]
