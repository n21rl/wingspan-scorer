"""Insights: what the history actually says."""

from __future__ import annotations

import streamlit as st

from views._shared import empty_state, get_connection
from wingspan import charts, repository, stats
from wingspan.model import Expansion

conn = get_connection()


def as_percent(frame, *columns):
    """Rates are stored 0-1; tables read better as whole percentages."""
    shown = frame.copy()
    for column in columns:
        if column in shown.columns:
            shown[column] = (shown[column] * 100).round(0).astype(int)
    return shown


st.title("Insights")

scores = repository.scores_dataframe(conn)
if scores.empty:
    empty_state(
        "Nothing to chart yet",
        "Record a game and the trends, win rates and score breakdowns show up here.",
        page="views/enter_scores.py",
        label="Enter a game",
    )
    st.stop()


# ------------------------------------------------------------------------- filters

with st.expander("Filters", expanded=False):
    earliest = scores["played_on"].min().date()
    latest = scores["played_on"].max().date()

    date_range = st.date_input(
        "Played between",
        value=(earliest, latest),
        min_value=earliest,
        max_value=latest,
        format="DD/MM/YYYY",
    )
    start, end = date_range if isinstance(date_range, tuple) and len(date_range) == 2 else (earliest, latest)

    chosen_players = st.multiselect("Players", sorted(scores["player"].unique()))
    chosen_expansions = st.multiselect("Expansions", [str(e) for e in Expansion])
    min_games = st.slider("Minimum games per player", 0, 20, 0)

frame = stats.filter_scores(
    scores,
    start=start,
    end=end,
    players=chosen_players or None,
    expansions=chosen_expansions or None,
    min_games=min_games,
)

if frame.empty:
    st.info("No games match those filters.")
    st.stop()

game_ids = set(frame["game_id"])
colors = stats.player_colors(frame)

bonus = repository.bonus_cards_dataframe(conn)
bonus = bonus[bonus["game_id"].isin(game_ids)] if not bonus.empty else bonus

rounds = repository.round_results_dataframe(conn)
rounds = rounds[rounds["game_id"].isin(game_ids)] if not rounds.empty else rounds


# ------------------------------------------------------------------------- headline

board = stats.leaderboard(frame)
streaks = stats.longest_win_streak(frame)
leader = board.iloc[0]

# One line rather than three stacked metrics: on a phone, st.columns stacks,
# and three metric tiles would push every chart below the fold.
st.caption(
    f"**{int(frame['game_id'].nunique())}** games · "
    f"best score **{int(frame['total'].max())}** · "
    f"most wins **{leader['player']}** ({int(leader['wins'])})"
)


tab_overview, tab_categories, tab_bonus, tab_goals = st.tabs(
    ["Overview", "Where points come from", "Bonus cards", "Goals"]
)


# ------------------------------------------------------------------------ overview

with tab_overview:
    st.subheader("Am I improving?")
    st.altair_chart(
        charts.score_over_time(stats.score_over_time(frame), colors),
        width="stretch",
    )
    st.caption("Dots are single games; the line is a trailing average of the last five.")

    st.subheader("Who wins, and how often?")
    st.altair_chart(charts.win_rate(board, colors), width="stretch")
    st.dataframe(
        as_percent(board, "win_rate").rename(
            columns={
                "player": "Player",
                "games": "Games",
                "wins": "Wins",
                "win_rate": "Win rate %",
                "avg_score": "Average",
                "best": "Best",
                "worst": "Worst",
            }
        ),
        hide_index=True,
        width="stretch",
    )

    if len(colors) > 1:
        st.subheader("Who beats whom?")
        st.altair_chart(charts.head_to_head(stats.head_to_head(frame)), width="stretch")

    if not streaks.empty and streaks["streak"].max() > 1:
        best_streak = streaks.iloc[0]
        st.caption(
            f"Longest winning streak: {best_streak['player']} — {int(best_streak['streak'])} in a row."
        )

    st.subheader("Personal bests")
    bests = stats.personal_bests(frame)
    for row in range(0, len(bests), 3):
        for column, best in zip(st.columns(3), bests[row : row + 3], strict=False):
            column.metric(f"{best.icon} {best.label}", best.value, best.player)


# ---------------------------------------------------------------------- categories

with tab_categories:
    st.subheader("Where do my points come from?")
    normalize = st.toggle("Show as a share of the final score")

    contribution = stats.category_contribution(frame, normalize=normalize)
    st.altair_chart(
        charts.category_contribution(contribution, normalize=normalize),
        width="stretch",
    )
    # Three palette slots sit under 3:1 on a light surface, so the numbers are
    # available as text rather than being carried by colour alone.
    with st.expander("Show the numbers"):
        st.dataframe(
            contribution.pivot_table(
                index="player", columns="label", values="points", aggfunc="sum"
            ).round(1),
            width="stretch",
        )

    st.subheader("Which categories am I inconsistent at?")
    st.altair_chart(
        charts.category_distribution(stats.category_distribution(frame), colors),
        width="stretch",
    )
    st.caption("Each box spans the middle half of that player's games; whiskers show the range.")


# --------------------------------------------------------------------- bonus cards

with tab_bonus:
    if bonus.empty:
        st.info(
            "No bonus cards recorded yet. Record which cards each player kept during "
            "score entry and this fills in."
        )
    else:
        min_uses = st.slider("Only cards held at least this often", 1, 10, 1)
        summary = stats.bonus_card_summary(bonus, min_uses=min_uses)

        if summary.empty:
            st.info("No cards have been held that often yet.")
        else:
            st.subheader("Average score by bonus card")
            st.altair_chart(charts.bonus_card_average(summary), width="stretch")

            st.subheader("How often each card gets kept")
            st.altair_chart(charts.bonus_card_usage(summary), width="stretch")

            st.subheader("Win rate when holding the card")
            st.altair_chart(charts.bonus_card_win_rate(summary), width="stretch")
            st.caption(
                "A card is never the only reason a game was won, but one that keeps "
                "showing up in wins is worth drafting."
            )

            st.subheader("Score spread per card")
            st.altair_chart(charts.bonus_card_spread(bonus), width="stretch")
            st.caption("A high average with a wide spread is a gamble; a tight one is reliable.")

            with st.expander("Show the numbers"):
                st.dataframe(
                    as_percent(summary, "win_rate").rename(
                        columns={
                            "card": "Card",
                            "uses": "Times held",
                            "avg_points": "Average",
                            "total_points": "All-time",
                            "avg_game_total": "Average game total",
                            "win_rate": "Win rate %",
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )


# --------------------------------------------------------------------------- goals

with tab_goals:
    if rounds.empty or rounds["goal_name"].isna().all():
        st.info(
            "No end-of-round goals recorded yet. Record each round's goal tile during "
            "score entry and this fills in."
        )
    else:
        st.subheader("Which goals pay best?")
        st.altair_chart(
            charts.goal_tile_average(stats.goal_tile_summary(rounds)), width="stretch"
        )

        st.subheader("Which goals do I keep losing?")
        st.altair_chart(
            charts.goal_tile_by_player(stats.goal_tile_by_player(rounds), colors),
            width="stretch",
        )

        st.subheader("By goal family")
        st.altair_chart(
            charts.goal_family_performance(stats.goal_family_summary(rounds), colors),
            width="stretch",
        )
        st.caption("Habitat, egg, nest and food goals grouped together.")

        with st.expander("Show the numbers"):
            st.dataframe(
                as_percent(stats.goal_tile_summary(rounds), "first_place_rate").rename(
                    columns={
                        "goal_name": "Goal",
                        "goal_family": "Family",
                        "plays": "Rounds played",
                        "avg_points": "Average points",
                        "first_place_rate": "First place %",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
