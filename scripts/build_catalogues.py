#!/usr/bin/env python3
"""Regenerate the goal tile and bonus card catalogues.

Run by hand when the upstream dataset changes:

    python scripts/build_catalogues.py

Source data is the community-maintained Wingsearch dataset
(https://github.com/navarog/wingsearch), itself built on TawnyFrogmouth's
BoardGameGeek spreadsheet. That project is GPLv3, so nothing is copied
verbatim: this script reads it and writes our own files containing only the
factual game data the app needs -- tile and card names, which expansion they
come from, and their printed conditions.

The app never runs this. It reads the committed JSON under data/, so there is
no network dependency at runtime.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

BASE_URL = "https://raw.githubusercontent.com/navarog/wingsearch/master/src/assets/data"
GOALS_URL = f"{BASE_URL}/goals.json"
BONUS_URL = f"{BASE_URL}/bonus.json"

ATTRIBUTION = (
    "Derived from the Wingsearch dataset (https://github.com/navarog/wingsearch), "
    "built on TawnyFrogmouth's Wingspan spreadsheet. Factual game data only."
)

#: Upstream `Set` values -> our Expansion labels.
SET_TO_EXPANSION = {
    "core": "Base Game",
    "european": "Europe",
    "oceania": "Oceania",
    "asia": "Asia",
    "americas": "Americas",
}

#: The source marks up icons as [token]. Render them as readable words.
TOKENS = {
    # Leading spaces keep "3[point]" from rendering as "3VP"; the whitespace
    # collapse at the end of render() tidies up the rest.
    "[point]": " VP",
    "[feather]": " VP",
    # Plural reads better: "[bird] in [forest]" means birds in the forest.
    "[egg]": "eggs",
    "[bird]": "birds",
    "[card]": "cards",
    "[wild]": "food",
    "[forest]": "forest",
    "[grassland]": "grassland",
    "[wetland]": "wetland",
    "[bowl]": "bowl-nest",
    "[cavity]": "cavity-nest",
    "[ground]": "ground-nest",
    "[platform]": "platform-nest",
    "[star]": "star-nest",
    "[nectar]": "nectar",
    "[invertebrate]": "invertebrate",
    "[seed]": "seed",
    "[fish]": "fish",
    "[fruit]": "fruit",
    "[rodent]": "rodent",
    "[predator]": "predator",
    "[flocking]": "flocking",
    "[bird_with_tucked_card]": "bird with tucked cards",
    "[hummingbird]": "hummingbird",
    "[bee]": "bee",
    "[mango]": "mango",
    "[brilliant]": "brilliant",
    "[emerald]": "emerald",
    "[topaz]": "topaz",
}

#: Keyword -> goal family, tried in order. Drives the "group by family" insight.
FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nectar", ("nectar",)),
    ("nests", ("bowl", "cavity", "ground", "platform", "star", "nest")),
    ("eggs", ("egg",)),
    ("habitat", ("forest", "grassland", "wetland", "habitat", "row", "column")),
    ("food", ("food", "seed", "fish", "fruit", "rodent", "invertebrate", "supply", "cache")),
    ("cards", ("card", "hand", "tucked")),
    ("birds", ("bird",)),
)


def fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https URL
        return json.loads(response.read().decode("utf-8"))


def _collapse_repeats(text: str) -> str:
    """Turn "eggs eggs eggs" into "3 eggs".

    The source spells a quantity out as repeated icons, so a naive replacement
    produces a stutter.
    """

    def replace(match: re.Match[str]) -> str:
        word = match.group(1)
        return f"{len(match.group(0).split())} {word}"

    return re.sub(r"\b(\w+)(?: \1\b)+", replace, text)


def render(text: Any) -> str:
    """Turn the source's [token] markup into plain readable text."""
    if text is None:
        return ""
    rendered = str(text)
    for token, word in TOKENS.items():
        # Pad so adjacent icons like [egg][egg] do not fuse into one word.
        rendered = rendered.replace(token, f" {word} ")
    # Anything unmapped: drop the brackets rather than leak markup.
    rendered = re.sub(r"\[([a-z_]+)\]", lambda m: f" {m.group(1).replace('_', ' ')} ", rendered)
    rendered = re.sub(r"<[^>]+>", " ", rendered)  # a few Notes carry HTML
    rendered = re.sub(r"\s+([,.;:])", r"\1", rendered)
    rendered = re.sub(r"\s+", " ", rendered).strip()
    return _collapse_repeats(rendered)


def classify_family(text: str) -> str:
    lowered = text.lower()
    for family, keywords in FAMILY_RULES:
        if any(keyword in lowered for keyword in keywords):
            return family
    return "other"


def classify_bonus_scoring(vp_text: str) -> str:
    """`per_item` pays a flat rate per matching thing; `tiered` uses brackets."""
    lowered = vp_text.lower()
    if " per " in lowered and ":" not in lowered:
        return "per_item"
    if ";" in lowered or " to " in lowered or "+" in lowered:
        return "tiered"
    return "per_item" if " per " in lowered else "tiered"


def build_goal_tiles(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tiles: list[dict[str, Any]] = []
    for entry in raw:
        expansion = SET_TO_EXPANSION.get(str(entry.get("Set", "")).lower())
        if expansion is None:
            continue
        green = render(entry.get("Goal"))
        blue = render(entry.get("Reverse"))
        if not green:
            continue
        tiles.append(
            {
                "id": f"g{entry['id']}",
                "name": green[:1].upper() + green[1:],
                "expansion": expansion,
                "green_description": green,
                "blue_description": blue,
                # Classified from the green face only: the blue face counts a
                # different thing, so folding it in mislabels the tile.
                "family": classify_family(green),
                # Green placement awards come from the goal board (round and
                # player count), not from the tile, so every tile scores the
                # same way and the strategy name is constant for now.
                "scoring_type": "placement",
                "source_id": entry["id"],
            }
        )
    return sorted(tiles, key=lambda t: (t["expansion"], t["name"]))


def build_bonus_cards(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for entry in raw:
        expansion = SET_TO_EXPANSION.get(str(entry.get("Set", "")).lower())
        if expansion is None:
            continue
        name = render(entry.get("Bonus card"))
        if not name:
            continue
        vp_text = render(entry.get("VP"))
        cards.append(
            {
                "id": f"b{entry['id']}",
                "name": name,
                "expansion": expansion,
                "condition": render(entry.get("Condition")),
                "description": render(entry.get("Explanatory text")),
                "vp_text": vp_text,
                "scoring_type": classify_bonus_scoring(vp_text),
                "source_id": entry["id"],
            }
        )
    return sorted(cards, key=lambda c: (c["expansion"], c["name"]))


def write_catalogue(path: Path, kind: str, entries: list[dict[str, Any]]) -> None:
    payload = {
        "_comment": ATTRIBUTION,
        "kind": kind,
        "count": len(entries),
        "entries": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(entries):>3} entries -> {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goals-url", default=GOALS_URL)
    parser.add_argument("--bonus-url", default=BONUS_URL)
    parser.add_argument("--out-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    tiles = build_goal_tiles(fetch_json(args.goals_url))
    cards = build_bonus_cards(fetch_json(args.bonus_url))

    if not tiles or not cards:
        print("refusing to write an empty catalogue", file=sys.stderr)
        return 1

    write_catalogue(args.out_dir / "goal_tiles.json", "goal_tiles", tiles)
    write_catalogue(args.out_dir / "bonus_cards.json", "bonus_cards", cards)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
