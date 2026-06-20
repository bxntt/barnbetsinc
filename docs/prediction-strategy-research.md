# Bet outcome prediction strategy — research notes

Audience: future Claude session. Dense over pretty. Links are file paths.

## Current architecture (what exists)
System is a **prediction engine**: for each game it estimates the probability of
every outcome per market and publishes the most likely call, ranked by probability.
It does NOT shop price or chase +EV — market odds enter only as a de-vigged consensus
*input* to the model.

Flow: build team-strength model from results history -> de-vig each book into a no-vig
consensus -> blend (model-first) -> per-market most-likely call + plain-English "why".
- ratings: agent/engine/ratings.py (team strength from results; config strategy.model_min_games)
- de-vig consensus: agent/engine/devig.py (power default, shin, multiplicative; config.yaml strategy.devig_method; weighted by strategy.book_weights)
- blend + per-market prediction + rationale: agent/engine/predict.py (model-first, capped by strategy.max_market_weight)
- calibration + Brier: agent/engine/calibration.py
- final scores (feed the model + calibration): agent/engine/results.py (ESPN)
- World Cup outcome model: agent/worldcup/poisson.py (indep Poisson fit to market 1X2)
  + agent/worldcup/simulate.py (Monte Carlo group stage, FIFA tiebreakers)
- free context: agent/context/espn.py (injuries/headlines), agent/context/weather.py
  (Open-Meteo, OFF: config.yaml context.weather=false)
- config: config.yaml

## Core thesis
The de-vigged market consensus is a strong public predictor of outcomes; an amateur
model rarely beats it outright. So the design is a **model-first blend**, not a
from-scratch "beat the market" model:
  Layer 1 PRIOR  = team-strength model from results (HAVE IT)
  Layer 2 BLEND  = de-vigged market consensus, capped so it can't fully override (HAVE IT)
  Layer 3 ADJUST = cheap independent signals where the market is slow/soft (THE GAP)
Layers 1 & 2 exist. Opportunity = Layer 3 + the calibration measurement loop.

## Per-market: each bet type needs a DIFFERENT object
- Moneyline (A wins): win probability. HAVE (model + consensus blend).
- Spread (cover): needs a MARGIN DISTRIBUTION, not a win prob. Only have consensus + blend.
- Totals (O/U): needs a TOTAL-POINTS DISTRIBUTION. Only have consensus.
- Draw (soccer): P(draw) structurally UNDERSTATED by indep Poisson (noted poisson.py:8)
  -> currently underpredicting draws.

To predict covers/totals from the model independently (not just echo the line),
convert team strength to distributions:
- Spread: model margin -> P(cover)=Phi((exp_margin-line)/sigma).
  sport sigma approx: NFL 13.5, NBA 11-12. Respect key numbers (NFL 3 and 7 ~ 1.5-2 pts).
- Totals: market line is a strong prior; cheap free nudges = weather (wind/rain depress
  NFL+MLB overs), NBA pace/possessions, MLB starting pitcher, star scorer out.
- Draw: add Dixon-Coles low-score correction (lifts 0-0/1-1/1-0).

## Layer 3 signals ranked by accuracy-per-effort (all free; user is cost-lean)
1. Injuries/lineups/rest — slowest market input; ESPN already wired (context/espn.py).
   Rest/B2B/travel derivable from schedule already pulled = 0 new API cost.
2. Weather for outdoor totals — flip config.yaml context.weather=true.
3. Independent margin/total models — more work, lower marginal value (fights the
   consensus). Use to nudge the blend, not to replace it.

## Measurement loop (how to know predictions are good)
- Calibration/Brier = ground truth (calibration.py): do the stated probabilities match
  realized hit rates? Needs a few hundred graded predictions to separate skill from
  variance. OPTIMIZE THIS — it's the honest signal that the blend is well-tuned.
- Loop: predict -> grade vs results -> calibration by sport/market over time -> feed
  that back into how much the model vs consensus is trusted per sport.

## Research update 2026-06-20 (literature-backed; sources at bottom)
Web-research pass to pressure-test the plan above. Findings that confirm or change it:

### Accuracy ceilings — set honest expectations [S1][S2][S3]
- Soccer 1X2 outcome accuracy tops out ~52-56% even for strong models — that's near the
  practical ceiling, not a failure. Best-in-class = gradient-boosted trees (CatBoost /
  XGBoost) fed RATING features (Elo / pi- / Berrar): CatBoost + pi-ratings ≈ 55.8% acc,
  0.1925 RPS, beating plain Poisson/Weibull (~48.5%) and the 2017 Soccer Prediction
  Challenge field. Takeaway: the rating features matter more than the algorithm.
- The de-vigged market is *very* hard to beat [S2][S6]. xG + Skellam + isotonic models
  only MATCH or slightly beat market forecasts, and the market usually wins on Brier.
  => CONFIRMS the model-first-but-market-anchored design. Goal is not to "beat" consensus
  but to MATCH it while staying independently explainable and well-calibrated.
- Cost-lean implication: a full GBM stack is heavier infra AND needs a labeled history we
  don't have yet. Keep the closed-form Elo+Poisson core now; treat GBM as a LATER upgrade,
  only after the calibration loop has banked a few hundred graded games to train/validate.

### Use the RIGHT scoring metric per market [S2][S7]
- Binary markets (ML / spread cover / total O/U): Brier + a reliability curve (predicted
  vs realized by bin). engine/calibration.py already does exactly this — KEEP.
- 3-way 1X2 (World Cup result): Brier is the wrong shape. Use **RPS** (ordinal-aware: a
  home-win call landing on a draw is "less wrong" than one landing on an away win) and/or
  **log loss / ignorance**. Live debate: some work argues log-loss beats RPS — so report
  BOTH for 1X2 and don't over-index on one. GAP: WC predictions are graded NOWHERE today
  (calibration.py is US-engine only). Add an RPS+log-loss grading loop for worldcup/.

### Calibrate, don't just measure [S2][S8]
- Once ~a few hundred graded predictions exist, fit a post-hoc calibrator and apply it to
  FUTURE probs: **isotonic regression** (non-parametric; most consistently improves, but
  overfits small n) or **Platt/logistic scaling** (safer on small n, can help or hurt).
  Plan: Platt while n is small, switch to isotonic once each (sport,market) bin is dense.
  Plugs straight onto calibration.py — its reliability bins are already what a calibrator
  consumes. This is the one change that most directly improves "what are the real chances."

### Dixon-Coles fixes the known draw underprediction (WC) [S4]
- Confirmed: independent Poisson understates low-score draws (poisson.py:9-10). Fix = the
  Dixon-Coles ρ correction on the four low scorelines (0-0,1-0,0-1,1-1); ρ typically ≈
  −0.03 to −0.10 (negative lifts 0-0 & 1-1, trims 1-0 & 0-1). Apply ρ as a multiplier on
  those four cells of poisson.score_matrix() before re-normalizing — tiny, local, no new
  data. Pair with **time-decay weighting** (recency half-life ≈ 45 days) when ratings are
  refit from results so current form outweighs stale results.

### Margin/total distributions — confirmed σ and key numbers (US spreads/totals) [S5]
- Margin ≈ Normal(mean = model/line, σ): NFL σ ≈ 13.5 (hist. 13.86), NBA σ ≈ 12.
  predict.py already uses sigma_margin/sigma_total — verify the ratings.py constants match.
- KEY NUMBERS: a pure Normal misprices NFL margins at 3 and 7. Better = model each key
  number as its own mass and mix with the Normal ("mixed" distribution). Cheap interim:
  bump probability mass at ±3 / ±7 with hand-tuned key-number weights. Totals' key numbers
  are weaker — plain Normal is fine there.

### Layer-3 schedule signals are free AND quantified (NBA especially) [S9]
- Second night of a back-to-back: teams win less, shoot worse, turn it over more — ≈ 3-5%
  perf drop, rising to **5-7%** on a coast-to-coast B2B. Travel direction is asymmetric
  (east-bound ~44.5% win vs west-bound ~40.8%); altitude (Denver, Utah) compounds fatigue.
  ALL derivable from the schedule we already pull => $0 new API. Best accuracy-per-dollar
  Layer-3 add for the US engine. Injuries/lineups already wired (context/espn.py,
  worldcup/factors.py); weather is one config flip for outdoor totals.

## The plan (prioritized; cost-lean; mapped to code + the tools we have)
Tools available to execute this: the existing Python engine + GitHub Actions cron (the
predict→grade→publish loop already runs free on a public repo); free data already wired
(odds /events, ESPN finals + injuries, Open-Meteo); WebSearch/WebFetch for one-off
research, σ/key-number constants, and host/venue facts (NOT for per-tick scraping — keep
the cron cheap). No paid ML infra. Ordered by accuracy-per-effort:

1. **Close the measurement loop first — it's the prerequisite for everything else.**
   a. [DONE 2026-06-20] agent/worldcup/calibration.py — grades the 1X2 result with
      **RPS + log loss** and total/btts/handicap with **Brier + reliability bins**.
      Logs every published call to data/history/worldcup_predictions.jsonl (de-duped
      by match+market, latest pre-kickoff wins); finals come FREE from ESPN's soccer
      scoreboard (espn_results, no key, fail-safe). Wired into worldcup/pipeline.py
      (live provider only) -> site/worldcup_calibration.json. grade() is a pure fn
      over the two logs. NEXT: it has no graded games until group results settle —
      let it bank a few hundred, then do step 2 (calibrator) and re-tune the
      factors.py weights / Dixon-Coles rho against RPS instead of by judgement.
   b. Keep banking graded US predictions (already happens via store.py → calibration.py).
   Why first: every later change (blend weights, calibrator, GBM) needs this ground truth.

2. **Add a post-hoc calibrator** (engine/calibration.py + a new apply step in predict.py):
   Platt now, isotonic once each (sport,market) bin is dense. Biggest direct lift to "real
   chances" honesty. Cheap; pure-Python; no new data.

3. **Dixon-Coles ρ + time-decay weighting in worldcup/** (poisson.score_matrix + ratings
   refit). Fixes the known draw understatement; ~20 lines; no new data.
   [DONE 2026-06-20] Dixon-Coles ρ=−0.06 lives in poisson.score_matrix (_dc_tau on the
   four low-score cells + renormalize; pass rho=0.0 for the plain grid). Flows into
   every grid-derived WC market (result/draw/btts/totals/handicap). NOTE: time-decay
   is N/A for WC — its ratings are a hand-maintained prior + standings form, not refit
   from results; time-decay applies to the US engine (engine/ratings.py from results).
   Also: the group Monte-Carlo (simulate.py) still samples each team independently via
   goal_cdf, so DC only reshapes the per-match published grid, not the sim draws.

4. **Model → margin/total distributions with key-number mass for US spreads/totals**
   (predict.py + ratings.py). Verify σ ≈ NFL 13.5 / NBA 12; add ±3/±7 key-number bumps.
   Biggest jump in WHAT can be predicted independently rather than echoing the line.

5. **Free Layer-3 schedule signals for the US engine** (new module like worldcup/factors.py,
   reusing the already-pulled schedule): rest days, back-to-back (esp. coast-to-coast),
   travel direction, altitude → small win-prob / pace nudges. $0 API. Flip weather on for
   outdoor totals at the same time.

6. **Wire calibration-by-(sport,market) back into the blend weight** (strategy.max_market_weight
   per segment): auto-trust the model more where it has been more accurate, the consensus
   more where it hasn't. Needs the loop from step 1 to have data. A principled successor:
   learn the model↔market blend as a small logistic stack on graded history.

7. **(Later, only after steps 1–2 bank a few hundred graded games)** evaluate a GBM
   (CatBoost/XGBoost) on rating features as a drop-in for the closed-form prior. Highest
   ceiling per the literature, but heaviest infra and data-hungry — deferred on purpose.

Status (2026-06-20): steps 1a (WC grading loop) and 3 (Dixon-Coles ρ) are DONE; the
Layer-3 injury/momentum/host signals are live in worldcup/factors.py. Remaining: step 2
(post-hoc calibrator, once grading banks data), steps 4–5 (US-sports margin/total
distributions + free schedule signals), and steps 6–7 (calibration→blend weighting, then
a GBM). All consistent with the core principle: predict likelihood, never shop odds/value
(market consensus stays a blend input).

## Sources
- [S1] Soccer ML review (techniques/accuracy ceilings): https://arxiv.org/pdf/2410.21484
- [S2] Wilkens, simple models vs Bundesliga odds (Brier/log-loss, market hard to beat):
  https://journals.sagepub.com/doi/10.1177/22150218261416681
- [S3] CatBoost + pi-ratings, RPS, GBT feature optimization: https://arxiv.org/html/2309.14807
- [S4] Dixon-Coles ρ low-score correction + time decay: https://dashee87.github.io/football/python/predicting-football-results-with-statistical-modelling-dixon-coles-and-time-weighting/
- [S5] NFL/NBA margin σ + key numbers: https://www.boydsbets.com/ats-margin-standard-deviations-by-point-spread/
  and key-number mixture: https://www.nfeloapp.com/analysis/margin-probabilities-from-nfl-spreads/
- [S6] Forecasting soccer with betting odds (two markets): https://www.sciencedirect.com/science/article/pii/S0169207024000670
- [S7] Case against RPS (use log loss/ignorance too): https://arxiv.org/abs/1908.08980
- [S8] sklearn probability calibration (isotonic vs Platt): https://scikit-learn.org/stable/auto_examples/calibration/plot_calibration_curve.html
- [S9] NBA rest/B2B/travel effect sizes: https://www.nbastuffer.com/rest-days-factor-nba-scheduling/
  and https://playdecoded.com/explainers/nba-back-to-back-games
