"""Reads and writes for players, games and settings."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any

import pandas as pd

from wingspan.db import purge_deleted
from wingspan.model import (
    CATEGORY_KEYS,
    ROUNDS,
    BonusCardScore,
    Expansion,
    Game,
    GoalSide,
    Player,
    PlayerScore,
    RoundResult,
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


# --------------------------------------------------------------------------- players


def _row_to_player(row: sqlite3.Row) -> Player:
    return Player(
        id=row["id"],
        name=row["name"],
        color=row["color"],
        avatar=row["avatar"],
        archived=bool(row["archived"]),
    )


def list_players(conn: sqlite3.Connection, include_archived: bool = False) -> list[Player]:
    sql = "SELECT * FROM players"
    if not include_archived:
        sql += " WHERE archived = 0"
    sql += " ORDER BY name COLLATE NOCASE"
    return [_row_to_player(r) for r in conn.execute(sql)]


def get_player(conn: sqlite3.Connection, player_id: str) -> Player | None:
    row = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    return _row_to_player(row) if row else None


def get_player_by_name(conn: sqlite3.Connection, name: str) -> Player | None:
    row = conn.execute(
        "SELECT * FROM players WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return _row_to_player(row) if row else None


def players_by_id(conn: sqlite3.Connection) -> dict[str, Player]:
    return {p.id: p for p in list_players(conn, include_archived=True)}


def save_player(conn: sqlite3.Connection, player: Player) -> Player:
    conn.execute(
        """
        INSERT INTO players (id, name, color, avatar, archived, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            color = excluded.color,
            avatar = excluded.avatar,
            archived = excluded.archived
        """,
        (player.id, player.name, player.color, player.avatar, int(player.archived), _now()),
    )
    return player


def ensure_player(conn: sqlite3.Connection, name: str, color: str = "#4c78a8") -> Player:
    """Look a player up by name, creating them if they are new."""
    existing = get_player_by_name(conn, name)
    if existing:
        return existing
    return save_player(conn, Player.new(name=name, color=color))


def player_game_count(conn: sqlite3.Connection, player_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM game_players WHERE player_id = ?", (player_id,)
    ).fetchone()
    return int(row["n"])


def game_counts_by_player(conn: sqlite3.Connection) -> dict[str, int]:
    """Every player's game count in one query, for views that need them all.

    Matches `player_game_count`'s semantics exactly -- every `game_players`
    row counts, soft-deleted games included -- so switching a call site from
    one to the other doesn't change what's on screen. Players with zero games
    are simply absent from the result rather than mapped to 0.
    """
    rows = conn.execute(
        "SELECT player_id, COUNT(*) AS n FROM game_players GROUP BY player_id"
    ).fetchall()
    return {row["player_id"]: int(row["n"]) for row in rows}


def delete_player(conn: sqlite3.Connection, player_id: str) -> bool:
    """Remove a player outright. Refuses once they appear in a game.

    Deleting would take their games' history with them, so callers should
    archive instead -- the return value says which happened.
    """
    if player_game_count(conn, player_id) > 0:
        conn.execute("UPDATE players SET archived = 1 WHERE id = ?", (player_id,))
        return False
    conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
    return True


# ----------------------------------------------------------------------------- games


def save_game(conn: sqlite3.Connection, game: Game) -> Game:
    """Insert or update a game, keyed on its id.

    The whole write is one transaction and child rows are replaced wholesale,
    so saving the same game twice leaves one game rather than two.
    """
    conn.execute("BEGIN")
    try:
        _write_game(conn, game)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return game


def save_games(conn: sqlite3.Connection, games: list[Game]) -> list[Game]:
    """Write many games in a single transaction -- all of them or none."""
    conn.execute("BEGIN")
    try:
        for game in games:
            _write_game(conn, game)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return games


def _write_game(conn: sqlite3.Connection, game: Game) -> Game:
    """Upsert one game. Caller owns the transaction."""
    game.recompute()
    conn.execute(
        """
        INSERT INTO games (id, played_on, expansions, nectar_enabled, duet_enabled,
                           goal_side, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            played_on = excluded.played_on,
            expansions = excluded.expansions,
            nectar_enabled = excluded.nectar_enabled,
            duet_enabled = excluded.duet_enabled,
            goal_side = excluded.goal_side,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (
            game.id,
            game.played_on.isoformat(),
            ",".join(str(e) for e in game.expansions),
            int(game.nectar_enabled),
            int(game.duet_enabled),
            str(game.goal_side),
            game.notes or "",
            _now(),
            _now(),
        ),
    )

    # Children are replaced wholesale so an edit that drops a player, a round
    # or a bonus card cannot leave orphaned rows behind.
    conn.execute("DELETE FROM game_players WHERE game_id = ?", (game.id,))
    conn.execute("DELETE FROM game_goals WHERE game_id = ?", (game.id,))
    conn.execute("DELETE FROM player_goal_scores WHERE game_id = ?", (game.id,))
    conn.execute("DELETE FROM player_bonus_cards WHERE game_id = ?", (game.id,))

    columns = ", ".join(CATEGORY_KEYS)
    placeholders = ", ".join("?" for _ in CATEGORY_KEYS)
    for score in game.scores:
        conn.execute(
            f"""
            INSERT INTO game_players
                (game_id, player_id, seat, {columns},
                 goal_points, goal_points_manual, total)
            VALUES (?, ?, ?, {placeholders}, ?, ?, ?)
            """,
            (
                game.id,
                score.player_id,
                score.seat,
                *[score.get(k) for k in CATEGORY_KEYS],
                score.goal_points,
                int(score.goal_points_manual),
                score.total,
            ),
        )

    for score in game.scores:
        for bonus in score.bonus_card_scores:
            conn.execute(
                """
                INSERT INTO player_bonus_cards
                    (game_id, player_id, bonus_card_id, points)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(game_id, player_id, bonus_card_id) DO UPDATE SET
                    points = excluded.points
                """,
                (game.id, score.player_id, bonus.bonus_card_id, int(bonus.points)),
            )

    for round_no, goal_tile_id in game.round_goals.items():
        conn.execute(
            "INSERT INTO game_goals (game_id, round_no, goal_tile_id) VALUES (?, ?, ?)",
            (game.id, int(round_no), goal_tile_id),
        )

    for round_no, results in game.round_results.items():
        for player_id, result in results.items():
            conn.execute(
                """
                INSERT INTO player_goal_scores
                    (game_id, round_no, player_id, placement, raw_count, points)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    game.id,
                    int(round_no),
                    player_id,
                    result.placement,
                    result.raw_count,
                    result.points,
                ),
            )
    return game


def load_game(
    conn: sqlite3.Connection, game_id: str, include_deleted: bool = False
) -> Game | None:
    sql = "SELECT * FROM games WHERE id = ?"
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    row = conn.execute(sql, (game_id,)).fetchone()
    if row is None:
        return None
    # Totals are a cache, so an edit session starts from derived values.
    return _hydrate_games(conn, [row])[0].recompute()


# SQLite's default build caps a statement at 999 bound parameters, so a
# `WHERE game_id IN (...)` for a very large batch has to be split into
# chunks rather than issued as one query.
_SQLITE_MAX_VARIABLES = 900


def _fetch_by_game_ids(
    conn: sqlite3.Connection, sql_template: str, game_ids: list[str]
) -> list[sqlite3.Row]:
    """Run `sql_template` (with a `{placeholders}` slot) once per chunk of ids."""
    rows: list[sqlite3.Row] = []
    for start in range(0, len(game_ids), _SQLITE_MAX_VARIABLES):
        chunk = game_ids[start : start + _SQLITE_MAX_VARIABLES]
        placeholders = ", ".join("?" for _ in chunk)
        rows.extend(
            conn.execute(sql_template.format(placeholders=placeholders), chunk).fetchall()
        )
    return rows


def _hydrate_games(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[Game]:
    """Attach every game's children with four queries total, not four per game.

    `load_game` routes its single row through here too, so the row->Game
    construction logic lives in one place instead of two copies drifting apart.
    """
    if not rows:
        return []

    game_ids = [row["id"] for row in rows]

    bonus_by_game: dict[str, dict[str, list[BonusCardScore]]] = {}
    for bonus_row in _fetch_by_game_ids(
        conn,
        """
        SELECT game_id, player_id, bonus_card_id, points
        FROM player_bonus_cards WHERE game_id IN ({placeholders})
        ORDER BY bonus_card_id
        """,
        game_ids,
    ):
        bonus_by_game.setdefault(bonus_row["game_id"], {}).setdefault(
            bonus_row["player_id"], []
        ).append(
            BonusCardScore(
                bonus_card_id=bonus_row["bonus_card_id"], points=bonus_row["points"]
            )
        )

    scores_by_game: dict[str, list[sqlite3.Row]] = {}
    for score_row in _fetch_by_game_ids(
        conn,
        "SELECT * FROM game_players WHERE game_id IN ({placeholders}) ORDER BY game_id, seat",
        game_ids,
    ):
        scores_by_game.setdefault(score_row["game_id"], []).append(score_row)

    goals_by_game: dict[str, list[sqlite3.Row]] = {}
    for goal_row in _fetch_by_game_ids(
        conn,
        "SELECT game_id, round_no, goal_tile_id FROM game_goals WHERE game_id IN ({placeholders})",
        game_ids,
    ):
        goals_by_game.setdefault(goal_row["game_id"], []).append(goal_row)

    results_by_game: dict[str, list[sqlite3.Row]] = {}
    for result_row in _fetch_by_game_ids(
        conn,
        "SELECT * FROM player_goal_scores WHERE game_id IN ({placeholders})",
        game_ids,
    ):
        results_by_game.setdefault(result_row["game_id"], []).append(result_row)

    return [
        _build_game(
            row,
            bonus_by_game.get(row["id"], {}),
            scores_by_game.get(row["id"], []),
            goals_by_game.get(row["id"], []),
            results_by_game.get(row["id"], []),
        )
        for row in rows
    ]


def _build_game(
    row: sqlite3.Row,
    bonus_by_player: dict[str, list[BonusCardScore]],
    score_rows: list[sqlite3.Row],
    goal_rows: list[sqlite3.Row],
    result_rows: list[sqlite3.Row],
) -> Game:
    """Assemble one Game from a game row plus its already-fetched children."""
    expansions = tuple(
        Expansion(e) for e in (row["expansions"] or "").split(",") if e
    ) or (Expansion.BASE,)

    game = Game(
        id=row["id"],
        played_on=_parse_date(row["played_on"]),
        expansions=expansions,
        nectar_enabled=bool(row["nectar_enabled"]),
        duet_enabled=bool(row["duet_enabled"]),
        goal_side=GoalSide(row["goal_side"]),
        notes=row["notes"] or "",
    )

    for score_row in score_rows:
        game.scores.append(
            PlayerScore(
                player_id=score_row["player_id"],
                seat=score_row["seat"],
                values={k: score_row[k] for k in CATEGORY_KEYS},
                goal_points=score_row["goal_points"],
                goal_points_manual=bool(score_row["goal_points_manual"]),
                bonus_card_scores=bonus_by_player.get(score_row["player_id"], []),
                total=score_row["total"],
            )
        )

    for goal_row in goal_rows:
        game.round_goals[goal_row["round_no"]] = goal_row["goal_tile_id"]

    for result_row in result_rows:
        game.round_results.setdefault(result_row["round_no"], {})[
            result_row["player_id"]
        ] = RoundResult(
            placement=result_row["placement"],
            raw_count=result_row["raw_count"],
            points=result_row["points"],
        )

    return game


def list_games(
    conn: sqlite3.Connection, limit: int | None = None, include_deleted: bool = False
) -> list[Game]:
    """Most recent first. Soft-deleted games are hidden unless asked for.

    Hydrates the whole page in a constant number of queries -- one for the
    games plus one per child table -- rather than four queries per game.
    """
    sql = "SELECT * FROM games"
    if not include_deleted:
        sql += " WHERE deleted_at IS NULL"
    sql += " ORDER BY played_on DESC, created_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    return [game.recompute() for game in _hydrate_games(conn, rows)]


def list_deleted_games(conn: sqlite3.Connection) -> list[Game]:
    """Games sitting in the soft-delete bin, most recently played first.

    A dedicated query rather than filtering `list_games(include_deleted=True)`
    against `list_games()` -- that pattern hydrates every game in the database
    twice just to find the handful that are deleted.
    """
    rows = conn.execute(
        "SELECT * FROM games WHERE deleted_at IS NOT NULL ORDER BY played_on DESC, created_at DESC"
    ).fetchall()
    return [game.recompute() for game in _hydrate_games(conn, rows)]


def count_games(conn: sqlite3.Connection, include_deleted: bool = False) -> int:
    sql = "SELECT COUNT(*) AS n FROM games"
    if not include_deleted:
        sql += " WHERE deleted_at IS NULL"
    return int(conn.execute(sql).fetchone()["n"])


def delete_game(conn: sqlite3.Connection, game_id: str) -> None:
    """Soft-delete, leaving a window in which the user can undo.

    `db.purge_deleted` clears these out for real once the window has passed.
    """
    conn.execute(
        "UPDATE games SET deleted_at = ? WHERE id = ?", (_now(), game_id)
    )


def restore_game(conn: sqlite3.Connection, game_id: str) -> bool:
    """Undo a soft delete. False if the game is already gone for good."""
    cursor = conn.execute(
        "UPDATE games SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL",
        (game_id,),
    )
    return bool(cursor.rowcount)


def purge_game(conn: sqlite3.Connection, game_id: str) -> None:
    """Delete a game for real, right now. Children cascade."""
    conn.execute("DELETE FROM games WHERE id = ?", (game_id,))


# -------------------------------------------------------------------------- settings


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, json.dumps(value)),
    )


# ------------------------------------------------------------------------ dataframes


def scores_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per player per game, with game metadata joined on.

    This is the single input to every aggregation in `wingspan.stats`.
    """
    frame = pd.read_sql_query(
        f"""
        SELECT g.id            AS game_id,
               g.played_on     AS played_on,
               g.expansions    AS expansions,
               g.nectar_enabled, g.duet_enabled, g.goal_side, g.notes,
               gp.player_id, gp.seat,
               {", ".join("gp." + k for k in CATEGORY_KEYS)},
               gp.goal_points, gp.total,
               p.name          AS player,
               p.color         AS color
        FROM games g
        JOIN game_players gp ON gp.game_id = g.id
        JOIN players p       ON p.id = gp.player_id
        WHERE g.deleted_at IS NULL
        ORDER BY g.played_on, g.id, gp.seat
        """,
        conn,
    )
    if frame.empty:
        return frame
    frame["played_on"] = pd.to_datetime(frame["played_on"])
    frame["rank"] = frame.groupby("game_id")["total"].rank(ascending=False, method="min")
    frame["won"] = frame["rank"] == 1
    frame["players_in_game"] = frame.groupby("game_id")["player_id"].transform("size")
    return frame


def round_results_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per player per round, with the goal tile and game date joined on."""
    frame = pd.read_sql_query(
        """
        SELECT r.game_id, r.round_no, r.player_id, r.placement, r.raw_count, r.points,
               rg.goal_tile_id, g.played_on, g.goal_side,
               t.name AS goal_name, t.family AS goal_family, t.expansion AS goal_expansion,
               p.name AS player, p.color AS color,
               gp.total AS game_total
        FROM player_goal_scores r
        JOIN games g          ON g.id = r.game_id
        JOIN players p        ON p.id = r.player_id
        JOIN game_players gp  ON gp.game_id = r.game_id AND gp.player_id = r.player_id
        LEFT JOIN game_goals rg
               ON rg.game_id = r.game_id AND rg.round_no = r.round_no
        LEFT JOIN goal_tiles t ON t.id = rg.goal_tile_id
        WHERE g.deleted_at IS NULL
        ORDER BY g.played_on, r.game_id, r.round_no
        """,
        conn,
    )
    if not frame.empty:
        frame["played_on"] = pd.to_datetime(frame["played_on"])
        frame["placed_first"] = frame["placement"] == 1
    return frame


def bonus_cards_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per bonus card held, with the card, player and game outcome.

    Carries the player's game total and whether they won, so "win rate when
    holding this card" is a groupby rather than a second query.
    """
    frame = pd.read_sql_query(
        """
        SELECT b.game_id, b.player_id, b.bonus_card_id, b.points,
               c.name AS card, c.expansion AS card_expansion,
               c.scoring_type, c.condition,
               g.played_on, gp.total AS game_total,
               p.name AS player, p.color AS color
        FROM player_bonus_cards b
        JOIN games g         ON g.id = b.game_id
        JOIN game_players gp ON gp.game_id = b.game_id AND gp.player_id = b.player_id
        JOIN players p       ON p.id = b.player_id
        LEFT JOIN bonus_cards c ON c.id = b.bonus_card_id
        WHERE g.deleted_at IS NULL
        ORDER BY g.played_on, b.game_id
        """,
        conn,
    )
    if frame.empty:
        return frame

    frame["played_on"] = pd.to_datetime(frame["played_on"])
    frame["card"] = frame["card"].fillna(frame["bonus_card_id"])

    winners = pd.read_sql_query(
        """
        SELECT gp.game_id, gp.player_id,
               RANK() OVER (PARTITION BY gp.game_id ORDER BY gp.total DESC) AS rank
        FROM game_players gp
        JOIN games g ON g.id = gp.game_id
        WHERE g.deleted_at IS NULL
        """,
        conn,
    )
    frame = frame.merge(winners, on=["game_id", "player_id"], how="left")
    frame["won"] = frame["rank"] == 1
    return frame


__all__ = [
    "ROUNDS",
    "bonus_cards_dataframe",
    "count_games",
    "delete_game",
    "purge_deleted",
    "purge_game",
    "restore_game",
    "delete_player",
    "ensure_player",
    "game_counts_by_player",
    "get_player",
    "get_player_by_name",
    "get_setting",
    "list_deleted_games",
    "list_games",
    "list_players",
    "load_game",
    "player_game_count",
    "players_by_id",
    "round_results_dataframe",
    "save_game",
    "save_games",
    "save_player",
    "scores_dataframe",
    "set_setting",
]
