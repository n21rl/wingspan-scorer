"""SQLite connection handling and schema migrations."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "wingspan.db"

#: Each entry is one migration: a tuple of statements applied in a transaction.
#: Append new migrations, never edit an applied one.
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """
        CREATE TABLE players (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            color       TEXT NOT NULL DEFAULT '#4c78a8',
            avatar      TEXT,
            archived    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE games (
            id              TEXT PRIMARY KEY,
            played_on       TEXT NOT NULL,
            expansions      TEXT NOT NULL DEFAULT '',
            nectar_enabled  INTEGER NOT NULL DEFAULT 0,
            duet_enabled    INTEGER NOT NULL DEFAULT 0,
            goal_side       TEXT NOT NULL DEFAULT 'green',
            notes           TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE game_players (
            game_id             TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            player_id           TEXT NOT NULL REFERENCES players(id),
            seat                INTEGER NOT NULL DEFAULT 0,
            birds               INTEGER NOT NULL DEFAULT 0,
            bonus_cards         INTEGER NOT NULL DEFAULT 0,
            eggs                INTEGER NOT NULL DEFAULT 0,
            food_on_cards       INTEGER NOT NULL DEFAULT 0,
            tucked_cards        INTEGER NOT NULL DEFAULT 0,
            nectar              INTEGER NOT NULL DEFAULT 0,
            duet_tokens         INTEGER NOT NULL DEFAULT 0,
            goal_points         INTEGER NOT NULL DEFAULT 0,
            goal_points_manual  INTEGER NOT NULL DEFAULT 0,
            total               INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (game_id, player_id)
        )
        """,
        """
        CREATE TABLE game_round_goals (
            game_id   TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            round_no  INTEGER NOT NULL CHECK (round_no BETWEEN 1 AND 4),
            goal_key  TEXT,
            PRIMARY KEY (game_id, round_no)
        )
        """,
        """
        CREATE TABLE game_round_results (
            game_id    TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            round_no   INTEGER NOT NULL CHECK (round_no BETWEEN 1 AND 4),
            player_id  TEXT NOT NULL REFERENCES players(id),
            placement  INTEGER,
            raw_count  INTEGER,
            points     INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (game_id, round_no, player_id)
        )
        """,
        """
        CREATE TABLE app_settings (
            key    TEXT PRIMARY KEY,
            value  TEXT NOT NULL
        )
        """,
        "CREATE INDEX idx_game_players_player ON game_players(player_id)",
        "CREATE INDEX idx_games_played_on ON games(played_on)",
        "CREATE INDEX idx_round_results_player ON game_round_results(player_id)",
    ),
    # 002 -- goals and bonus cards become catalogued entities, plus a grace
    # period on delete.
    (
        "ALTER TABLE game_round_goals RENAME TO game_goals",
        "ALTER TABLE game_goals RENAME COLUMN goal_key TO goal_tile_id",
        "ALTER TABLE game_round_results RENAME TO player_goal_scores",
        "ALTER TABLE games ADD COLUMN deleted_at TEXT",
        """
        CREATE TABLE goal_tiles (
            id                TEXT PRIMARY KEY,
            name              TEXT NOT NULL,
            expansion         TEXT NOT NULL,
            description       TEXT NOT NULL DEFAULT '',
            blue_description  TEXT NOT NULL DEFAULT '',
            family            TEXT NOT NULL DEFAULT 'other',
            scoring_type      TEXT NOT NULL DEFAULT 'placement'
        )
        """,
        """
        CREATE TABLE bonus_cards (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            expansion     TEXT NOT NULL,
            condition     TEXT NOT NULL DEFAULT '',
            description   TEXT NOT NULL DEFAULT '',
            vp_text       TEXT NOT NULL DEFAULT '',
            scoring_type  TEXT NOT NULL DEFAULT 'tiered'
        )
        """,
        """
        CREATE TABLE player_bonus_cards (
            game_id        TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            player_id      TEXT NOT NULL REFERENCES players(id),
            bonus_card_id  TEXT NOT NULL,
            points         INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (game_id, player_id, bonus_card_id)
        )
        """,
        "CREATE INDEX idx_player_bonus_cards_card ON player_bonus_cards(bonus_card_id)",
        "CREATE INDEX idx_player_bonus_cards_player ON player_bonus_cards(player_id)",
        "CREATE INDEX idx_game_goals_tile ON game_goals(goal_tile_id)",
        "CREATE INDEX idx_games_deleted_at ON games(deleted_at)",
    ),
)

SCHEMA_VERSION = len(MIGRATIONS)


def resolve_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Where the database lives.

    Explicit argument wins, then $WINGSPAN_DB, then `data/wingspan.db` resolved
    against the repository root -- not the working directory, so the app runs
    from anywhere.
    """
    if path is not None:
        return Path(path)
    env = os.environ.get("WINGSPAN_DB")
    return Path(env) if env else DEFAULT_DB_PATH


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open a migrated connection.

    SQLite disables foreign keys per connection by default, which would make
    every ON DELETE CASCADE above silently do nothing.
    """
    target = resolve_path(path)
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    sync_catalogues(conn)
    purge_deleted(conn)
    return conn


#: How long a soft-deleted game stays recoverable before it is really gone.
DELETE_GRACE_DAYS = 30


def sync_catalogues(conn: sqlite3.Connection) -> None:
    """Mirror the JSON catalogues into their tables.

    Reference data, refreshed on every connect, so regenerating the JSON and
    restarting is enough to pick up new tiles or cards -- no migration needed.
    """
    from wingspan import catalogue  # late: catalogue imports ROOT from here

    conn.execute("BEGIN")
    try:
        for tile in catalogue.goal_tiles():
            conn.execute(
                """
                INSERT INTO goal_tiles
                    (id, name, expansion, description, blue_description, family, scoring_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name, expansion = excluded.expansion,
                    description = excluded.description,
                    blue_description = excluded.blue_description,
                    family = excluded.family, scoring_type = excluded.scoring_type
                """,
                (
                    tile.id,
                    tile.name,
                    str(tile.expansion),
                    tile.green_description,
                    tile.blue_description,
                    tile.family,
                    tile.scoring_type,
                ),
            )
        for card in catalogue.bonus_cards():
            conn.execute(
                """
                INSERT INTO bonus_cards
                    (id, name, expansion, condition, description, vp_text, scoring_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name, expansion = excluded.expansion,
                    condition = excluded.condition, description = excluded.description,
                    vp_text = excluded.vp_text, scoring_type = excluded.scoring_type
                """,
                (
                    card.id,
                    card.name,
                    str(card.expansion),
                    card.condition,
                    card.description,
                    card.vp_text,
                    card.scoring_type,
                ),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def purge_deleted(conn: sqlite3.Connection, older_than_days: int = DELETE_GRACE_DAYS) -> int:
    """Hard-delete games whose undo window has expired. Children cascade."""
    cursor = conn.execute(
        """
        DELETE FROM games
        WHERE deleted_at IS NOT NULL
          AND julianday('now') - julianday(deleted_at) > ?
        """,
        (int(older_than_days),),
    )
    return cursor.rowcount or 0


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        return 0
    return int(row["version"])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply any outstanding migrations. Safe to call on every connect."""
    version = current_version(conn)
    for index in range(version, len(MIGRATIONS)):
        conn.execute("BEGIN")
        try:
            for statement in MIGRATIONS[index]:
                conn.execute(statement)
            conn.execute("UPDATE schema_version SET version = ?", (index + 1,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return SCHEMA_VERSION
