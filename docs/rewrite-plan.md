# Rewrite plan: Streamlit → FastAPI + React PWA

Status: **planned, not started.** The performance and auth groundwork described
under "Already done" has landed; no frontend work has begun.

## Why

Three separate problems were being felt as one "the app is sluggish":

1. **Cold start.** The deployment runs with `min_machines_running = 0`, so the
   machine suspends when idle and the first visit after a gap pays the resume.
2. **Per-interaction latency.** Streamlit reruns the whole script on every
   widget interaction, each one a round trip to `ams`. Entering one game walked
   through up to 13 screens, so 13 round trips at a table on phone data.
3. **Work repeated on every rerun.** N+1 queries, no caching, and `st.tabs`
   rendering all four tab bodies to show one.

(3) was fixed in place — see "Already done". (2) is structural to Streamlit's
execution model and is the reason for this rewrite. (1) is mostly solved *by*
the rewrite: a service worker can serve the app shell while the machine wakes,
which Streamlit cannot do because it needs a live WebSocket before rendering
anything at all.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Backend | **Keep Python** | `stats.py`, `csv_io.py`, `goals.py` and `repository.py` are well covered by ~1,300 lines of tests. Porting pandas aggregations to JS is the highest-risk, lowest-reward part of a migration and buys nothing user-visible. |
| Frontend | **React + Vite + TypeScript** | Most maintainable by a future contributor or tool. SvelteKit would give a smaller bundle and was the closer technical call. |
| Offline scope | **Resilient entry, not full offline-first** | Entry is local and instant; losing signal mid-game costs nothing. Insights and History need a connection. Avoids building a sync layer. |
| Auth | **Single shared passphrase** | No user accounts wanted. See "Auth" below. |
| Multi-group | **Not now, but not designed out** | See "Multi-group" below. |
| Always-on machine | **No** | Rejected on cost (~$3/month). The PWA is the cold-start answer instead. |

## Architecture

One Fly machine, one volume, one SQLite file — unchanged. FastAPI serves both
the JSON API and the built SPA as static files, so there is no CORS, no second
origin and no second deploy target.

```
Browser (React PWA)  ──HTTP/JSON──>  FastAPI  ──>  wingspan/  ──>  SQLite on /data
  service worker: app shell + bootstrap cache
  localStorage:   in-progress game draft
```

**`charts.py` needs no rewrite.** It already emits Vega-Lite specs; Altair is
just a Python wrapper over Vega-Lite, which is a JS library. The API serves
`chart.to_dict()` and `vega-embed` renders it. Only the transport changes.

**Ported to TypeScript:** the goal-placement rules and category totalling only
(~150 lines), because entry must compute running totals with no network. The
tie-pooling logic in `goals.py:47-80` is subtle — placements read as a ranking,
tied players pool the awards for the places they occupy and split rounded down.
Parity approach: generate a JSON fixture of scoring cases from
`tests/test_scoring.py` and assert it from both pytest and vitest, so the two
implementations cannot silently diverge.

**Deleted at cutover:** `views/`, `app.py`, `wingspan/auth.py`, and `streamlit`
from `requirements.txt`.

## API surface

- `GET  /api/bootstrap` — players, defaults, full catalogue in one call;
  service-worker cached
- `GET|POST|PATCH|DELETE /api/players[/{id}]`, `POST /api/players/{id}/avatar`
- `GET  /api/games?limit&offset` — paginated
- `GET  /api/games/{id}`, `PUT /api/games/{id}` (upsert on id, same semantics as
  `repository.save_game` today), `DELETE`, `POST /api/games/{id}/restore`
- `GET  /api/insights?start&end&players[]&expansions[]&min_games` — Vega-Lite
  specs plus table data
- `GET|PUT /api/settings`, `GET /api/export.csv`, `POST /api/import`
- `POST /api/login`, `GET /api/health`

Uploaded avatars need a static mount (`/media`) pointing at `WINGSPAN_IMAGES`.

## Entry redesign

Today: up to 13 screens, each a network round trip.

After: **setup → scoring → bonus → goals → review**, every keystroke local.

The two existing entry modes survive as a client-side view toggle over the same
local state — same mental model, but switching is free rather than a round trip.
The four round-goal screens collapse into one, with placement points recomputing
live.

The draft lives in `localStorage`, so closing the browser mid-game no longer
loses it. Today a dead Streamlit session takes the in-progress game with it.

## Auth

Passphrase in a Fly secret, never in the repo. `POST /api/login` compares with
`secrets.compare_digest` **over UTF-8 bytes** — `compare_digest` raises
`TypeError` on non-ASCII `str`, which would take the login page down rather than
reject the attempt. Sets a signed, `httpOnly`, `Secure`, `SameSite=Lax` cookie
with a long expiry: this is a phone at a table, and nobody should retype a
passphrase before every game. All `/api/*` routes require it. Rate-limit login.

**Design the login to resolve to an identity, not a boolean**, even with exactly
one identity. That is the same shape multi-group would need, and it costs nothing
today. See below.

## Multi-group

Explicitly **out of scope for now**, but the current schema forecloses it and
that is worth recording:

- `players.name` is `TEXT NOT NULL UNIQUE` (`db.py:19`) — one global namespace
- `games` has no owner column
- `app_settings` is a single flat key/value table; `game_defaults` is **one row**
  shared by everyone

So there is exactly one dataset. Two play groups would see each other's games,
collide on player names, and overwrite each other's defaults. Adding this later
means a migration, `name` becoming unique per group, and group scoping on every
read, write, export and import. Retrofitting is much more expensive than
designing it in, so avoid *precluding* it even while not building it.

## Phasing

Each phase leaves a working, deployable app.

1. **FastAPI alongside Streamlit.** Both run. API tests.
2. **Vite/React skeleton** at `/app`, Streamlit still at `/`. Bootstrap +
   players + read-only history. **Service worker lands here**, not late — it is
   load-bearing for perceived cold-start performance, not just installability.
3. **Entry wizard** — ported scoring, parity fixture, localStorage drafts.
4. **Insights** via vega-embed.
5. **Settings, CSV import/export, avatars.**
6. **Cutover** — SPA at `/`, delete `views/` and `app.py`, multi-stage
   Dockerfile (node build → python runtime), health check `/_stcore/health` →
   `/api/health`.

Testing: the existing pytest suite stays green throughout; vitest for scoring
parity; a Playwright smoke test entering a full game.

## Already done (landed on `claude/streamlit-performance-ux-8nujam`)

These were worth doing regardless of the rewrite, because they live in code the
rewrite keeps:

- **N+1 query elimination.** `list_games` went from 4 queries per game to one
  per child table (241 → 5 statements for 60 games). Settings no longer hydrates
  the entire history twice. Players uses one `GROUP BY`.
- **Catalogue sync gating.** Was 119 upserts on every connect, in the critical
  path of every cold start. Now hashes the source JSON and skips when unchanged
  (128 → 6 statements on a warm connect). Also requires the catalogue tables to
  be non-empty, so a future migration rebuilding either table cannot leave it
  empty forever with the hash still matching.
- **Passphrase gate** (`wingspan/auth.py`) — stopgap until phase 1 brings real
  cookie auth. No-op unless `WINGSPAN_PASSPHRASE` is set.

## Deliberately NOT done

These were identified as real but live in files the rewrite deletes, so fixing
them would be throwaway work. Recorded so the analysis is not repeated:

- **`st.tabs` renders all four tab bodies on every run** (`views/insights.py`).
  All ~12 charts are computed and serialised to the browser to display one.
  Worth ~20 minutes *only* if the current app has to be lived with for a while.
- **No `@st.cache_data`** on the three dataframe loads in `views/insights.py`.
- **`_roster()` in `views/enter_scores.py`** runs a full `SELECT * FROM players`
  on every `player_name()` / `player_color()` call — dozens per rerun.
- **No `.streamlit/config.toml`** — no theme, and the header is hidden with CSS
  rather than `toolbarMode = "minimal"`.

## Open questions

- **Which devices actually matter?** Assumed "phone-first" throughout (the
  codebase is explicit about it), but the single iOS reference in the repo is one
  defensive CSS comment at `app.py:17-18`, not evidence of the owner's device.
  Android Chrome and iOS Safari differ substantially on PWA install and service
  worker support.
- **Is `auto_stop_machines = 'suspend'` actually suspending**, or silently
  falling back to a full stop? Suspend has conditions attached.
- **Are the 30s health checks holding the machine awake?** If so, the deployment
  is already paying for 24/7 without getting the benefit.
- **Are Fly volume snapshots enabled?** The only backup today is the manual CSV
  export in Settings. One volume, one machine.
