from datetime import date

import pytest

from wingspan import db, repository
from wingspan.model import (
    CATEGORY_KEYS,
    BonusCardScore,
    Game,
    Player,
    PlayerScore,
    RoundResult,
)


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture()
def players(conn):
    ant = repository.save_player(conn, Player.new("Ant", "#c10000"))
    polly = repository.save_player(conn, Player.new("Polly", "#ffc800"))
    return ant, polly


def build_score(player_id, seat=0, bonus=None, **values):
    score = PlayerScore(player_id=player_id, seat=seat, values={k: 0 for k in CATEGORY_KEYS})
    for key, value in values.items():
        score.set(key, value)
    for card_id, points in (bonus or {}).items():
        score.bonus_card_scores.append(BonusCardScore(bonus_card_id=card_id, points=points))
    return score


# Real ids from data/goal_tiles.json and data/bonus_cards.json.
GOAL_FOREST = "g2000"
GOAL_BOWL_EGGS = "g2010"
GOAL_TOTAL_BIRDS = "g2024"
GOAL_WETLAND = "g2002"
CARD_ANATOMIST = "b1000"
CARD_BIRD_COUNTER = "b1004"


@pytest.fixture()
def sample_game(players):
    """A complete two-player game with round goals and bonus cards."""
    ant, polly = players
    game = Game.new(date(2025, 5, 4))
    game.notes = "Close one"
    game.scores = [
        build_score(
            ant.id, seat=0, birds=31, eggs=12, food_on_cards=4, tucked_cards=3,
            bonus={CARD_ANATOMIST: 7},
        ),
        build_score(
            polly.id, seat=1, birds=28, eggs=15, food_on_cards=2, tucked_cards=6,
            bonus={CARD_BIRD_COUNTER: 4, CARD_ANATOMIST: 7},
        ),
    ]
    game.round_goals = {
        1: GOAL_FOREST,
        2: GOAL_BOWL_EGGS,
        3: GOAL_TOTAL_BIRDS,
        4: GOAL_WETLAND,
    }
    game.round_results = {
        1: {ant.id: RoundResult(placement=1), polly.id: RoundResult(placement=2)},
        2: {ant.id: RoundResult(placement=2), polly.id: RoundResult(placement=1)},
        3: {ant.id: RoundResult(placement=1), polly.id: RoundResult(placement=1)},
        4: {ant.id: RoundResult(placement=2), polly.id: RoundResult(placement=1)},
    }
    return game.recompute()
