"use strict";

/* Justification page: the per-pick "how we got here", pulled from the same
   JSON feeds as the picks page so it stays in sync automatically. */

const MARKET_LABEL = {
  // World Cup
  result: "Result",
  total: "Total",
  btts: "BTTS",
  handicap: "Handicap",
  // US sports
  h2h: "Moneyline",
  spreads: "Spread",
  totals: "Total",
};

// Expand the "BTTS:" prefix on the bold pick text into full words.
function pickLabel(pick) {
  return String(pick).replace(/^BTTS:/, "Both Teams to Score:");
}

async function load() {
  const [hr, wc] = await Promise.allSettled([
    fetchJson("data.json"),
    fetchJson("worldcup.json"),
  ]);

  if (wc.status === "fulfilled") {
    renderWcWhy(wc.value.predictions || []);
  } else {
    document.getElementById("wcWhy").innerHTML = loadError(wc.reason, "agent.worldcup.pipeline");
  }

  if (hr.status === "fulfilled") {
    renderUsWhy(hr.value.predictions || []);
  } else {
    document.getElementById("usWhy").innerHTML = loadError(hr.reason, "agent.pipeline");
  }
}

function renderWcWhy(preds) {
  const el = document.getElementById("wcWhy");
  if (!preds.length) {
    el.innerHTML = `<div class="empty">No predictions to explain yet.</div>`;
    return;
  }
  const byGame = new Map();
  for (const p of preds) {
    if (!byGame.has(p.match_id)) byGame.set(p.match_id, []);
    byGame.get(p.match_id).push(p);
  }
  // Order games chronologically by kickoff (matches the picks page).
  el.innerHTML = Array.from(byGame.values())
    .sort((a, b) => new Date(a[0].commence_time) - new Date(b[0].commence_time))
    .map((calls) => {
      const g = calls[0];
      const rows = calls
        .slice()
        .sort((a, b) => b.prob - a.prob)
        .map(
          (p) => `
        <div class="why-row">
          <div class="why-head">
            <span class="line-mkt">${MARKET_LABEL[p.market] || escapeHtml(p.market)}</span>
            <span class="line-pick">${escapeHtml(pickLabel(p.pick))}</span>
            <span class="line-pct ${p.prob_pct >= 60 ? "p-strong" : p.prob_pct >= 45 ? "p-good" : "p-lean"}">${p.prob_pct}%</span>
          </div>
          <p class="rationale">${escapeHtml(p.rationale)}</p>
        </div>`
        )
        .join("");
      return `
      <article class="card">
        <div class="card-head"><span class="matchup">${escapeHtml(g.home)} vs ${escapeHtml(g.away)}</span></div>
        <div class="whys">${rows}</div>
      </article>`;
    })
    .join("");
}

function renderUsWhy(preds) {
  const el = document.getElementById("usWhy");
  if (!preds.length) {
    el.innerHTML = `<div class="empty">No predictions to explain yet.</div>`;
    return;
  }
  const byGame = new Map();
  for (const p of preds) {
    if (!byGame.has(p.game_id)) byGame.set(p.game_id, []);
    byGame.get(p.game_id).push(p);
  }
  // Order games chronologically by start time (matches the picks page).
  el.innerHTML = Array.from(byGame.values())
    .sort((a, b) => new Date(a[0].commence_time) - new Date(b[0].commence_time))
    .map((calls) => {
      const g = calls[0];
      const rows = calls
        .slice()
        .sort((a, b) => b.prob - a.prob)
        .map(
          (p) => `
        <div class="why-row">
          <div class="why-head">
            <span class="line-mkt">${MARKET_LABEL[p.market] || escapeHtml(p.market)}</span>
            <span class="line-pick">${escapeHtml(pickLabel(p.pick))}</span>
            <span class="line-pct ${p.prob_pct >= 60 ? "p-strong" : p.prob_pct >= 45 ? "p-good" : "p-lean"}">${p.prob_pct}%</span>
          </div>
          <p class="rationale">${escapeHtml(p.rationale)}</p>
        </div>`
        )
        .join("");
      return `
      <article class="card">
        <div class="card-head"><span class="matchup">${escapeHtml(g.away_team)} @ ${escapeHtml(g.home_team)}</span></div>
        <div class="whys">${rows}</div>
      </article>`;
    })
    .join("");
}

load();
