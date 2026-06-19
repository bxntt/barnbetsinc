"""Model-driven World Cup predictor.

Unlike the Hard Rock engine (which judges *one* book against a sharp reference),
this side predicts *what will happen* in each game from a model of the teams, and
only uses the market as one more input:

  * `ratings`    — team strength priors, form-adjusted from the live standings.
  * `predict`    — per-game calls for every bet type (result / total / both-teams-
                   to-score / handicap), each with a probability of hitting. The
                   probability is the team-strength model blended with the no-vig
                   market consensus when odds are available.
  * `simulate`   — a Monte Carlo of the group stage (2026 48-team / 12-group
                   format): each team's chance to win its group and to advance,
                   driven by the same model (sharpened by market odds where quoted).

The question is "what is most likely to happen", not "which book is mispricing
this" — the schedule (and so the predictions) comes free from the /events feed,
and paid odds polls only sharpen the blend.
"""
