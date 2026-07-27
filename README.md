# Wingspan Score Tracker

A Streamlit app for scoring games of Wingspan, built for a phone at the table:
fast tap entry, a review step before anything is saved, and charts that answer
where your points actually come from.

```bash
pip install -r requirements.txt
streamlit run app.py
```

## What it records

Per game: date, players and seating order, expansions on the table, nectar and
duet toggles, which side of the goal board was used, and notes.

Per player: the six scoring categories, the individual **bonus cards** they kept
and what each one scored, and their **placement in each of the four end-of-round
goals**. Bonus and goal totals are derived from those details, so the Insights
page can break them down rather than showing one lump sum.

## Pages

| Page | What it does |
|---|---|
| **Enter scores** | A wizard, one decision per screen, with Back/Next and a review step. Two entry orders: one category at a time (everyone at once) or one player at a time. |
| **Insights** | Score trends, win rates, head-to-head, category contribution, and per-card and per-goal-tile performance. |
| **History** | Review, edit or delete a saved game. Deletes have an undo window. |
| **Players** | Names, colours and avatars. A player's colour is their colour in every chart. |
| **Settings** | Defaults for new games, CSV backup and restore, and the deleted-game bin. |

## How scoring works

End-of-round goals on the green side pay by placement and round (1st/2nd/3rd:
4/1/0, 5/2/1, 6/3/2, 7/4/3). Tied players pool the points for the places they
occupy and split them, rounding down. A two-player game has no third place. A
player with none of the goal item does not place at all. The blue side scores
one point per qualifying item.

Bonus card points are always entered by hand — the app records what a card paid
out and never tries to infer it from the state of the game.

Stored totals are a cache for querying and charting. They are recomputed from
the underlying scores on every save *and* every load, so they cannot drift.

## Data

Everything lives in `data/wingspan.db` (SQLite). Settings → Backup exports the
whole history as one flat CSV, one row per player per game, and imports the same
shape back — matching on game id, so re-importing updates rather than
duplicating. It also reads the CSV format written by the previous version of
this app.

Deleting a game is soft: it stays recoverable for 30 days (Settings → Recently
deleted) before being purged.

### Catalogues

`data/goal_tiles.json` and `data/bonus_cards.json` hold the 56 goal tiles and 61
bonus cards across the base game, Europe, Oceania, Asia and Americas. They are
read from disk — **the app makes no network calls at runtime**.

Regenerate them with:

```bash
python scripts/build_catalogues.py
```

That script derives the factual game data (names, expansions, conditions, VP
text) from the community-maintained
[Wingsearch](https://github.com/navarog/wingsearch) dataset, itself built on
TawnyFrogmouth's Wingspan spreadsheet. Thanks to both. Nothing from that GPLv3
project is redistributed here.

## Layout

```
app.py                 navigation shell, page config, mobile CSS
views/                 one module per page (Streamlit only lives here)
wingspan/
  model.py             scoring categories, Game/PlayerScore, recompute()
  goals.py             end-of-round goal scoring rules
  catalogue.py         goal tile and bonus card catalogues
  db.py                schema, migrations, catalogue sync, purge
  repository.py        all reads and writes; views never touch SQL
  csv_io.py            CSV export and import
  stats.py             pandas aggregations
  charts.py            Altair chart specs
scripts/               catalogue generator
tests/                 pytest
```

Nothing under `wingspan/` imports Streamlit, so the domain, storage and chart
specs are all testable headlessly.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers scoring and tie-splitting, migrations, storage round-trips, CSV
import of the legacy format, the stats aggregations, and a smoke test per page
against both an empty and a seeded database.

To point the app at a different database, set `WINGSPAN_DB`:

```bash
WINGSPAN_DB=/tmp/scratch.db streamlit run app.py
```
