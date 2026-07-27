"""Domain model for a game of Wingspan.

The scoring categories live here and only here. Everything else -- the SQLite
columns, the entry screens, the CSV export header, the charts -- derives its
list of categories from `CATEGORIES`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

ROUNDS = (1, 2, 3, 4)


class Expansion(StrEnum):
    BASE = "Base Game"
    EUROPE = "Europe"
    OCEANIA = "Oceania"
    ASIA = "Asia"
    AMERICAS = "Americas"


class GoalSide(StrEnum):
    """Which face of the end-of-round goal tiles is in play.

    GREEN is the competitive side: players are ranked and score by placement.
    BLUE is the friendly side: every player scores 1 point per qualifying item.
    """

    GREEN = "green"
    BLUE = "blue"


class EntryMode(StrEnum):
    BY_CATEGORY = "Category-by-category"
    BY_PLAYER = "Player-by-player"


@dataclass(frozen=True)
class Category:
    """One scoring row on the Wingspan pad.

    `gate` names the game option that must be enabled for the category to
    apply; None means it always applies. `cap` is an upper bound for entry
    widgets -- generous enough never to block a real score, tight enough to
    catch a fat-fingered extra digit.
    """

    key: str
    label: str
    icon: str
    gate: str | None
    cap: int
    help: str


CATEGORIES: tuple[Category, ...] = (
    Category("birds", "Birds", "🐦", None, 120, "Points printed on the birds in your play area."),
    Category("bonus_cards", "Bonus cards", "🎴", None, 60, "Total from your bonus cards."),
    Category("eggs", "Eggs", "🥚", None, 80, "1 point per egg on your birds."),
    Category("food_on_cards", "Food on cards", "🌾", None, 60, "1 point per food token cached on a bird."),
    Category("tucked_cards", "Tucked cards", "🪶", None, 60, "1 point per card tucked under a bird."),
    Category("nectar", "Nectar", "🍯", "nectar", 30, "Nectar majorities across the three habitats."),
    Category("duet_tokens", "Duet tokens", "🔗", "duet", 30, "Points scored on the duet map."),
)

CATEGORY_KEYS: tuple[str, ...] = tuple(c.key for c in CATEGORIES)
CATEGORIES_BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}

#: Pseudo-category used wherever goal points need a label alongside the real ones.
GOAL_KEY = "goal_points"
GOAL_LABEL = "End-of-round goals"
GOAL_ICON = "🏆"


def active_categories(*, nectar_enabled: bool, duet_enabled: bool) -> tuple[Category, ...]:
    """The categories that apply given a game's options."""
    enabled = {"nectar": nectar_enabled, "duet": duet_enabled}
    return tuple(c for c in CATEGORIES if c.gate is None or enabled[c.gate])


@dataclass
class Player:
    id: str
    name: str
    color: str = "#4c78a8"
    avatar: str | None = None
    archived: bool = False

    @staticmethod
    def new(name: str, color: str = "#4c78a8", avatar: str | None = None) -> Player:
        return Player(id=str(uuid.uuid4()), name=name, color=color, avatar=avatar)


@dataclass
class RoundResult:
    """One player's outcome on one end-of-round goal.

    On the green side `placement` is 1/2/3 (or None for unplaced). On the blue
    side `raw_count` holds the number of qualifying items. `points` is derived
    by `wingspan.goals` and cached here.
    """

    placement: int | None = None
    raw_count: int | None = None
    points: int = 0


@dataclass
class BonusCardScore:
    """One bonus card a player kept, and what it scored them.

    Points are always entered by hand -- the app records what the card paid
    out, it never tries to work that out from the state of the game.
    """

    bonus_card_id: str
    points: int = 0


@dataclass
class PlayerScore:
    player_id: str
    seat: int = 0
    values: dict[str, int] = field(default_factory=lambda: {k: 0 for k in CATEGORY_KEYS})
    goal_points: int = 0
    goal_points_manual: bool = False
    bonus_card_scores: list[BonusCardScore] = field(default_factory=list)
    total: int = 0

    def get(self, key: str) -> int:
        return int(self.values.get(key, 0))

    def set(self, key: str, value: int) -> None:
        self.values[key] = int(value)

    @property
    def bonus_card_ids(self) -> list[str]:
        return [b.bonus_card_id for b in self.bonus_card_scores]


@dataclass
class Game:
    id: str
    played_on: date
    expansions: tuple[Expansion, ...] = (Expansion.BASE,)
    nectar_enabled: bool = False
    duet_enabled: bool = False
    goal_side: GoalSide = GoalSide.GREEN
    notes: str = ""
    scores: list[PlayerScore] = field(default_factory=list)
    #: round number -> goal key from `wingspan.goals.GOAL_CATALOG` (or None)
    round_goals: dict[int, str | None] = field(default_factory=dict)
    #: round number -> player id -> RoundResult
    round_results: dict[int, dict[str, RoundResult]] = field(default_factory=dict)

    @staticmethod
    def new(played_on: date | None = None) -> Game:
        return Game(id=str(uuid.uuid4()), played_on=played_on or date.today())

    @property
    def categories(self) -> tuple[Category, ...]:
        return active_categories(
            nectar_enabled=self.nectar_enabled, duet_enabled=self.duet_enabled
        )

    @property
    def player_ids(self) -> list[str]:
        return [s.player_id for s in self.scores]

    def score_for(self, player_id: str) -> PlayerScore | None:
        return next((s for s in self.scores if s.player_id == player_id), None)

    def category_total(self, score: PlayerScore) -> int:
        """Sum of the categories that apply to this game -- goals excluded."""
        return sum(score.get(c.key) for c in self.categories)

    def recompute(self) -> Game:
        """Refresh every derived number in place, then return self.

        Stored totals are a cache for querying and charting, never the source
        of truth: they are rebuilt from the components here, and this runs on
        both save and load so an edit session always starts from derived
        values.

        Bonus card points come from the individual cards when any were
        recorded. Goal points come from the round results unless a player's
        goal score was overridden by hand. Totals follow from the categories
        actually in play, so a nectar score entered and then switched off never
        leaks into the total.
        """
        from wingspan import goals as goals_mod

        derived = goals_mod.game_goal_points(self)
        for score in self.scores:
            if score.bonus_card_scores:
                score.set("bonus_cards", sum(b.points for b in score.bonus_card_scores))
            if not score.goal_points_manual:
                score.goal_points = derived.get(score.player_id, 0)
            score.total = self.category_total(score) + score.goal_points
        return self

    def winners(self) -> list[str]:
        """Player ids with the highest total. Empty when there are no scores.

        Wingspan breaks a tie on total in favour of the most food remaining,
        which this app does not track, so genuine ties are reported as ties.
        """
        if not self.scores:
            return []
        best = max(s.total for s in self.scores)
        return [s.player_id for s in self.scores if s.total == best]
