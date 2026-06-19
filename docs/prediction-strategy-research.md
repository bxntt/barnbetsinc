# Bet outcome prediction strategy — research notes

Audience: future Claude session. Dense over pretty. Links are file paths.

## Current architecture (what exists)
System is a VALUE engine, not a prediction engine. It answers "where is Hard Rock
mispriced vs sharp consensus", NOT "what will happen". The de-vigged sharp prob IS
the prediction.

Flow: de-vig sharp books (pinnacle/circa/betonlineag) -> fair prob -> EV gate at
target book (hardrockbet).
- de-vig: agent/engine/devig.py (power default, shin, multiplicative; config.yaml strategy.devig_method)
- EV gate + confidence multiplier: agent/engine/ev.py (evaluate_game; _confidence at :44; EV at :151)
- interpolation for off-number spreads/totals: agent/engine/interpolate.py
- Kelly sizing: agent/engine/kelly.py (quarter-kelly, capped, config strategy.kelly_*)
- Elo cross-check (h2h ONLY, flags disagreement, does not size): agent/engine/elo.py
- calibration + Brier: agent/engine/calibration.py
- CLV (closing line value): agent/engine/clv.py (by-sport breakout)
- line movement / steam: agent/engine/movement.py (target move + sharp ref_probs move)
- World Cup outcome model: agent/worldcup/poisson.py (indep Poisson fit to market 1X2)
  + agent/worldcup/simulate.py (Monte Carlo group stage, FIFA tiebreakers)
- free context: agent/context/espn.py (injuries/headlines), agent/context/weather.py
  (Open-Meteo, OFF: config.yaml context.weather=false), agent/engine/results.py (ESPN final scores)
- config: config.yaml

## Core thesis
Sharp CLOSING line is the best public predictor of outcomes. Amateur models lose
to it. Do NOT build a from-scratch model to "beat the market". Instead: 3-layer hybrid.
  Layer 1 PRIOR  = de-vigged sharp consensus (HAVE IT)
  Layer 2 ADJUST = cheap independent signals ONLY where market is slow/soft (THE GAP)
  Layer 3 GATE   = EV + Kelly + confidence (HAVE IT)
Layers 1 & 3 exist. Opportunity = Layer 2 + the measurement loop.

## Per-market: each bet type needs a DIFFERENT object
- Moneyline (A wins): win prob. HAVE (de-vig + Elo flag).
- Spread (cover): needs a MARGIN DISTRIBUTION, not win prob. Only have de-vig+interp.
- Totals (O/U): needs a TOTAL-POINTS DISTRIBUTION. Only have de-vig.
- Draw (soccer): P(draw) structurally UNDERSTATED by indep Poisson (noted poisson.py:8)
  -> currently underpricing every draw bet.

Elo gap today outputs only win prob (elo.py:40). To predict covers/totals
independently, convert to distributions:
- Spread: Elo gap -> expected margin; P(cover)=Phi((exp_margin-line)/sigma).
  sport sigma approx: NFL 13.5, NBA 11-12. Respect key numbers (NFL 3 and 7 ~ 1.5-2 pts).
- Totals: market line is strong prior; cheap free nudges = weather (wind/rain depress
  NFL+MLB overs), NBA pace/possessions, MLB starting pitcher, star scorer out.
- Draw: add Dixon-Coles low-score correction (lifts 0-0/1-1/1-0).

## Layer 2 signals ranked by ROI-per-effort (all free; user is cost-lean)
1. Injuries/lineups/rest — slowest market input; ESPN already wired (context/espn.py).
   Rest/B2B/travel derivable from schedule already pulled = 0 new API cost.
2. Steam confirmation — movement.py already computes sharp ref_probs movement. Best spot:
   sharp moved toward a side, Hard Rock hasn't followed. Use as a FILTER (only take
   value sharps also moving toward) -> raises hit rate.
3. Weather for outdoor totals — flip config.yaml context.weather=true.
4. Independent Elo margin/total models — more work, lower marginal value (fights the
   close). Use to FLAG disagreement, not to size.

## Measurement loop (how to know predictions are good WITHOUT waiting for results)
- CLV = leading indicator (clv.py). Consistently beating close => genuinely +EV before
  any game graded. Already by-sport. OPTIMIZE THIS.
- Calibration/Brier = lagging ground truth (calibration.py). ~500+ bets to separate
  skill from variance.
- Loop: predict -> CLV check -> calibration over time -> feed CLV-by-sport back into the
  confidence multiplier in ev.py so engine auto-trusts markets/sports where it's been right.

## Recommended next steps (cheap; pick one)
1. Elo -> margin/total distributions (biggest jump in WHAT can be predicted: spreads+totals).
2. Turn on weather + totals pace/lineup nudge (one config flip + small module).
3. Dixon-Coles draw correction in worldcup poisson (fixes known underprice).
4. Wire CLV-by-sport into confidence weight in ev.py (biggest PROCESS upside; makes
   every other prediction self-correcting/trustworthy). RECOMMENDED FIRST.

Recommend #4 first (makes everything honest) or #1 (biggest predictive expansion).
No code written yet as of this doc — this is strategy only.
