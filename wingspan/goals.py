"""Scoring rules for end-of-round goals.

The *what* of a goal -- its name, expansion and description -- lives in the
catalogue (`wingspan.catalogue`). The *how much* lives here, because on the
green side the award is a property of the goal board rather than of the tile:
it depends on the round and on how many places exist to be won.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from wingspan.model import ROUNDS, GoalSide

if TYPE_CHECKING:  # pragma: no cover
    from wingspan.model import Game

#: Green-side award by round: (1st, 2nd, 3rd). Later rounds are worth more.
GREEN_POINTS: dict[int, tuple[int, int, int]] = {
    1: (4, 1, 0),
    2: (5, 2, 1),
    3: (6, 3, 2),
    4: (7, 4, 3),
}

#: The goal board has three places regardless of expansion.
MAX_PLACES = 3

PLACEMENT = "placement"
COUNT = "count"


def available_places(player_count: int | None) -> int:
    """How many places can actually be won.

    A two-player game has no third place, so a tie for first pools first and
    second and there is nothing left to award.
    """
    if not player_count or player_count < 1:
        return MAX_PLACES
    return max(1, min(MAX_PLACES, int(player_count)))


def placement_points(
    round_no: int,
    placements: Mapping[str, int | None],
    player_count: int | None = None,
) -> dict[str, int]:
    """Green-side points per player for one round.

    Tied players pool the awards for the places they occupy and split the pot,
    rounded down -- so two players tied for first in round 1 take (4+1)//2 = 2
    each and the next player is third, not second.

    Placements are read as a ranking rather than as literal place numbers, so
    `{a: 1, b: 1, c: 2}` behaves the same as `{a: 1, b: 1, c: 3}`.

    A player with none of the goal item does not place at all: pass None, and
    they score nothing without consuming a place.
    """
    if round_no not in GREEN_POINTS:
        raise ValueError(f"round must be one of {ROUNDS}, got {round_no!r}")

    table = GREEN_POINTS[round_no]
    places = available_places(player_count if player_count else len(placements))

    points = {pid: 0 for pid in placements}
    ranks = sorted({p for p in placements.values() if p is not None})

    slot = 0  # zero-based index into `table`
    for rank in ranks:
        tied = [pid for pid, p in placements.items() if p == rank]
        pot = sum(table[slot + i] for i in range(len(tied)) if slot + i < places)
        share = pot // len(tied)
        for pid in tied:
            points[pid] = share
        slot += len(tied)
    return points


def count_points(raw_count: int | None) -> int:
    """Blue-side points: one per qualifying item."""
    return max(0, int(raw_count or 0))


def score_round(
    *,
    round_no: int,
    side: GoalSide | None,
    placements: Mapping[str, int | None] | None = None,
    counts: Mapping[str, int | None] | None = None,
    player_count: int | None = None,
    scoring_type: str = PLACEMENT,
) -> dict[str, int]:
    """Dispatch one round of goal scoring to the right strategy.

    `scoring_type` comes from the goal tile, so an expansion tile that scores
    some novel way can be added by extending this function alone.
    """
    side = side or GoalSide.GREEN

    if side is GoalSide.BLUE or scoring_type == COUNT:
        source = counts if counts is not None else {}
        return {pid: count_points(value) for pid, value in source.items()}

    if scoring_type != PLACEMENT:
        raise ValueError(f"unknown goal scoring_type: {scoring_type!r}")

    return placement_points(round_no, placements or {}, player_count)


def round_points(round_no: int, side: GoalSide, results: Mapping[str, object]) -> dict[str, int]:
    """Points for one round from stored `RoundResult` objects."""
    if side is GoalSide.BLUE:
        return {pid: count_points(getattr(r, "raw_count", None)) for pid, r in results.items()}
    return placement_points(
        round_no,
        {pid: getattr(r, "placement", None) for pid, r in results.items()},
        len(results),
    )


def game_goal_points(game: "Game") -> dict[str, int]:
    """Total end-of-round goal points per player, caching each round's points.

    Writes `points` back onto every `RoundResult` so the per-round breakdown
    survives into storage and into the goal-performance charts.
    """
    from wingspan.catalogue import goal_tile

    totals = {pid: 0 for pid in game.player_ids}
    player_count = len(game.scores) or None

    for round_no in ROUNDS:
        results = game.round_results.get(round_no)
        if not results:
            continue

        tile = goal_tile(game.round_goals.get(round_no))
        awarded = score_round(
            round_no=round_no,
            side=game.goal_side,
            placements={pid: r.placement for pid, r in results.items()},
            counts={pid: r.raw_count for pid, r in results.items()},
            player_count=player_count,
            scoring_type=tile.scoring_type if tile else PLACEMENT,
        )
        for pid, pts in awarded.items():
            results[pid].points = pts
            if pid in totals:
                totals[pid] += pts
    return totals
