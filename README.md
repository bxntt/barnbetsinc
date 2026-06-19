# Best Bets · Hard Rock

An agent that finds **+EV ("value") bets at Hard Rock Bet** — the only legal mobile
sportsbook in Florida — and publishes a ranked, mobile-friendly list with a shareable
URL. For each bet it shows **how much edge** you have and **why**.

> **Informational only. Not financial advice. 21+ where legal.** Sportsbooks
> (Hard Rock/Kambi included) may limit accounts that consistently bet value.

---

## The strategy in one paragraph

You can't shop lines or arbitrage with a single book, but you *can* tell when that book
is **mispricing** a bet. The agent pulls odds for each game from a free odds API —
including **Hard Rock** and a **sharp reference** (Pinnacle, or a consensus of other
books) — and removes the vig from the sharp line to get the **true win probability**.
If Hard Rock pays *more* than that true probability justifies, it's a **+EV bet**:

```
fair_prob = de-vig(sharp odds)              # the "real" chance the bet wins
EV%       = fair_prob * hardrock_decimal − 1
recommend if EV% ≥ min_ev_pct (default 2%)
```

Each pick is weighted by **confidence** (tighter sharp markets and games not starting
imminently score higher) and annotated with **line movement** and a **closing-line-value
(CLV)** track record — the long-run proof that the picks are genuinely good.

## What it is / isn't doing

| Edge | Status | Why |
|---|---|---|
| **+EV vs sharp market** | ✅ core engine | Works with one book; the real long-term edge |
| Line movement / steam | ✅ confirming signal | Built from committed odds snapshots |
| Closing line value (CLV) | ✅ track record | Grades past picks vs the closing line |
| Injury / weather context | ⚙️ optional (off by default) | ESPN + Open-Meteo, best-effort |
| Arbitrage / line shopping | ❌ not possible | Require multiple books; Florida = Hard Rock only |
| Fade-the-public (bet%/money%) | ❌ dropped | No cheap programmatic splits API (see below) |

---

## Quickstart (no API key needed)

```bash
pip install -r requirements.txt
python -m agent.pipeline          # uses the bundled mock data -> writes site/data.json
cd site && python -m http.server  # open http://localhost:8000 on desktop or phone
```

The mock slate includes planted +EV bets so you can see the full thing working offline.

## Switching to real Hard Rock odds

1. Get a free key: **[The Odds API](https://the-odds-api.com)** (recommended — verified
   schema, Hard Rock is in the `us` region) or **[odds-api.io](https://odds-api.io)**
   (more generous rate limit; its adapter is best-effort, verify against your account).
2. Copy `.env.example` → `.env` and paste your key.
3. In `config.yaml` set `provider: the_odds_api` (or `odds_api_io`).
4. `python -m agent.pipeline`

Key `config.yaml` knobs: `min_ev_pct` (edge threshold), `sports`, `markets`,
`sharp_books` (reference priority), `the_odds_api_regions` (`us,eu` includes Pinnacle —
costs more credits), `confidence`, `max_published`.

## Deploy to GitHub Pages (shareable URL)

1. Push this repo to GitHub.
2. **Settings → Pages → Source: GitHub Actions**.
3. (Optional, for real data) **Settings → Secrets → Actions** → add `THE_ODDS_API_KEY`.
4. **Actions → "Update best bets & deploy" → Run workflow.** Your site is at
   `https://<user>.github.io/<repo>/`. The workflow then re-runs on a cron (default every
   3h — tune the schedule in [.github/workflows/update.yml](.github/workflows/update.yml)
   to fit your API's free-tier budget).

---

## How it works (layout)

```
agent/
  config.py              # config.yaml + .env loader
  models.py              # Game / BookOdds / Outcome / BestBet
  odds_math.py           # American <-> decimal <-> implied probability
  providers/             # mock (default) | the_odds_api | odds_api_io
  engine/
    devig.py             # no-vig fair line from sharp ref or consensus
    ev.py                # EV% + confidence per Hard Rock outcome
    movement.py          # line movement from snapshot history
    clv.py               # closing-line-value track record
  context/               # espn (injuries), weather (Open-Meteo) — optional
  store.py               # odds snapshots + recommendation log in data/history/
  rank.py                # confidence-weighted ranking + plain-English "why"
  pipeline.py            # fetch -> de-vig -> EV -> rank -> publish
site/                    # mobile-first static site (reads data.json)
tests/test_engine.py     # odds math, de-vig, EV, ranking
```

Run the tests with `pytest`.

---

## Data-source research (2026) — why +EV, not fade-the-public

The original idea was "fade the public," which needs **public bet% + money% (handle)**.
That data has no cheap programmatic source:

- **Split Labs** — $14.99/mo, shows both %s, but **dashboard-only (no API)**.
- **SportsDataIO** — real API with both %s, but **sales-gated (~4-figure/yr)**.
- **Sportradar** — gold standard, **enterprise / licensed-operator only**.
- Scraping Action Network / Covers / VSiN violates their ToS — excluded.

Meanwhile, **free odds APIs** (The Odds API, odds-api.io) include **Hard Rock + sharp
reference books**, which is exactly what +EV detection needs. So the project pivoted to
the edge that's both *more reliable* and *actually fundable on free data*.
