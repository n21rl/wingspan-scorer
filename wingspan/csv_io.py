"""CSV export and import.

Two shapes are understood:

* **flat** -- what this app exports: one row per player per game, carrying the
  game metadata, every category, and the four rounds' goals and placements.
  Round-trips exactly, and is comfortable to edit in a spreadsheet.
* **legacy** -- the `data/scores.csv` written by the original prototype. Import
  only. It has no expansion metadata and no per-round detail, so the goal
  column is taken as a hand-entered total.
"""

from __future__ import annotations

import io
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from wingspan import repository
from wingspan.model import (
    CATEGORY_KEYS,
    ROUNDS,
    BonusCardScore,
    Expansion,
    Game,
    GoalSide,
    PlayerScore,
    RoundResult,
)

FLAT_GAME_COLUMNS = (
    "game_id",
    "played_on",
    "expansions",
    "nectar_enabled",
    "duet_enabled",
    "goal_side",
    "notes",
)
FLAT_PLAYER_COLUMNS = (
    "player",
    "seat",
    *CATEGORY_KEYS,
    "bonus_card_detail",
    "goal_points",
    "goal_points_manual",
    "total",
)

#: Bonus cards are a variable-length list per player, so they ride in one
#: column as "id:points;id:points" rather than exploding the header.
BONUS_PAIR_SEPARATOR = ";"
BONUS_FIELD_SEPARATOR = ":"


def _round_columns() -> tuple[str, ...]:
    columns: list[str] = []
    for round_no in ROUNDS:
        columns += [
            f"r{round_no}_goal",
            f"r{round_no}_placement",
            f"r{round_no}_count",
            f"r{round_no}_points",
        ]
    return tuple(columns)


FLAT_COLUMNS = (*FLAT_GAME_COLUMNS, *FLAT_PLAYER_COLUMNS, *_round_columns())

LEGACY_CATEGORY_MAP = {
    "Birds": "birds",
    "Bonus Cards": "bonus_cards",
    "Eggs": "eggs",
    "Food on Cards": "food_on_cards",
    "Tucked Cards": "tucked_cards",
    "Nectar": "nectar",
    "Duet Tokens": "duet_tokens",
}


@dataclass
class ImportReport:
    games_added: int = 0
    games_updated: int = 0
    players_created: int = 0
    rows_read: int = 0
    rows_skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def games_total(self) -> int:
        return self.games_added + self.games_updated

    def summary(self) -> str:
        parts = [
            f"{self.games_added} game(s) added",
            f"{self.games_updated} updated",
            f"{self.players_created} player(s) created",
        ]
        if self.rows_skipped:
            parts.append(f"{self.rows_skipped} row(s) skipped")
        return ", ".join(parts)


# ------------------------------------------------------------------------- helpers


def parse_flexible_date(raw: object) -> date:
    """Parse a date that may be ISO or day-first.

    The legacy file mixes `2025-05-04` and `04/05/2025` for the *same* game, so
    ISO is tried first and anything else is read day-first -- the European
    reading, which is what makes those two agree.
    """
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()

    text = str(raw).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        raise ValueError("empty date")

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    stamp = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.isna(stamp):
        raise ValueError(f"unrecognised date: {raw!r}")
    return stamp.date()


def _as_int(value: object, default: int = 0) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_optional_int(value: object) -> int | None:
    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _clean_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def encode_bonus_cards(score: PlayerScore) -> str:
    return BONUS_PAIR_SEPARATOR.join(
        f"{b.bonus_card_id}{BONUS_FIELD_SEPARATOR}{int(b.points)}"
        for b in score.bonus_card_scores
    )


def decode_bonus_cards(raw: object) -> list[BonusCardScore]:
    """Parse "id:points;id:points". Malformed pairs are dropped, not fatal."""
    text = _clean_str(raw)
    if not text:
        return []

    decoded: list[BonusCardScore] = []
    for chunk in text.split(BONUS_PAIR_SEPARATOR):
        chunk = chunk.strip()
        if not chunk:
            continue
        card_id, _, points = chunk.partition(BONUS_FIELD_SEPARATOR)
        card_id = card_id.strip()
        if card_id:
            decoded.append(BonusCardScore(bonus_card_id=card_id, points=_as_int(points)))
    return decoded


def detect_format(frame: pd.DataFrame) -> str:
    columns = set(frame.columns)
    if {"game_id", "player"} <= columns:
        return "flat"
    if {"Game ID", "Player"} <= columns:
        return "legacy"
    raise ValueError(
        "Unrecognised CSV. Expected the app's export columns (game_id, player, ...) "
        "or the legacy header (Game ID, Player, ...)."
    )


# -------------------------------------------------------------------------- export


def export_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    """The full history in the flat, round-trippable shape."""
    names = {p.id: p.name for p in repository.list_players(conn, include_archived=True)}
    rows: list[dict[str, object]] = []

    for game in repository.list_games(conn):
        for score in game.scores:
            row: dict[str, object] = {
                "game_id": game.id,
                "played_on": game.played_on.isoformat(),
                "expansions": ",".join(str(e) for e in game.expansions),
                "nectar_enabled": int(game.nectar_enabled),
                "duet_enabled": int(game.duet_enabled),
                "goal_side": str(game.goal_side),
                "notes": game.notes,
                "player": names.get(score.player_id, score.player_id),
                "seat": score.seat,
                "bonus_card_detail": encode_bonus_cards(score),
                "goal_points": score.goal_points,
                "goal_points_manual": int(score.goal_points_manual),
                "total": score.total,
            }
            row.update({key: score.get(key) for key in CATEGORY_KEYS})

            for round_no in ROUNDS:
                result = game.round_results.get(round_no, {}).get(score.player_id)
                row[f"r{round_no}_goal"] = game.round_goals.get(round_no) or ""
                row[f"r{round_no}_placement"] = result.placement if result else None
                row[f"r{round_no}_count"] = result.raw_count if result else None
                row[f"r{round_no}_points"] = result.points if result else None
            rows.append(row)

    return pd.DataFrame(rows, columns=list(FLAT_COLUMNS))


def export_csv_text(conn: sqlite3.Connection) -> str:
    return export_dataframe(conn).to_csv(index=False)


def export_csv(conn: sqlite3.Connection, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(export_csv_text(conn), encoding="utf-8")
    return target


# -------------------------------------------------------------------------- import


def read_csv(source: str | Path | io.IOBase | bytes) -> pd.DataFrame:
    """Read CSV from a path, raw text, bytes or an uploaded file object."""
    if isinstance(source, bytes):
        return pd.read_csv(io.BytesIO(source))
    if isinstance(source, (str, Path)):
        text = str(source)
        if "\n" in text or "," in text and not Path(text).exists():
            return pd.read_csv(io.StringIO(text))
        return pd.read_csv(text)
    return pd.read_csv(source)


def import_csv(conn: sqlite3.Connection, source: str | Path | io.IOBase | bytes) -> ImportReport:
    """Import either supported shape, detected from the header."""
    frame = read_csv(source)
    if detect_format(frame) == "legacy":
        return import_legacy_frame(conn, frame)
    return import_flat_frame(conn, frame)


def _resolve_players(
    conn: sqlite3.Connection, names: list[str], report: ImportReport
) -> dict[str, str]:
    """Map player names to ids, creating any that are new."""
    mapping: dict[str, str] = {}
    for name in names:
        existing = repository.get_player_by_name(conn, name)
        if existing is None:
            existing = repository.save_player(conn, repository.Player.new(name))
            report.players_created += 1
        mapping[name] = existing.id
    return mapping


def import_flat_frame(conn: sqlite3.Connection, frame: pd.DataFrame) -> ImportReport:
    report = ImportReport(rows_read=len(frame))
    if frame.empty:
        return report

    frame = frame.copy()
    frame["player"] = frame["player"].map(_clean_str)
    frame = frame[frame["player"] != ""]
    report.rows_skipped += report.rows_read - len(frame)

    existing_ids = {g.id for g in repository.list_games(conn)}
    name_to_id = _resolve_players(conn, sorted(frame["player"].unique()), report)

    games: list[Game] = []
    for game_id, block in frame.groupby("game_id", sort=False):
        first = block.iloc[0]
        try:
            played_on = parse_flexible_date(first.get("played_on"))
        except ValueError as exc:
            report.warnings.append(f"Game {game_id}: {exc}; skipped")
            report.rows_skipped += len(block)
            continue

        game = Game(
            id=_clean_str(game_id) or str(uuid.uuid4()),
            played_on=played_on,
            expansions=_parse_expansions(first.get("expansions")),
            nectar_enabled=_as_bool(first.get("nectar_enabled")),
            duet_enabled=_as_bool(first.get("duet_enabled")),
            goal_side=_parse_goal_side(first.get("goal_side"), report, game_id),
            notes=_clean_str(first.get("notes")),
        )

        for round_no in ROUNDS:
            key = _clean_str(first.get(f"r{round_no}_goal"))
            if key:
                game.round_goals[round_no] = key

        for seat, (_, row) in enumerate(block.iterrows()):
            player_id = name_to_id[row["player"]]
            score = PlayerScore(
                player_id=player_id,
                seat=_as_int(row.get("seat"), seat),
                values={key: _as_int(row.get(key)) for key in CATEGORY_KEYS},
                bonus_card_scores=decode_bonus_cards(row.get("bonus_card_detail")),
                goal_points=_as_int(row.get("goal_points")),
                goal_points_manual=_as_bool(row.get("goal_points_manual")),
            )
            game.scores.append(score)

            for round_no in ROUNDS:
                placement = _as_optional_int(row.get(f"r{round_no}_placement"))
                raw_count = _as_optional_int(row.get(f"r{round_no}_count"))
                if placement is None and raw_count is None:
                    continue
                game.round_results.setdefault(round_no, {})[player_id] = RoundResult(
                    placement=placement, raw_count=raw_count
                )

        games.append(game)
        if game.id in existing_ids:
            report.games_updated += 1
        else:
            report.games_added += 1

    repository.save_games(conn, games)
    return report


def import_legacy_frame(conn: sqlite3.Connection, frame: pd.DataFrame) -> ImportReport:
    """Import the original prototype's `data/scores.csv`.

    That file has quirks this has to absorb: the same game appears more than
    once because the old results screen re-saved on every rerun, and the date
    is written in two different formats for the same game. Rows are deduped on
    (game, player) keeping the last, which also settles the date.
    """
    report = ImportReport(rows_read=len(frame))
    if frame.empty:
        return report

    frame = frame.copy()
    frame["Player"] = frame["Player"].map(_clean_str)
    frame["Game ID"] = frame["Game ID"].map(_clean_str)
    frame = frame[(frame["Player"] != "") & (frame["Game ID"] != "")]

    before = len(frame)
    frame = frame.drop_duplicates(subset=["Game ID", "Player"], keep="last")
    duplicates = before - len(frame)
    if duplicates:
        report.warnings.append(
            f"Collapsed {duplicates} duplicate row(s) from the old double-save bug."
        )
    report.rows_skipped += report.rows_read - len(frame)

    existing_ids = {g.id for g in repository.list_games(conn)}
    name_to_id = _resolve_players(conn, sorted(frame["Player"].unique()), report)

    games: list[Game] = []
    for game_id, block in frame.groupby("Game ID", sort=False):
        try:
            played_on = parse_flexible_date(block.iloc[-1].get("Game Date"))
        except ValueError as exc:
            report.warnings.append(f"Game {game_id}: {exc}; skipped")
            report.rows_skipped += len(block)
            continue

        game = Game(id=game_id, played_on=played_on)

        for seat, (_, row) in enumerate(block.iterrows()):
            values = {key: 0 for key in CATEGORY_KEYS}
            for legacy_column, key in LEGACY_CATEGORY_MAP.items():
                values[key] = _as_int(row.get(legacy_column))

            # The legacy file has no per-round detail, only a goal total, so it
            # is carried across as a manual override rather than being derived.
            game.scores.append(
                PlayerScore(
                    player_id=name_to_id[row["Player"]],
                    seat=seat,
                    values=values,
                    goal_points=_as_int(row.get("End-of-Round Goals")),
                    goal_points_manual=True,
                )
            )

        # Expansion metadata was never recorded, but a non-zero score in a
        # gated category proves that module was on the table.
        game.nectar_enabled = any(s.get("nectar") for s in game.scores)
        game.duet_enabled = any(s.get("duet_tokens") for s in game.scores)
        if game.nectar_enabled:
            game.expansions = (Expansion.BASE, Expansion.OCEANIA)

        games.append(game)
        if game.id in existing_ids:
            report.games_updated += 1
        else:
            report.games_added += 1

    repository.save_games(conn, games)
    return report


def _parse_expansions(raw: object) -> tuple[Expansion, ...]:
    text = _clean_str(raw)
    if not text:
        return (Expansion.BASE,)
    parsed: list[Expansion] = []
    for part in text.split(","):
        part = part.strip()
        try:
            parsed.append(Expansion(part))
        except ValueError:
            continue
    return tuple(parsed) or (Expansion.BASE,)


def _parse_goal_side(raw: object, report: ImportReport, game_id: object) -> GoalSide:
    text = _clean_str(raw).lower()
    if not text:
        return GoalSide.GREEN
    try:
        return GoalSide(text)
    except ValueError:
        report.warnings.append(f"Game {game_id}: unknown goal side {raw!r}; assumed green.")
        return GoalSide.GREEN


def import_legacy_files(
    conn: sqlite3.Connection,
    scores_path: str | Path,
    players_path: str | Path | None = None,
) -> ImportReport:
    """Import the prototype's CSVs, seeding player colours from players.csv."""
    if players_path and Path(players_path).exists():
        players = pd.read_csv(players_path)
        for _, row in players.iterrows():
            name = _clean_str(row.get("Player"))
            if not name or repository.get_player_by_name(conn, name):
                continue
            player = repository.Player.new(name, _clean_str(row.get("Color")) or "#4c78a8")
            # Old paths were written on Windows; keep just the filename so the
            # avatar resolves under images/ on any platform.
            raw_picture = _clean_str(row.get("Picture"))
            if raw_picture:
                player.avatar = raw_picture.replace("\\", "/").rsplit("/", 1)[-1]
            repository.save_player(conn, player)

    return import_csv(conn, Path(scores_path))
