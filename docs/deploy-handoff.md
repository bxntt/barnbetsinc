# Deploy handoff — one-page redesign + Justification page

For the future "push everything live" session. Covers the site UI work done on
2026-06-19: merging the two tabs into one page, adding the Justification page,
and the parallel Injuries page. Code is committed; the only thing between here
and a live site is triggering (and verifying) the Pages deploy.

## Status

On `main`, already pushed:

| commit | what |
| --- | --- |
| `5cab779` | Merge picks into one page; add Justification page |
| `4dd55c2` | World Cup: add per-game injuries/availability page (parallel session) |

- All 52 tests pass; `python -m agent.worldcup.pipeline` runs clean end-to-end.
- Working tree clean as of this doc.

## What's already done (no action needed)

- `site/index.html` — the World Cup / Hard Rock **tabs are gone**; one scrolling
  page with three sections: WC predictions (compact `market · pick · %` lines),
  who-advances table (`team · pts · advance%`), Hard Rock +EV bets
  (`label · edge · price · % to hit`). Rationale text, confidence bars, and tag
  rows were removed to cut clutter.
- `site/justification.html` + `justification.js` — methodology blurb + per-pick
  "how we got here" summaries, read from the same JSON feeds (auto-syncs).
- `site/common.js` — shared fetch/format helpers used by every page.
- `site/app.js`, `site/styles.css` — rewritten for the merged layout.
- Injuries page (`injuries.html/js`, `agent/worldcup/injuries.py`) bundled;
  `site/injuries.json` generated (16 absences across 14/43 games).

## What's left to make it live

1. **Trigger the deploy.** The Pages workflow does **NOT** run on `push` — only
   on `schedule` (cron `*/15`) and `workflow_dispatch`. So pushing alone does
   nothing visible. Either:
   - wait for the next 15-min cron tick (it regenerates JSON and deploys), or
   - Actions tab → **"Update best bets & deploy"** → *Run workflow* for an
     immediate deploy.
2. **Confirm the CI run is green.** The job runs `python -m agent.pipeline`,
   which now also runs the worldcup pipeline → regenerates `worldcup.json` +
   `injuries.json`. If any parallel-session wiring (`agent/config.py`,
   `agent/worldcup/pipeline.py`, `injuries.py`, `config.yaml`) is broken, the
   deploy step is skipped and nothing publishes — check the Actions log.
3. **Verify the live site** (bxntt.github.io/barnbetsinc):
   - [ ] `index.html` is one page, three sections, no leftover tab toggle.
   - [ ] Nav links Picks / Injuries / Justification all load (no 404).
   - [ ] Justification page shows rationales for both WC and Hard Rock.
   - [ ] Injuries page populates (depends on `injuries.json` in the artifact).
   - [ ] Mobile width (≤620px) looks clean.
   - [ ] No browser/visual check has been done yet — data contracts, JS syntax,
         and the pipeline run were verified, but nobody has opened it in a browser.

## Coordination for the consolidation push

- **`git pull --rebase` before pushing** — several sessions are committing to
  `main`.
- **Conflict hot-spots** (more than one session edits these):
  - `site/styles.css` — rewritten here; injuries CSS appended. Keep both.
  - `site/index.html` nav block — three links (Picks / Injuries / Justification).
  - `site/common.js` — new shared helpers; keep a single copy.
- **Let CI own the generated JSON.** Don't hand-resolve conflicts in
  `site/data.json`, `site/worldcup.json`, `site/injuries.json`, or
  `data/history/*`. Take either side — the next pipeline tick overwrites them.

## Notes

- `site/injuries.json` is regenerated every CI tick; the committed copy is just a
  seed so the page isn't empty before the first deploy.
- The pipeline only spends odds credits inside a match window. The last local run
  cost 2 credits (474 remaining); model-only ticks are free.
