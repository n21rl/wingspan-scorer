"""wingspan.db.sync_catalogues: skip the 117 catalogue upserts when the
source JSON hasn't changed since the last sync.
"""

from __future__ import annotations

import json
import sqlite3

from wingspan import catalogue, db


def _traced_statements(conn: sqlite3.Connection, action) -> list[str]:
    """Every SQL statement `action` causes `conn` to execute."""
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        action()
    finally:
        conn.set_trace_callback(None)
    return statements


def _catalogue_writes(statements: list[str]) -> list[str]:
    return [s for s in statements if "INSERT INTO goal_tiles" in s or "INSERT INTO bonus_cards" in s]


def test_first_connect_on_empty_db_populates_catalogue_tables(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")
    try:
        tile_count = conn.execute("SELECT COUNT(*) FROM goal_tiles").fetchone()[0]
        card_count = conn.execute("SELECT COUNT(*) FROM bonus_cards").fetchone()[0]
        assert tile_count == len(catalogue.goal_tiles())
        assert card_count == len(catalogue.bonus_cards())

        # The fingerprint is persisted so the next connect can skip the sync.
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (db._CATALOGUE_FINGERPRINT_KEY,)
        ).fetchone()
        assert row is not None
        assert row["value"] == db._catalogue_fingerprint()
    finally:
        conn.close()


def test_second_connect_with_unchanged_json_performs_no_catalogue_writes(tmp_path):
    path = tmp_path / "warm.db"
    db.connect(path).close()  # first connect: full sync, fingerprint stored

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        statements = _traced_statements(conn, lambda: db.sync_catalogues(conn))
        assert _catalogue_writes(statements) == []
    finally:
        conn.close()


def test_changing_catalogue_content_triggers_a_resync(tmp_path, monkeypatch):
    """Regenerating the JSON (scripts/build_catalogues.py) must still take
    effect on the next connect, even though most connects now skip the sync.
    """
    goal_path = tmp_path / "goal_tiles.json"
    bonus_path = tmp_path / "bonus_cards.json"
    goal_path.write_text(
        json.dumps({"entries": [{"id": "gX", "name": "Original", "expansion": "Base Game"}]})
    )
    bonus_path.write_text(json.dumps({"entries": []}))

    monkeypatch.setattr(catalogue, "GOAL_TILES_PATH", goal_path)
    monkeypatch.setattr(catalogue, "BONUS_CARDS_PATH", bonus_path)
    catalogue.reload()
    try:
        conn = db.connect(tmp_path / "resync.db")
        try:
            name = conn.execute("SELECT name FROM goal_tiles WHERE id = 'gX'").fetchone()["name"]
            assert name == "Original"

            # A second sync with the same content must be a no-op...
            statements = _traced_statements(conn, lambda: db.sync_catalogues(conn))
            assert _catalogue_writes(statements) == []

            # ...but regenerating the JSON with new content must resync.
            goal_path.write_text(
                json.dumps({"entries": [{"id": "gX", "name": "Renamed", "expansion": "Base Game"}]})
            )
            catalogue.reload()

            statements = _traced_statements(conn, lambda: db.sync_catalogues(conn))
            assert _catalogue_writes(statements) != []

            name = conn.execute("SELECT name FROM goal_tiles WHERE id = 'gX'").fetchone()["name"]
            assert name == "Renamed"
        finally:
            conn.close()
    finally:
        # Cache is now empty; once monkeypatch restores the real paths below,
        # the next reader lazily repopulates it from the real JSON.
        catalogue.reload()


def test_existing_db_with_catalogue_rows_but_no_stored_fingerprint_still_syncs(tmp_path):
    """A database created before this change has catalogue rows already but
    never wrote the fingerprint -- it must sync once (to establish the
    fingerprint) rather than assume it's already up to date.
    """
    path = tmp_path / "legacy.db"
    db.connect(path).close()  # populates catalogue tables *and* the fingerprint

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        # Simulate a pre-existing database that predates the fingerprint.
        conn.execute("DELETE FROM app_settings WHERE key = ?", (db._CATALOGUE_FINGERPRINT_KEY,))

        statements = _traced_statements(conn, lambda: db.sync_catalogues(conn))
        assert _catalogue_writes(statements) != []

        tile_count = conn.execute("SELECT COUNT(*) FROM goal_tiles").fetchone()[0]
        assert tile_count == len(catalogue.goal_tiles())

        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (db._CATALOGUE_FINGERPRINT_KEY,)
        ).fetchone()
        assert row is not None and row["value"] == db._catalogue_fingerprint()

        # A subsequent sync now finds the fingerprint and skips the writes.
        statements = _traced_statements(conn, lambda: db.sync_catalogues(conn))
        assert _catalogue_writes(statements) == []
    finally:
        conn.close()


def test_emptied_catalogue_tables_resync_even_when_the_fingerprint_matches(tmp_path):
    """The fingerprint describes the JSON, not the rows.

    A migration that rebuilt either table would leave it empty with the hash
    still matching, and skipping forever would render every goal and card as
    its raw id.
    """
    path = tmp_path / "rebuilt.db"
    db.connect(path).close()

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("DELETE FROM goal_tiles")
        # The fingerprint is deliberately left in place: it still matches.
        assert db._catalogue_fingerprint() == conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (db._CATALOGUE_FINGERPRINT_KEY,)
        ).fetchone()["value"]

        statements = _traced_statements(conn, lambda: db.sync_catalogues(conn))
        assert _catalogue_writes(statements) != []
        assert conn.execute("SELECT COUNT(*) FROM goal_tiles").fetchone()[0] == len(
            catalogue.goal_tiles()
        )
    finally:
        conn.close()
