"use strict";

/* Justification page: the per-pick "how we got here", pulled from the same
   JSON feeds as the picks page so it stays in sync automatically. */

const MARKET_LABEL = {
  result: "Result",
  total: "Total",
  btts: "BTTS",
  handicap: "Handicap",
};

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
    renderBetsWhy(hr.value.bets || []);
  } else {
    document.getElementById("betsWhy").innerHTML = loadError(hr.reason, "agent.pipeline");
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
  el.innerHTML = Array.from(byGame.values())
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
            <span class="line-pick">${escapeHtml(p.pick)}</span>
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

function renderBetsWhy(bets) {
  const el = document.getElementById("betsWhy");
  const list = bets.slice().sort((a, b) => b.ev_pct - a.ev_pct);
  if (!list.length) {
    el.innerHTML = `<div class="empty">No +EV bets to explain right now.</div>`;
    return;
  }
  el.innerHTML = list
    .map(
      (b) => `
    <article class="card">
      <div class="card-head">
        <div>
          <div class="bet-label">${escapeHtml(b.label)}</div>
          <span class="meta">${escapeHtml(b.away_team)} @ ${escapeHtml(b.home_team)} · ${escapeHtml(b.sport_title)}</span>
        </div>
        <div class="ev-badge ${b.ev_pct >= 5 ? "ev-strong" : b.ev_pct >= 3 ? "ev-good" : "ev-lean"}">
          <div class="ev">+${b.ev_pct}%</div><div class="ev-k">edge</div>
        </div>
      </div>
      <p class="rationale">${escapeHtml(b.rationale)}</p>
    </article>`
    )
    .join("");
}

load();
