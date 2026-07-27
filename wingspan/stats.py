"""Aggregations over the score history.

Pure pandas in, pandas out -- no Streamlit and no SQL, so every number on the
Insights page can be checked in a unit test.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wingspan.model import CATEGORIES, CATEGORY_KEYS, GOAL_ICON, GOAL_KEY, GOAL_LABEL

#: Category key -> display label, including the derived goal points column.
CONTRIBUTION_LABELS: dict[str, str] = {
    **{c.key: c.label for c in CATEGORIES},
    GOAL_KEY: GOAL_LABEL,
}
CONTRIBUTION_ICONS: dict[str, str] = {
    **{c.key: c.icon for c in CATEGORIES},
    GOAL_KEY: GOAL_ICON,
}
CONTRIBUTION_KEYS: tuple[str, ...] = (*CATEGORY_KEYS, GOAL_KEY)


def filter_scores(
    frame: pd.DataFrame,
    *,
    start=None,
    end=None,
    players: list[str] | None = None,
    expansions: list[str] | None = None,
    min_games: int = 0,
) -> pd.DataFrame:
    """Apply the Insights filter bar.

    Player filtering keeps whole games rather than lone rows: dropping one
    player's row from a game would silently change who "won" it.
    """
    if frame.empty:
        return frame

    result = frame
    if start is not None:
        result = result[result["played_on"] >= pd.Timestamp(start)]
    if end is not None:
        result = result[result["played_on"] <= pd.Timestamp(end)]

    if expansions:
        wanted = set(expansions)
        keep = result["expansions"].fillna("").map(
            lambda raw: bool(wanted & {e for e in str(raw).split(",") if e})
        )
        result = result[keep]

    if players:
        games = result.loc[result["player"].isin(players), "game_id"].unique()
        result = result[result["game_id"].isin(games)]

    if min_games > 0 and not result.empty:
        counts = result.groupby("player")["game_id"].nunique()
        frequent = counts[counts >= min_games].index
        result = result[result["player"].isin(frequent)]

    return result


def player_colors(frame: pd.DataFrame) -> dict[str, str]:
    """Player name -> their chosen hex colour, for the chart scales."""
    if frame.empty:
        return {}
    pairs = frame[["player", "color"]].drop_duplicates(subset=["player"])
    return dict(zip(pairs["player"], pairs["color"], strict=False))


def leaderboard(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per player: games, wins, win rate and score spread."""
    if frame.empty:
        return pd.DataFrame(
            columns=["player", "games", "wins", "win_rate", "avg_score", "best", "worst"]
        )

    grouped = frame.groupby("player", as_index=False).agg(
        games=("game_id", "nunique"),
        wins=("won", "sum"),
        avg_score=("total", "mean"),
        best=("total", "max"),
        worst=("total", "min"),
    )
    grouped["wins"] = grouped["wins"].astype(int)
    grouped["win_rate"] = grouped["wins"] / grouped["games"]
    grouped["avg_score"] = grouped["avg_score"].round(1)
    return grouped.sort_values(["wins", "avg_score"], ascending=False).reset_index(drop=True)


def score_over_time(frame: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Every game's total per player, plus a trailing mean of their last N."""
    if frame.empty:
        return frame

    result = frame.sort_values("played_on").copy()
    result["rolling_mean"] = (
        result.groupby("player")["total"]
        .transform(lambda s: s.rolling(window, min_periods=1).mean())
        .round(1)
    )
    return result


def head_to_head(frame: pd.DataFrame) -> pd.DataFrame:
    """Win rate for every ordered pair of players who have met.

    Counts a shared game as a win for the player with the higher total, so a
    tie counts for neither side.
    """
    if frame.empty:
        return pd.DataFrame(columns=["player", "opponent", "games", "wins", "win_rate"])

    pairs = frame.merge(frame, on="game_id", suffixes=("", "_opp"))
    pairs = pairs[pairs["player"] != pairs["player_opp"]]
    if pairs.empty:
        return pd.DataFrame(columns=["player", "opponent", "games", "wins", "win_rate"])

    pairs["beat"] = pairs["total"] > pairs["total_opp"]
    result = pairs.groupby(["player", "player_opp"], as_index=False).agg(
        games=("game_id", "nunique"), wins=("beat", "sum")
    )
    result = result.rename(columns={"player_opp": "opponent"})
    result["wins"] = result["wins"].astype(int)
    result["win_rate"] = result["wins"] / result["games"]
    return result


def category_contribution(frame: pd.DataFrame, normalize: bool = False) -> pd.DataFrame:
    """Average points per category per player, long format for a stacked bar."""
    if frame.empty:
        return pd.DataFrame(columns=["player", "category", "label", "points", "share"])

    present = [k for k in CONTRIBUTION_KEYS if k in frame.columns]
    averages = frame.groupby("player", as_index=False)[present].mean()
    long = averages.melt(id_vars="player", var_name="category", value_name="points")
    long["label"] = long["category"].map(CONTRIBUTION_LABELS)
    long["points"] = long["points"].round(1)

    totals = long.groupby("player")["points"].transform("sum")
    long["share"] = (long["points"] / totals.replace(0, pd.NA)).fillna(0.0)
    if normalize:
        long["points"] = (long["share"] * 100).round(1)

    # Drop categories nobody scored in -- an all-zero nectar band is noise.
    scored = long.groupby("category")["points"].transform("sum") > 0
    return long[scored].reset_index(drop=True)


def category_distribution(frame: pd.DataFrame) -> pd.DataFrame:
    """Every game's per-category score, long format for a box or strip plot."""
    if frame.empty:
        return pd.DataFrame(columns=["player", "game_id", "category", "label", "points"])

    present = [k for k in CONTRIBUTION_KEYS if k in frame.columns]
    long = frame.melt(
        id_vars=["player", "game_id", "color"],
        value_vars=present,
        var_name="category",
        value_name="points",
    )
    long["label"] = long["category"].map(CONTRIBUTION_LABELS)
    scored = long.groupby("category")["points"].transform("sum") > 0
    return long[scored].reset_index(drop=True)


def longest_win_streak(frame: pd.DataFrame) -> pd.DataFrame:
    """Longest run of consecutive wins per player, in date order."""
    if frame.empty:
        return pd.DataFrame(columns=["player", "streak"])

    rows = []
    for player, block in frame.sort_values("played_on").groupby("player"):
        best = running = 0
        for won in block["won"]:
            running = running + 1 if won else 0
            best = max(best, running)
        rows.append({"player": player, "streak": best})
    return pd.DataFrame(rows).sort_values("streak", ascending=False).reset_index(drop=True)


@dataclass
class PersonalBest:
    label: str
    icon: str
    value: int
    player: str


def personal_bests(frame: pd.DataFrame) -> list[PersonalBest]:
    """The record in each scoring category, and who holds it."""
    if frame.empty:
        return []

    bests: list[PersonalBest] = [
        PersonalBest(
            "Highest total",
            "🏅",
            int(frame["total"].max()),
            frame.loc[frame["total"].idxmax(), "player"],
        )
    ]
    for key in CONTRIBUTION_KEYS:
        if key not in frame.columns or frame[key].max() <= 0:
            continue
        bests.append(
            PersonalBest(
                CONTRIBUTION_LABELS[key],
                CONTRIBUTION_ICONS[key],
                int(frame[key].max()),
                frame.loc[frame[key].idxmax(), "player"],
            )
        )
    return bests


# ------------------------------------------------------------------------ bonus cards


def bonus_card_summary(frame: pd.DataFrame, min_uses: int = 1) -> pd.DataFrame:
    """Per bonus card: how often it was kept, what it paid, and how it went.

    `avg_game_total` and `win_rate` describe the games in which the card was
    held -- the card is not the only reason those games were won, but a card
    that keeps showing up in wins is worth noticing.
    """
    if frame.empty:
        return pd.DataFrame(
            columns=["card", "uses", "avg_points", "total_points", "avg_game_total", "win_rate"]
        )

    result = frame.groupby("card", as_index=False).agg(
        uses=("game_id", "count"),
        avg_points=("points", "mean"),
        total_points=("points", "sum"),
        avg_game_total=("game_total", "mean"),
        win_rate=("won", "mean"),
    )
    result["avg_points"] = result["avg_points"].round(1)
    result["avg_game_total"] = result["avg_game_total"].round(1)
    result = result[result["uses"] >= min_uses]
    return result.sort_values(["avg_points", "uses"], ascending=False).reset_index(drop=True)


def bonus_card_by_player(frame: pd.DataFrame, min_uses: int = 1) -> pd.DataFrame:
    """Which cards each player does best with."""
    if frame.empty:
        return pd.DataFrame(columns=["player", "card", "uses", "avg_points", "color"])

    result = frame.groupby(["player", "card"], as_index=False).agg(
        uses=("game_id", "count"),
        avg_points=("points", "mean"),
        color=("color", "first"),
    )
    result["avg_points"] = result["avg_points"].round(1)
    result = result[result["uses"] >= min_uses]
    return result.sort_values("avg_points", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------------- goal tiles


def goal_tile_summary(frame: pd.DataFrame, min_plays: int = 1) -> pd.DataFrame:
    """Per goal tile: how often it came up, what it paid, how often it was won."""
    if frame.empty:
        return pd.DataFrame(
            columns=["goal_name", "goal_family", "plays", "avg_points", "first_place_rate"]
        )

    scored = frame.dropna(subset=["goal_name"])
    if scored.empty:
        return pd.DataFrame(
            columns=["goal_name", "goal_family", "plays", "avg_points", "first_place_rate"]
        )

    result = scored.groupby(["goal_name", "goal_family"], as_index=False).agg(
        plays=("game_id", "count"),
        avg_points=("points", "mean"),
        first_place_rate=("placed_first", "mean"),
    )
    result["avg_points"] = result["avg_points"].round(1)
    result = result[result["plays"] >= min_plays]
    return result.sort_values("avg_points", ascending=False).reset_index(drop=True)


def goal_tile_by_player(frame: pd.DataFrame, min_plays: int = 1) -> pd.DataFrame:
    """How each player performs on each tile -- the "which goals do I lose" view."""
    if frame.empty:
        return pd.DataFrame(columns=["player", "goal_name", "plays", "avg_points", "color"])

    scored = frame.dropna(subset=["goal_name"])
    if scored.empty:
        return pd.DataFrame(columns=["player", "goal_name", "plays", "avg_points", "color"])

    result = scored.groupby(["player", "goal_name"], as_index=False).agg(
        plays=("game_id", "count"),
        avg_points=("points", "mean"),
        first_place_rate=("placed_first", "mean"),
        color=("color", "first"),
    )
    result["avg_points"] = result["avg_points"].round(1)
    result = result[result["plays"] >= min_plays]
    return result.sort_values("avg_points", ascending=False).reset_index(drop=True)


def goal_family_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Roll tiles up into families (habitat, eggs, nests, ...) per player."""
    if frame.empty:
        return pd.DataFrame(columns=["player", "goal_family", "plays", "avg_points", "color"])

    scored = frame.dropna(subset=["goal_family"])
    if scored.empty:
        return pd.DataFrame(columns=["player", "goal_family", "plays", "avg_points", "color"])

    result = scored.groupby(["player", "goal_family"], as_index=False).agg(
        plays=("game_id", "count"),
        avg_points=("points", "mean"),
        first_place_rate=("placed_first", "mean"),
        color=("color", "first"),
    )
    result["avg_points"] = result["avg_points"].round(1)
    return result.sort_values("avg_points", ascending=False).reset_index(drop=True)
