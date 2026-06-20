"""Model-driven World Cup predictor.

Like the US-sports side, this predicts *what will happen* in each game from a model
of the teams, and only uses the market as one more input:

  * `ratings`    — team strength priors, form-adjusted from the live standings.
  * `factors`    — match-context signals (injuries, attacking/defensive momentum,
                   host-nation venue) folded into the goal model as goal-rate tilts.
  * `predict`    — per-game calls for every bet type (result / total / both-teams-
                   to-score / handicap), each with a probability of hitting. The
                   probability is the team-strength model (injury/form/venue
                   adjusted) blended with the no-vig market consensus when odds are
                   available. Low-score draws are Dixon-Coles corrected (`poisson`).
  * `simulate`   — a Monte Carlo of the group stage (2026 48-team / 12-group
                   format): each team's chance to win its group and to advance,
                   driven by the same model (sharpened by market odds where quoted).
  * `calibration`— grades published calls against free ESPN finals (RPS + log loss
                   for the 3-way result, Brier for the binary markets) so the engine
                   is measured, not just asserted.

The question is "what is most likely to happen", not "which book is mispricing
this" — the schedule (and so the predictions) comes free from the /events feed,
and paid odds polls only sharpen the blend.
"""
