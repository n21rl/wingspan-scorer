"""Score entry: a wizard sized for a phone at the table.

One decision per screen, full width, with Back and Next always in reach. The
whole game lives in a single draft in session state and is only written once,
at the end, by an upsert keyed on the draft's id -- so a stray rerun cannot
save the game twice.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from views._shared import get_connection, load_defaults, player_chip
from wingspan import catalogue, repository
from wingspan.goals import GREEN_POINTS, available_places
from wingspan.model import (
    ROUNDS,
    BonusCardScore,
    EntryMode,
    Expansion,
    Game,
    GoalSide,
    PlayerScore,
    RoundResult,
)

DRAFT = "draft_game"
META = "draft_meta"
STEP = "draft_step"

#: Bonus cards get their own screen, so they are not one of the number rows.
SKIP_IN_SCORING = {"bonus_cards"}

PLACE_LABELS = ("1st", "2nd", "3rd")
NO_PLACE = "—"

conn = get_connection()


# --------------------------------------------------------------------------- state


def draft() -> Game | None:
    return st.session_state.get(DRAFT)


def meta() -> dict:
    return st.session_state.setdefault(META, {})


def reset_draft() -> None:
    for key in (DRAFT, META, STEP):
        st.session_state.pop(key, None)
    # Widget keys are namespaced by step, so clear them too or a new game
    # inherits the last one's numbers.
    for key in [k for k in st.session_state if str(k).startswith("w_")]:
        st.session_state.pop(key, None)


def steps() -> list[tuple[str, str]]:
    """(step key, screen title) for the current draft."""
    game = draft()
    options = meta()
    plan: list[tuple[str, str]] = [("setup", "Game setup")]

    scoring = [c for c in game.categories if c.key not in SKIP_IN_SCORING]
    if options.get("entry_mode") == str(EntryMode.BY_PLAYER):
        for score in game.scores:
            plan.append((f"player:{score.player_id}", player_name(score.player_id)))
    else:
        for category in scoring:
            plan.append((f"category:{category.key}", category.label))

    plan.append(("bonus", "Bonus cards"))

    if options.get("track_round_goals", True):
        plan += [(f"round:{r}", f"Round {r} goal") for r in ROUNDS]
    else:
        plan.append(("goal_total", "End-of-round goals"))

    plan.append(("review", "Review & save"))
    return plan


def go(delta: int) -> None:
    st.session_state[STEP] = max(0, min(len(steps()) - 1, st.session_state.get(STEP, 0) + delta))


def jump(index: int) -> None:
    st.session_state[STEP] = index


# --------------------------------------------------------------------------- lookups


def _roster() -> dict[str, object]:
    """Every player by id, including archived ones.

    Deliberately uncached: a player added on the Players page has to be
    selectable here on the very next rerun.
    """
    return repository.players_by_id(conn)


def player_name(player_id: str) -> str:
    player = _roster().get(player_id)
    return player.name if player else "Unknown"


def player_color(player_id: str) -> str:
    player = _roster().get(player_id)
    return player.color if player else "#4c78a8"


# ----------------------------------------------------------------------------- setup


def screen_setup() -> None:
    game = draft()
    options = meta()
    roster = repository.list_players(conn)

    if not roster:
        st.subheader("Add a player first")
        st.caption("Scores are recorded against a player, so there needs to be at least one.")
        if st.button("Go to Players", type="primary"):
            st.switch_page("views/players.py")
        return

    names = {p.name: p.id for p in roster}
    known = _roster()
    current = [player_name(pid) for pid in game.player_ids if pid in known]

    with st.form("setup", border=False):
        played_on = st.date_input("Date played", value=game.played_on, format="DD/MM/YYYY")

        chosen = st.multiselect(
            "Players",
            options=list(names),
            default=current or None,
            help="The order you pick them in is the seating order.",
        )

        expansions = st.multiselect(
            "Expansions on the table",
            options=[str(e) for e in Expansion],
            default=[str(e) for e in game.expansions],
        )

        left, right = st.columns(2)
        nectar = left.checkbox("Nectar", value=game.nectar_enabled)
        duet = right.checkbox("Duet map", value=game.duet_enabled)

        goal_side = st.radio(
            "Goal board side",
            options=[GoalSide.GREEN, GoalSide.BLUE],
            format_func=lambda s: "Green (compete for places)"
            if s is GoalSide.GREEN
            else "Blue (1 point per item)",
            index=0 if game.goal_side is GoalSide.GREEN else 1,
            horizontal=False,
        )

        entry_mode = st.radio(
            "Entry order",
            options=[EntryMode.BY_CATEGORY, EntryMode.BY_PLAYER],
            format_func=lambda m: "One category at a time (everyone at once)"
            if m is EntryMode.BY_CATEGORY
            else "One player at a time (all their categories)",
            index=0 if options.get("entry_mode") == str(EntryMode.BY_CATEGORY) else 1,
        )

        with st.expander("Detail to record"):
            track_goals = st.checkbox(
                "Record each round's goal and placements",
                value=options.get("track_round_goals", True),
                help="Off: just type each player's total goal points.",
            )
            track_bonus = st.checkbox(
                "Record which bonus cards each player kept",
                value=options.get("track_bonus_detail", True),
                help="Off: just type each player's total bonus score.",
            )

        notes = st.text_input("Notes", value=game.notes, placeholder="Optional")

        if st.form_submit_button("Start scoring", type="primary", width="stretch"):
            if not chosen:
                st.error("Pick at least one player.")
                return

            game.played_on = played_on if isinstance(played_on, date) else date.today()
            game.expansions = tuple(Expansion(e) for e in expansions) or (Expansion.BASE,)
            game.nectar_enabled = nectar
            game.duet_enabled = duet
            game.goal_side = goal_side
            game.notes = notes
            _sync_players(game, [names[n] for n in chosen])

            options.update(
                entry_mode=str(entry_mode),
                track_round_goals=track_goals,
                track_bonus_detail=track_bonus,
            )
            go(1)
            st.rerun()


def _sync_players(game: Game, player_ids: list[str]) -> None:
    """Match the draft's scores to the chosen players, keeping what was typed."""
    existing = {s.player_id: s for s in game.scores}
    game.scores = [
        existing.get(pid) or PlayerScore(player_id=pid) for pid in player_ids
    ]
    for seat, score in enumerate(game.scores):
        score.seat = seat

    kept = set(player_ids)
    for results in game.round_results.values():
        for gone in [pid for pid in results if pid not in kept]:
            results.pop(gone)


# --------------------------------------------------------------------------- scoring


def running_total(game: Game, score: PlayerScore) -> int:
    return game.category_total(score) + score.goal_points


def screen_category(category_key: str) -> None:
    """One category, every player -- the fast mode at the table."""
    game = draft()
    category = next(c for c in game.categories if c.key == category_key)

    st.caption(category.help)
    with st.form(f"cat_{category_key}", border=False):
        for score in game.scores:
            st.markdown(player_chip(player_name(score.player_id), player_color(score.player_id)), unsafe_allow_html=True)
            st.number_input(
                f"{category.label} for {player_name(score.player_id)}",
                min_value=0,
                max_value=category.cap,
                step=1,
                value=score.get(category_key),
                key=f"w_{category_key}_{score.player_id}",
                label_visibility="collapsed",
            )
            st.caption(f"Running total: {running_total(game, score)}")

        _nav_buttons(
            lambda: [
                score.set(category_key, st.session_state[f"w_{category_key}_{score.player_id}"])
                for score in game.scores
            ]
        )


def screen_player(player_id: str) -> None:
    """One player, every category -- the careful mode."""
    game = draft()
    score = game.score_for(player_id)
    categories = [c for c in game.categories if c.key not in SKIP_IN_SCORING]

    st.markdown(player_chip(player_name(player_id), player_color(player_id)), unsafe_allow_html=True)
    with st.form(f"player_{player_id}", border=False):
        for category in categories:
            st.number_input(
                f"{category.icon} {category.label}",
                min_value=0,
                max_value=category.cap,
                step=1,
                value=score.get(category.key),
                key=f"w_{player_id}_{category.key}",
                help=category.help,
            )

        _nav_buttons(
            lambda: [
                score.set(c.key, st.session_state[f"w_{player_id}_{c.key}"]) for c in categories
            ]
        )
    st.caption(f"Running total: {running_total(game, score)}")


# ---------------------------------------------------------------------- bonus cards


def screen_bonus() -> None:
    game = draft()
    if not meta().get("track_bonus_detail", True):
        _screen_simple_number("bonus_cards", "Bonus card score", "🎴")
        return

    cards = catalogue.bonus_cards_for(game.expansions)
    labels = {c.id: c.name for c in cards}
    options = list(labels)

    st.caption("Pick the cards each player kept, then enter what each one scored.")

    # The multiselects sit outside the form: choosing a card has to redraw the
    # points inputs immediately, which a form would defer until submit.
    for score in game.scores:
        st.markdown(player_chip(player_name(score.player_id), player_color(score.player_id)), unsafe_allow_html=True)
        chosen = st.multiselect(
            f"Bonus cards for {player_name(score.player_id)}",
            options=options,
            default=[b.bonus_card_id for b in score.bonus_card_scores if b.bonus_card_id in labels],
            format_func=lambda cid: labels.get(cid, cid),
            key=f"w_bonuspick_{score.player_id}",
            label_visibility="collapsed",
        )

        previous = {b.bonus_card_id: b.points for b in score.bonus_card_scores}
        updated: list[BonusCardScore] = []
        for card_id in chosen:
            card = catalogue.bonus_card(card_id)
            points = st.number_input(
                f"{labels.get(card_id, card_id)} — points",
                min_value=0,
                max_value=60,
                step=1,
                value=int(previous.get(card_id, 0)),
                key=f"w_bonuspts_{score.player_id}_{card_id}",
                help=card.vp_text if card else None,
            )
            updated.append(BonusCardScore(bonus_card_id=card_id, points=int(points)))

        score.bonus_card_scores = updated
        score.set("bonus_cards", sum(b.points for b in updated))
        st.caption(f"Bonus total: {score.get('bonus_cards')} · running total: {running_total(game, score)}")
        st.divider()

    _nav_buttons(None, in_form=False)


def _screen_simple_number(category_key: str, label: str, icon: str) -> None:
    """Fallback when the user opted out of card-level or round-level detail."""
    game = draft()
    with st.form(f"simple_{category_key}", border=False):
        for score in game.scores:
            st.number_input(
                f"{icon} {label} — {player_name(score.player_id)}",
                min_value=0,
                max_value=200,
                step=1,
                value=score.get(category_key),
                key=f"w_simple_{category_key}_{score.player_id}",
            )
        _nav_buttons(
            lambda: [
                score.set(
                    category_key,
                    st.session_state[f"w_simple_{category_key}_{score.player_id}"],
                )
                for score in game.scores
            ]
        )


# ------------------------------------------------------------------- round goals


def screen_round(round_no: int) -> None:
    game = draft()
    tiles = catalogue.goal_tiles_for(game.expansions)
    tile_ids = [t.id for t in tiles]
    labels = {t.id: t.name for t in tiles}

    current = game.round_goals.get(round_no)
    index = tile_ids.index(current) + 1 if current in tile_ids else 0

    # Outside the form: picking the tile updates the description and the blue
    # side's wording straight away.
    chosen = st.selectbox(
        f"Which goal was round {round_no}?",
        options=[None, *tile_ids],
        index=index,
        format_func=lambda tid: "Not recorded" if tid is None else labels.get(tid, tid),
        key=f"w_goalpick_{round_no}",
    )
    game.round_goals[round_no] = chosen

    tile = catalogue.goal_tile(chosen)
    if tile:
        st.caption(f"{tile.description_for(game.goal_side)} · {tile.family}")

    green = game.goal_side is GoalSide.GREEN
    if green:
        awards = GREEN_POINTS[round_no]
        places = available_places(len(game.scores))
        st.caption(
            "This round pays "
            + ", ".join(f"{PLACE_LABELS[i]} {awards[i]}" for i in range(places))
            + ". Ties share the places they take up."
        )
    else:
        st.caption("Blue side: 1 point per qualifying item.")

    with st.form(f"round_{round_no}", border=False):
        results = game.round_results.setdefault(round_no, {})
        for score in game.scores:
            st.markdown(player_chip(player_name(score.player_id), player_color(score.player_id)), unsafe_allow_html=True)
            existing = results.get(score.player_id, RoundResult())

            if green:
                places = available_places(len(game.scores))
                choices = [*PLACE_LABELS[:places], NO_PLACE]
                default = (
                    PLACE_LABELS[existing.placement - 1]
                    if existing.placement and existing.placement <= places
                    else NO_PLACE
                )
                st.segmented_control(
                    f"Placement for {player_name(score.player_id)}",
                    options=choices,
                    default=default,
                    key=f"w_place_{round_no}_{score.player_id}",
                    label_visibility="collapsed",
                )
            else:
                st.number_input(
                    f"Count for {player_name(score.player_id)}",
                    min_value=0,
                    max_value=99,
                    step=1,
                    value=existing.raw_count or 0,
                    key=f"w_count_{round_no}_{score.player_id}",
                    label_visibility="collapsed",
                )

        if green:
            st.caption(f"“{NO_PLACE}” means they had none of it, so they do not place.")

        _nav_buttons(lambda: _commit_round(round_no))


def _commit_round(round_no: int) -> None:
    game = draft()
    green = game.goal_side is GoalSide.GREEN
    results: dict[str, RoundResult] = {}

    for score in game.scores:
        if green:
            picked = st.session_state.get(f"w_place_{round_no}_{score.player_id}")
            placement = PLACE_LABELS.index(picked) + 1 if picked in PLACE_LABELS else None
            results[score.player_id] = RoundResult(placement=placement)
        else:
            count = st.session_state.get(f"w_count_{round_no}_{score.player_id}", 0)
            results[score.player_id] = RoundResult(raw_count=int(count))

    game.round_results[round_no] = results
    game.recompute()


def screen_goal_total() -> None:
    """Manual goal points when the user skipped round-by-round detail."""
    game = draft()
    st.caption("Total end-of-round goal points for each player.")
    with st.form("goal_total", border=False):
        for score in game.scores:
            st.number_input(
                f"🏆 {player_name(score.player_id)}",
                min_value=0,
                max_value=99,
                step=1,
                value=score.goal_points,
                key=f"w_goaltotal_{score.player_id}",
            )
        _nav_buttons(_commit_goal_totals)


def _commit_goal_totals() -> None:
    game = draft()
    for score in game.scores:
        score.goal_points = int(st.session_state.get(f"w_goaltotal_{score.player_id}", 0))
        score.goal_points_manual = True
    game.recompute()


# ---------------------------------------------------------------------------- review


def screen_review() -> None:
    game = draft().recompute()
    winners = set(game.winners())

    st.caption(f"{game.played_on:%d %b %Y} · {len(game.scores)} players")

    for score in sorted(game.scores, key=lambda s: -s.total):
        name = player_name(score.player_id)
        crown = " 👑" if score.player_id in winners else ""
        with st.container(border=True):
            st.markdown(
                player_chip(f"**{name}**{crown} — {score.total}", player_color(score.player_id)),
                unsafe_allow_html=True,
            )
            parts = [
                f"{c.icon} {c.label} {score.get(c.key)}"
                for c in game.categories
                if score.get(c.key)
            ]
            parts.append(f"🏆 Goals {score.goal_points}")
            st.caption(" · ".join(parts))

            if score.bonus_card_scores:
                st.caption(
                    "Bonus: "
                    + ", ".join(
                        f"{catalogue.bonus_card_name(b.bonus_card_id)} {b.points}"
                        for b in score.bonus_card_scores
                    )
                )

    with st.expander("Jump back and fix something"):
        for index, (key, title) in enumerate(steps()):
            if key in {"setup", "review"}:
                continue
            if st.button(title, key=f"jump_{key}", width="stretch"):
                jump(index)
                st.rerun()

    saved_id = meta().get("saved_id")
    label = "Update game" if saved_id else "Save game"

    left, right = st.columns([1, 2])
    if left.button("Back", width="stretch"):
        go(-1)
        st.rerun()
    if right.button(label, type="primary", width="stretch"):
        repository.save_game(conn, game)
        meta()["saved_id"] = game.id
        st.success(f"Saved. {_winner_sentence(game, winners)}")
        st.balloons()

    if saved_id:
        st.caption("Saved. Saving again updates this game rather than adding another.")
        if st.button("Start another game", width="stretch"):
            reset_draft()
            st.rerun()


def _winner_sentence(game: Game, winners: set[str]) -> str:
    names = [player_name(pid) for pid in winners]
    best = max((s.total for s in game.scores), default=0)
    if len(names) == 1:
        return f"{names[0]} wins with {best}."
    return f"It's a tie on {best}: {', '.join(names)}."


# ------------------------------------------------------------------------ navigation


def _nav_buttons(commit, in_form: bool = True) -> None:
    """Back / Next, committing this screen's widgets into the draft.

    Both directions commit, so stepping back never silently discards what was
    just typed.
    """
    back_col, next_col = st.columns([1, 2])
    button = st.form_submit_button if in_form else st.button

    with back_col:
        back = button("Back", width="stretch")
    with next_col:
        forward = button("Next", type="primary", width="stretch")

    if back or forward:
        if commit:
            commit()
        draft().recompute()
        go(1 if forward else -1)
        st.rerun()


def _progress(index: int, total: int, title: str) -> None:
    st.progress((index + 1) / total, text=f"Step {index + 1} of {total} · {title}")


# -------------------------------------------------------------------------- dispatch


def main() -> None:
    if draft() is None:
        defaults = load_defaults()
        game = Game.new()
        game.expansions = tuple(
            Expansion(e) for e in defaults.get("expansions", []) if e in set(Expansion)
        ) or (Expansion.BASE,)
        game.nectar_enabled = bool(defaults.get("nectar_enabled"))
        game.duet_enabled = bool(defaults.get("duet_enabled"))
        game.goal_side = GoalSide(defaults.get("goal_side", GoalSide.GREEN))

        roster = {p.name: p.id for p in repository.list_players(conn)}
        game.scores = [
            PlayerScore(player_id=roster[name], seat=seat)
            for seat, name in enumerate(defaults.get("players", []))
            if name in roster
        ]

        st.session_state[DRAFT] = game
        st.session_state[META] = {
            "entry_mode": defaults.get("entry_mode", str(EntryMode.BY_CATEGORY)),
            "track_round_goals": bool(defaults.get("track_round_goals", True)),
            "track_bonus_detail": bool(defaults.get("track_bonus_detail", True)),
        }
        st.session_state[STEP] = 0

    plan = steps()
    index = min(st.session_state.get(STEP, 0), len(plan) - 1)
    key, title = plan[index]

    st.title(title)
    if index:
        _progress(index, len(plan), title)

    if key == "setup":
        screen_setup()
    elif key.startswith("category:"):
        screen_category(key.split(":", 1)[1])
    elif key.startswith("player:"):
        screen_player(key.split(":", 1)[1])
    elif key == "bonus":
        screen_bonus()
    elif key.startswith("round:"):
        screen_round(int(key.split(":", 1)[1]))
    elif key == "goal_total":
        screen_goal_total()
    elif key == "review":
        screen_review()

    if index:
        st.divider()
        if st.button("Discard this game", width="stretch"):
            reset_draft()
            st.rerun()


main()
