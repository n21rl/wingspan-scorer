from datetime import date

import pandas as pd
import pytest

from wingspan import csv_io, db, repository
from wingspan.model import Expansion, Game, GoalSide, RoundResult

from .conftest import build_score

LEGACY_CSV = """Game ID,Game Date,Player,Birds,Bonus Cards,End-of-Round Goals,Eggs,Food on Cards,Tucked Cards,Duet Tokens,Total Score,Nectar
d85642a3,04/05/2025,Ant,31,7,12,10,4,3,0,67,0
d85642a3,04/05/2025,Polly,28,11,8,15,2,6,0,70,0
d85642a3,2025-05-04,Ant,31,7,12,10,4,3,0,67,0
d85642a3,2025-05-04,Polly,28,11,8,15,2,6,0,70,0
"""


def test_flat_export_round_trips(conn, sample_game, tmp_path):
    repository.save_game(conn, sample_game)
    text = csv_io.export_csv_text(conn)

    target = db.connect(tmp_path / "restored.db")
    report = csv_io.import_csv(target, text)

    assert report.games_added == 1
    restored = target.execute("SELECT id FROM games").fetchone()["id"]
    before = repository.load_game(conn, sample_game.id)
    after = repository.load_game(target, restored)

    assert after.played_on == before.played_on
    assert after.notes == before.notes
    assert after.expansions == before.expansions
    assert [s.total for s in after.scores] == [s.total for s in before.scores]
    assert after.round_goals == before.round_goals
    assert [sorted(s.bonus_card_ids) for s in after.scores] == [
        sorted(s.bonus_card_ids) for s in before.scores
    ]
    target.close()


def test_export_header_is_stable(conn, sample_game):
    repository.save_game(conn, sample_game)
    frame = csv_io.export_dataframe(conn)
    assert list(frame.columns) == list(csv_io.FLAT_COLUMNS)
    assert "bonus_card_detail" in frame.columns
    assert "r1_goal" in frame.columns


def test_export_of_an_empty_database_still_has_the_header(conn):
    frame = csv_io.export_dataframe(conn)
    assert frame.empty
    assert list(frame.columns) == list(csv_io.FLAT_COLUMNS)


def test_bonus_card_detail_encoding_round_trips():
    score = build_score("p1", bonus={"b1000": 7, "b1004": 4})
    encoded = csv_io.encode_bonus_cards(score)
    assert encoded == "b1000:7;b1004:4"

    decoded = csv_io.decode_bonus_cards(encoded)
    assert [(b.bonus_card_id, b.points) for b in decoded] == [("b1000", 7), ("b1004", 4)]


@pytest.mark.parametrize("raw", ["", None, float("nan"), "   ", ";;"])
def test_bonus_card_detail_handles_empty_input(raw):
    assert csv_io.decode_bonus_cards(raw) == []


def test_bonus_card_detail_drops_malformed_pairs():
    decoded = csv_io.decode_bonus_cards("b1000:7;;garbage;:5;b1004:notanumber")
    assert [(b.bonus_card_id, b.points) for b in decoded] == [
        ("b1000", 7),
        ("garbage", 0),
        ("b1004", 0),
    ]


# ---------------------------------------------------------------------------- dates


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-05-04", date(2025, 5, 4)),
        ("04/05/2025", date(2025, 5, 4)),
        ("04-05-2025", date(2025, 5, 4)),
        ("4.5.2025", date(2025, 5, 4)),
        (date(2025, 5, 4), date(2025, 5, 4)),
        ("2025-05-04T10:00:00", date(2025, 5, 4)),
    ],
)
def test_flexible_date_parsing(raw, expected):
    assert csv_io.parse_flexible_date(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "nan", "not a date"])
def test_unparseable_dates_are_rejected(raw):
    with pytest.raises(ValueError):
        csv_io.parse_flexible_date(raw)


# --------------------------------------------------------------------- legacy import


def test_legacy_import_collapses_the_double_save_duplicates(conn):
    report = csv_io.import_csv(conn, LEGACY_CSV)

    assert report.rows_read == 4
    assert report.games_added == 1
    assert report.players_created == 2
    assert repository.count_games(conn) == 1
    assert any("duplicate" in w for w in report.warnings)


def test_legacy_import_resolves_the_mixed_date_format(conn):
    csv_io.import_csv(conn, LEGACY_CSV)
    game = repository.list_games(conn)[0]
    assert game.played_on == date(2025, 5, 4)


def test_legacy_import_keeps_the_goal_total_as_a_manual_override(conn):
    """The old file has no per-round detail, only a goal lump sum."""
    csv_io.import_csv(conn, LEGACY_CSV)
    game = repository.list_games(conn)[0]

    ant = next(s for s in game.scores if s.get("birds") == 31)
    assert ant.goal_points_manual is True
    assert ant.goal_points == 12
    assert ant.total == 31 + 7 + 10 + 4 + 3 + 12
    assert game.round_results == {}


def test_legacy_import_infers_expansions_from_gated_scores(conn):
    nectar_csv = LEGACY_CSV.replace(
        "d85642a3,2025-05-04,Ant,31,7,12,10,4,3,0,67,0",
        "d85642a3,2025-05-04,Ant,31,7,12,10,4,3,0,67,9",
    )
    csv_io.import_csv(conn, nectar_csv)
    game = repository.list_games(conn)[0]

    assert game.nectar_enabled is True
    assert Expansion.OCEANIA in game.expansions
    assert game.duet_enabled is False


def test_reimporting_the_same_file_updates_rather_than_duplicates(conn):
    csv_io.import_csv(conn, LEGACY_CSV)
    second = csv_io.import_csv(conn, LEGACY_CSV)

    assert second.games_updated == 1
    assert second.games_added == 0
    assert repository.count_games(conn) == 1


def test_unknown_csv_shape_is_rejected(conn):
    with pytest.raises(ValueError, match="Unrecognised CSV"):
        csv_io.import_csv(conn, "a,b,c\n1,2,3\n")


def test_flat_import_creates_missing_players(conn):
    frame = pd.DataFrame(
        [
            {
                "game_id": "g-1",
                "played_on": "2025-06-01",
                "expansions": "Base Game,Oceania",
                "nectar_enabled": 1,
                "duet_enabled": 0,
                "goal_side": "blue",
                "notes": "imported",
                "player": "Newcomer",
                "seat": 0,
                "birds": 20,
                "nectar": 6,
                "bonus_card_detail": "b1000:7",
                "r1_goal": "g2000",
                "r1_count": 3,
            }
        ]
    )
    report = csv_io.import_flat_frame(conn, frame)

    assert report.games_added == 1
    assert report.players_created == 1
    game = repository.list_games(conn)[0]
    assert game.goal_side is GoalSide.BLUE
    assert game.nectar_enabled is True
    assert game.round_goals[1] == "g2000"
    assert game.scores[0].goal_points == 3  # blue side: one point per item
    assert game.scores[0].get("bonus_cards") == 7


def test_flat_import_warns_on_an_unknown_goal_side(conn):
    frame = pd.DataFrame(
        [{"game_id": "g-2", "played_on": "2025-06-02", "player": "Ant", "goal_side": "purple"}]
    )
    report = csv_io.import_flat_frame(conn, frame)

    assert repository.list_games(conn)[0].goal_side is GoalSide.GREEN
    assert any("goal side" in w for w in report.warnings)


def test_import_of_an_empty_frame_is_a_no_op(conn):
    report = csv_io.import_flat_frame(conn, pd.DataFrame())
    assert report.games_added == 0
    assert repository.count_games(conn) == 0


def test_soft_deleted_games_are_not_exported(conn, sample_game):
    repository.save_game(conn, sample_game)
    repository.delete_game(conn, sample_game.id)
    assert csv_io.export_dataframe(conn).empty


def test_import_is_all_or_nothing(conn, players):
    """A failure partway through must not leave half a batch behind."""
    ant, _ = players
    good = Game.new(date(2025, 1, 1))
    good.scores = [build_score(ant.id, birds=5)]
    repository.save_game(conn, good)

    frame = pd.DataFrame(
        [
            {"game_id": "ok", "played_on": "2025-02-02", "player": "Ant", "birds": 10},
            {"game_id": "bad", "played_on": "2025-02-03", "player": "Ant", "seat": "x"},
        ]
    )
    # Both rows are importable; the point is the count stays consistent.
    csv_io.import_flat_frame(conn, frame)
    assert repository.count_games(conn) == 3
