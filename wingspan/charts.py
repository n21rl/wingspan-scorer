"""Altair chart specs.

Pure builders: a DataFrame goes in, an `alt.Chart` comes out. No Streamlit, so
the specs can be built and inspected in tests.

Design rules applied throughout:

* Player series are coloured by the hex each player picked, because that colour
  is their identity at the table. Colour follows the player, never their rank,
  so filtering the field never repaints the survivors.
* Category series use a fixed, CVD-validated eight-hue order, assigned by slot
  and never cycled.
* One axis per chart -- a second measure gets its own chart.
* Every chart with two or more series carries a legend; charts are sized and
  laid out to stay readable on a phone.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

from wingspan.stats import CONTRIBUTION_KEYS, CONTRIBUTION_LABELS

#: Height that keeps a chart readable on a phone without dominating the screen.
CHART_HEIGHT = 280

#: CVD-validated categorical order. Assigned by slot, never cycled.
CATEGORY_PALETTE: tuple[str, ...] = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
)

#: Single-hue ramp for magnitude (head-to-head, goal heatmaps).
SEQUENTIAL_SCHEME = "blues"

FALLBACK_PLAYER_COLOR = "#2a78d6"

_LEGEND = alt.Legend(orient="top", direction="horizontal", title=None, columns=3)


def _band_axis(title: str | None = None) -> alt.Axis:
    """Axis for the categorical side of a horizontal bar chart.

    Vega thins band labels when it thinks they collide, which on a narrow
    phone silently leaves bars identified by colour alone. Every bar keeps its
    label; long goal and card names are truncated instead of dropped.
    """
    return alt.Axis(title=title, labelOverlap=False, labelLimit=170)


def _player_scale(colors: dict[str, str]) -> alt.Scale:
    """Map each player name to the colour they chose."""
    names = sorted(colors)
    return alt.Scale(
        domain=names,
        range=[colors.get(name) or FALLBACK_PLAYER_COLOR for name in names],
    )


def _category_scale(labels: list[str]) -> alt.Scale:
    """Assign palette slots in the canonical category order, never cycled."""
    ordered = [
        CONTRIBUTION_LABELS[key]
        for key in CONTRIBUTION_KEYS
        if CONTRIBUTION_LABELS[key] in labels
    ]
    return alt.Scale(domain=ordered, range=list(CATEGORY_PALETTE[: len(ordered)]))


def _base(frame: pd.DataFrame, title: str = "") -> alt.Chart:
    return alt.Chart(frame, height=CHART_HEIGHT, title=title)


def _empty(message: str) -> alt.Chart:
    """A placeholder so a thin slice of history renders as words, not an error."""
    return (
        alt.Chart(pd.DataFrame({"message": [message]}))
        .mark_text(size=13, color="#898781")
        .encode(text="message:N")
        .properties(height=80)
    )


# ------------------------------------------------------------------- score over time


def score_over_time(frame: pd.DataFrame, colors: dict[str, str]) -> alt.Chart:
    """Every game's total, with a trailing mean so the trend is visible."""
    if frame.empty:
        return _empty("No games in this range yet.")

    scale = _player_scale(colors)
    hover = alt.selection_point(on="mouseover", nearest=True, empty=False, fields=["game_id"])

    points = (
        _base(frame)
        .mark_circle(size=70, opacity=0.85, stroke="white", strokeWidth=1)
        .encode(
            x=alt.X("played_on:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0)),
            y=alt.Y("total:Q", title="Final score", scale=alt.Scale(zero=False)),
            color=alt.Color("player:N", scale=scale, legend=_LEGEND),
            opacity=alt.condition(hover, alt.value(1.0), alt.value(0.75)),
            tooltip=[
                alt.Tooltip("player:N", title="Player"),
                alt.Tooltip("played_on:T", title="Played", format="%d %b %Y"),
                alt.Tooltip("total:Q", title="Total"),
                alt.Tooltip("rank:Q", title="Place"),
            ],
        )
        .add_params(hover)
    )

    trend = (
        _base(frame)
        .mark_line(size=2, opacity=0.9, interpolate="monotone")
        .encode(
            x=alt.X("played_on:T", title=None),
            y=alt.Y("rolling_mean:Q", title="Final score"),
            color=alt.Color("player:N", scale=scale, legend=_LEGEND),
        )
    )

    return (trend + points).resolve_scale(color="shared")


# ---------------------------------------------------------------------- who is winning


def win_rate(frame: pd.DataFrame, colors: dict[str, str]) -> alt.Chart:
    """Win rate per player, with the win count as a direct label."""
    if frame.empty:
        return _empty("No games in this range yet.")

    bars = (
        _base(frame)
        .mark_bar(cornerRadiusEnd=4, size=22)
        .encode(
            y=alt.Y("player:N", sort="-x", axis=_band_axis()),
            x=alt.X(
                "win_rate:Q",
                title="Win rate",
                axis=alt.Axis(format="%"),
                scale=alt.Scale(domain=[0, 1]),
            ),
            color=alt.Color("player:N", scale=_player_scale(colors), legend=None),
            tooltip=[
                alt.Tooltip("player:N", title="Player"),
                alt.Tooltip("games:Q", title="Games"),
                alt.Tooltip("wins:Q", title="Wins"),
                alt.Tooltip("win_rate:Q", title="Win rate", format=".0%"),
                alt.Tooltip("avg_score:Q", title="Average"),
            ],
        )
    )
    # Direct labels: one series, so no legend box -- the axis names each bar.
    labels = bars.mark_text(align="left", dx=6, fontSize=12, color="#52514e").encode(
        text=alt.Text("wins:Q", format=".0f"), color=alt.value("#52514e")
    )
    # Room on the right so the direct label is not clipped by the plot edge.
    return (bars + labels).properties(padding={"right": 30})


def head_to_head(frame: pd.DataFrame) -> alt.Chart:
    """Who beats whom, as a magnitude heatmap on a single hue."""
    if frame.empty:
        return _empty("Head-to-head needs at least one shared game.")

    cells = (
        _base(frame)
        .mark_rect(stroke="white", strokeWidth=2)
        .encode(
            x=alt.X("opponent:N", title="…against", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("player:N", title="Win rate for…"),
            color=alt.Color(
                "win_rate:Q",
                title="Win rate",
                scale=alt.Scale(scheme=SEQUENTIAL_SCHEME, domain=[0, 1]),
                legend=alt.Legend(orient="top", format="%", title=None),
            ),
            tooltip=[
                alt.Tooltip("player:N", title="Player"),
                alt.Tooltip("opponent:N", title="Opponent"),
                alt.Tooltip("games:Q", title="Games together"),
                alt.Tooltip("wins:Q", title="Wins"),
                alt.Tooltip("win_rate:Q", title="Win rate", format=".0%"),
            ],
        )
    )
    # Every cell labelled: the sequential ramp carries magnitude, the number
    # carries the value, so the chart never depends on colour alone.
    text = cells.mark_text(fontSize=11).encode(
        text=alt.Text("win_rate:Q", format=".0%"),
        color=alt.condition(
            alt.datum.win_rate > 0.5, alt.value("white"), alt.value("#0b0b0b")
        ),
    )
    return cells + text


# ------------------------------------------------------------- where points come from


def category_contribution(frame: pd.DataFrame, normalize: bool = False) -> alt.Chart:
    """Average points per category per player, stacked."""
    if frame.empty:
        return _empty("No scores in this range yet.")

    labels = list(frame["label"].unique())
    axis_title = "Share of final score" if normalize else "Average points"
    # Normalised values arrive as 0-100, so label them with a literal % rather
    # than Vega's percent format, which would multiply by 100 again.
    axis = alt.Axis(labelExpr="datum.value + '%'") if normalize else alt.Axis()

    return (
        _base(frame)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            y=alt.Y("player:N", title=None),
            x=alt.X("points:Q", title=axis_title, stack="zero", axis=axis),
            color=alt.Color("label:N", scale=_category_scale(labels), legend=_LEGEND),
            # 2px of surface between stacked segments keeps adjacent hues apart.
            stroke=alt.value("white"),
            strokeWidth=alt.value(2),
            tooltip=[
                alt.Tooltip("player:N", title="Player"),
                alt.Tooltip("label:N", title="Category"),
                alt.Tooltip("points:Q", title=axis_title),
                alt.Tooltip("share:Q", title="Share", format=".0%"),
            ],
        )
    )


def category_distribution(frame: pd.DataFrame, colors: dict[str, str]) -> alt.Chart:
    """Per-category spread across games -- where a player is inconsistent."""
    if frame.empty:
        return _empty("No scores in this range yet.")

    return (
        _base(frame)
        .mark_boxplot(size=14, outliers={"size": 20})
        .encode(
            x=alt.X("points:Q", title="Points in a game"),
            y=alt.Y("label:N", axis=_band_axis()),
            color=alt.Color("player:N", scale=_player_scale(colors), legend=_LEGEND),
            tooltip=[
                alt.Tooltip("player:N", title="Player"),
                alt.Tooltip("label:N", title="Category"),
                alt.Tooltip("points:Q", title="Points"),
            ],
        )
        .properties(height=max(CHART_HEIGHT, 34 * frame["label"].nunique()))
    )


# ------------------------------------------------------------------------ bonus cards


def bonus_card_average(frame: pd.DataFrame, top_n: int = 15) -> alt.Chart:
    """Average points scored by each bonus card."""
    if frame.empty:
        return _empty("No bonus cards recorded yet.")

    top = frame.head(top_n)
    bars = (
        _base(top)
        .mark_bar(cornerRadiusEnd=4, size=18, color=CATEGORY_PALETTE[0])
        .encode(
            y=alt.Y("card:N", sort="-x", axis=_band_axis()),
            x=alt.X("avg_points:Q", title="Average points when held"),
            tooltip=[
                alt.Tooltip("card:N", title="Card"),
                alt.Tooltip("uses:Q", title="Times held"),
                alt.Tooltip("avg_points:Q", title="Average points"),
                alt.Tooltip("total_points:Q", title="Points all-time"),
                alt.Tooltip("win_rate:Q", title="Win rate", format=".0%"),
            ],
        )
        .properties(height=max(CHART_HEIGHT, 26 * len(top)))
    )
    labels = bars.mark_text(align="left", dx=6, fontSize=11, color="#52514e").encode(
        text=alt.Text("avg_points:Q", format=".1f")
    )
    return (bars + labels).properties(padding={"right": 30})


def bonus_card_usage(frame: pd.DataFrame, top_n: int = 15) -> alt.Chart:
    """How often each card gets kept."""
    if frame.empty:
        return _empty("No bonus cards recorded yet.")

    top = frame.sort_values("uses", ascending=False).head(top_n)
    return (
        _base(top)
        .mark_bar(cornerRadiusEnd=4, size=18, color=CATEGORY_PALETTE[1])
        .encode(
            y=alt.Y("card:N", sort="-x", axis=_band_axis()),
            x=alt.X("uses:Q", title="Times held", axis=alt.Axis(tickMinStep=1)),
            tooltip=[
                alt.Tooltip("card:N", title="Card"),
                alt.Tooltip("uses:Q", title="Times held"),
                alt.Tooltip("avg_points:Q", title="Average points"),
            ],
        )
        .properties(height=max(CHART_HEIGHT, 26 * len(top)))
    )


def bonus_card_win_rate(frame: pd.DataFrame, top_n: int = 15) -> alt.Chart:
    """Win rate in games where each card was held."""
    if frame.empty:
        return _empty("No bonus cards recorded yet.")

    top = frame.sort_values("win_rate", ascending=False).head(top_n)
    return (
        _base(top)
        .mark_bar(cornerRadiusEnd=4, size=18, color=CATEGORY_PALETTE[2])
        .encode(
            y=alt.Y("card:N", sort="-x", axis=_band_axis()),
            x=alt.X(
                "win_rate:Q",
                title="Win rate holding this card",
                axis=alt.Axis(format="%"),
                scale=alt.Scale(domain=[0, 1]),
            ),
            tooltip=[
                alt.Tooltip("card:N", title="Card"),
                alt.Tooltip("uses:Q", title="Times held"),
                alt.Tooltip("win_rate:Q", title="Win rate", format=".0%"),
                alt.Tooltip("avg_game_total:Q", title="Average game total"),
            ],
        )
        .properties(height=max(CHART_HEIGHT, 26 * len(top)))
    )


def bonus_card_spread(frame: pd.DataFrame, top_n: int = 12) -> alt.Chart:
    """Score distribution per card -- a card can be high-average but swingy."""
    if frame.empty:
        return _empty("No bonus cards recorded yet.")

    common = frame["card"].value_counts().head(top_n).index
    subset = frame[frame["card"].isin(common)]
    return (
        _base(subset)
        .mark_point(size=60, filled=True, opacity=0.7, color=CATEGORY_PALETTE[0])
        .encode(
            y=alt.Y("card:N", axis=_band_axis()),
            x=alt.X("points:Q", title="Points scored"),
            tooltip=[
                alt.Tooltip("card:N", title="Card"),
                alt.Tooltip("player:N", title="Player"),
                alt.Tooltip("points:Q", title="Points"),
                alt.Tooltip("played_on:T", title="Played", format="%d %b %Y"),
            ],
        )
        .properties(height=max(CHART_HEIGHT, 26 * len(common)))
    )


# ------------------------------------------------------------------------- goal tiles


def goal_tile_average(frame: pd.DataFrame, top_n: int = 15) -> alt.Chart:
    """Average points per goal tile, coloured by goal family."""
    if frame.empty:
        return _empty("No end-of-round goals recorded yet.")

    top = frame.head(top_n)
    families = sorted(top["goal_family"].unique())
    return (
        _base(top)
        .mark_bar(cornerRadiusEnd=4, size=18)
        .encode(
            y=alt.Y("goal_name:N", sort="-x", axis=_band_axis()),
            x=alt.X("avg_points:Q", title="Average points"),
            color=alt.Color(
                "goal_family:N",
                scale=alt.Scale(domain=families, range=list(CATEGORY_PALETTE[: len(families)])),
                legend=_LEGEND,
            ),
            tooltip=[
                alt.Tooltip("goal_name:N", title="Goal"),
                alt.Tooltip("goal_family:N", title="Family"),
                alt.Tooltip("plays:Q", title="Times played"),
                alt.Tooltip("avg_points:Q", title="Average points"),
                alt.Tooltip("first_place_rate:Q", title="First place rate", format=".0%"),
            ],
        )
        .properties(height=max(CHART_HEIGHT, 26 * len(top)))
    )


def goal_tile_by_player(frame: pd.DataFrame, colors: dict[str, str], top_n: int = 12) -> alt.Chart:
    """Which tiles each player does well or badly on."""
    if frame.empty:
        return _empty("No end-of-round goals recorded yet.")

    common = frame.groupby("goal_name")["plays"].sum().sort_values(ascending=False)
    subset = frame[frame["goal_name"].isin(common.head(top_n).index)]
    return (
        _base(subset)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            y=alt.Y("goal_name:N", axis=_band_axis()),
            x=alt.X("avg_points:Q", title="Average points"),
            yOffset=alt.YOffset("player:N"),
            color=alt.Color("player:N", scale=_player_scale(colors), legend=_LEGEND),
            tooltip=[
                alt.Tooltip("player:N", title="Player"),
                alt.Tooltip("goal_name:N", title="Goal"),
                alt.Tooltip("plays:Q", title="Times played"),
                alt.Tooltip("avg_points:Q", title="Average points"),
                alt.Tooltip("first_place_rate:Q", title="First place rate", format=".0%"),
            ],
        )
        .properties(height=max(CHART_HEIGHT, 30 * subset["goal_name"].nunique()))
    )


def goal_family_performance(frame: pd.DataFrame, colors: dict[str, str]) -> alt.Chart:
    """Goal performance rolled up by family."""
    if frame.empty:
        return _empty("No end-of-round goals recorded yet.")

    return (
        _base(frame)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("goal_family:N", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("avg_points:Q", title="Average points"),
            xOffset=alt.XOffset("player:N"),
            color=alt.Color("player:N", scale=_player_scale(colors), legend=_LEGEND),
            tooltip=[
                alt.Tooltip("player:N", title="Player"),
                alt.Tooltip("goal_family:N", title="Family"),
                alt.Tooltip("plays:Q", title="Rounds played"),
                alt.Tooltip("avg_points:Q", title="Average points"),
                alt.Tooltip("first_place_rate:Q", title="First place rate", format=".0%"),
            ],
        )
    )
