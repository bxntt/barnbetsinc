# Barn Betting Inc.

A mobile-first site with **two sections**, served from one shareable URL:

1. **🏀 US sports** — for every game, **predicts the most likely outcome** in each
   market (moneyline / spread / total) from a team-strength model blended with the
   market consensus.
2. **⚽ World Cup** — model-driven **per-game predictions** (result / total / both-
   teams-to-score / handicap) plus a Monte-Carlo **group-stage simulator** for the
   2026 tournament.

Both sides answer the same question — *what is most likely to happen?* — and rank
their calls by probability. No single sportsbook is judged and no price is "shopped."

> **Informational only. Not financial advice. 21+ where legal.** Predictions are
> estimates, not certainties.

---

## How the prediction works

For each game we estimate the probability of every outcome, then publish the most
likely call per market:

```
model_prob   = team-strength ratings, built from recent results / standings + form
market_prob  = de-vig each book, then average across books -> no-vig consensus
prob         = blend(model_prob, market_prob)   # model-first; consensus is one input
```

The blend is **model-first**: the market consensus can only pull the estimate so far
(`max_market_weight`), and until a team has been seen enough times (`model_min_games`)
that game leans more on the consensus. A **calibration loop** grades past predictions
against final results so we can see whether the probabilities actually hold up.

## What it is / isn't doing

| | Status | Why |
|---|---|---|
| **Per-market outcome prediction** | ✅ core | Most-likely call per game, ranked by probability |
| De-vigged market consensus | ✅ one input | The market's no-vig view, blended into the model |
| Probability calibration | ✅ honesty check | Grades predicted vs realized hit rate |
| Injury / weather context | ⚙️ optional | ESPN + Open-Meteo, best-effort |
| +EV / value / line-shopping | ❌ not done | We predict likelihood, not price value |

---

## Quickstart (no API key needed)

```bash
pip install -r requirements.txt
python -m agent.pipeline   # bundled mock data -> writes site/data.json AND site/worldcup.json
python3 serve.py           # serves site/ at http://localhost:8000 (add --open to launch a browser)
```

`serve.py` is a zero-dependency wrapper around `http.server`: it serves the
`site/` folder from anywhere in the repo, falls back to the next free port if
8000 is taken, and warns when the generated data files are missing. The site
loads its data with `fetch()`, so it must be served over HTTP — opening the
files straight from disk (`file://`) will block data loading. (`cd site &&
python -m http.server` works too.)

The bundled `mock` slate covers a handful of US games and a full 12-group World Cup
field, so both sections of the site work offline with no API key. To run just one side:

```bash
python -m agent.worldcup.pipeline   # World Cup only -> site/worldcup.json
```

## Switching to real odds

1. Get a free key: **[The Odds API](https://the-odds-api.com)** (recommended — verified
   schema) or **[odds-api.io](https://odds-api.io)** (more generous rate limit; its
   adapter is best-effort, verify against your account).
2. Copy `.env.example` → `.env` and paste your key.
3. In `config.yaml` set `provider: the_odds_api` (or `odds_api_io`).
4. `python -m agent.pipeline`

Key `config.yaml` knobs: `sports`, `markets`, `the_odds_api_regions`, the `strategy`
block (`devig_method`, `book_weights`, `max_market_weight`, `model_min_games`,
`calibration_enabled`), and `max_published`.

## Deploy to GitHub Pages (shareable URL)

1. Push this repo to GitHub.
2. **Settings → Pages → Source: GitHub Actions**.
3. (Optional, for real data) **Settings → Secrets → Actions** → add `THE_ODDS_API_KEY`.
4. **Actions → "Update predictions & deploy" → Run workflow.** Your site is at
   `https://<user>.github.io/<repo>/`. The workflow then re-runs on a cron (default every
   15 min — most ticks cost 0 credits; the budget gate only pays for an odds poll inside
   a World Cup match window). Tune the schedule in
   [.github/workflows/update.yml](.github/workflows/update.yml).

---

## World Cup section

The World Cup side predicts each game from a model of the teams and adds a group-stage
simulator:

| Tool | What it answers |
|---|---|
| **Match predictions** | Most likely **result / total / BTTS / handicap** per game, each with a probability. |
| **Group simulator** | Each team's chance to **win its group** and to **advance** (2026: top 2 + 8 best thirds → Round of 32). |

How it works:

```
predict:  team-strength ratings (+ live form) -> goal expectancies -> per-market
          probabilities, blended with the no-vig market consensus when odds exist
sim:      each unplayed match's goal expectancies -> Monte-Carlo scorelines ->
          group tables (points, GD, GF tiebreakers) -> P(win group) / P(advance)
```

Played matches use their real scoreline, so projections sharpen through the group
stage. Knobs live under `worldcup:` in `config.yaml` (`provider`, `markets`, `sims`,
`seed`). The bundled `mock` provider powers both the predictor and simulator with no
key; `the_odds_api` gives live odds that sharpen the prediction blend.

## How it works (layout)

```
agent/
  config.py              # config.yaml + .env loader (incl. worldcup block)
  models.py              # Game / BookOdds / Outcome / Prediction
  odds_math.py           # American <-> decimal <-> implied probability
  budget.py              # free-tier credit gate / poll throttle
  providers/             # mock (default) | the_odds_api | odds_api_io
  engine/                # US-sports predictor
    ratings.py           # team-strength model from results history
    devig.py             # no-vig consensus probability across books
    predict.py           # per-game, per-market most-likely call + "why"
    results.py           # final scores (feeds the model + calibration)
    calibration.py       # predicted vs realized hit-rate check
  context/               # espn (injuries), weather (Open-Meteo) — optional
  worldcup/              # model-driven World Cup predictor + simulator
    ratings.py           # team strength priors, form-adjusted
    devig.py             # N-way (1X2) no-vig consensus across all books
    poisson.py           # goal expectancies from a 1X2 line; sample scorelines
    predict.py           # per-game calls for every market
    simulate.py          # Monte-Carlo group-stage simulator (2026 format)
    provider.py          # mock 12-group field | the_odds_api soccer odds
    injuries.py          # who's expected out, by game (site/injuries.json)
    pipeline.py          # fetch -> predict + simulate -> site/worldcup.json
  store.py               # odds snapshots + prediction log in data/history/
  rank.py                # probability ranking + plain-English "why"
  publish.py             # serialize predictions -> site/data.json
  pipeline.py            # US-sports run; also triggers the World Cup run
site/                    # mobile-first static site; reads data.json + worldcup.json
tests/                   # test_engine / test_strategy / test_worldcup / test_budget
```

Run the tests with `pytest`.
