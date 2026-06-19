"use strict";

/* Picks page: one merged, essentials-only view of World Cup predictions,
   group advancement, and Hard Rock +EV bets. The "why" lives on
   justification.html, so this page stays uncluttered. */

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

  let updated = [];

  if (wc.status === "fulfilled") {
    const d = wc.value;
    renderWcPredictions(d.predictions || []);
    renderWcGroups(d.groups || [], d.sim_note || "");
    if (d.generated_at) updated.push("World Cup " + timeAgo(d.generated_at));
  } else {
    document.getElementById("wcPredictions").innerHTML = loadError(wc.reason, "agent.worldcup.pipeline");
    document.getElementById("wcGroups").innerHTML = "";
  }

  if (hr.status === "fulfilled") {
    renderBets(hr.value.bets || []);
    if (hr.value.generated_at) updated.push("Hard Rock " + timeAgo(hr.value.generated_at));
  } else {
    document.getElementById("bets").innerHTML = loadError(hr.reason, "agent.pipeline");
  }

  document.getElementById("updated").textContent = updated.length ? "Updated · " + updated.join(" · ") : "";
}

/* ---------------------------------------------------------- World Cup --- */
function pctClass(pct) {
  if (pct >= 60) return "p-strong";
  if (pct >= 45) return "p-good";
  return "p-lean";
}

function renderWcPredictions(preds) {
  const el = document.getElementById("wcPredictions");
  if (!preds.length) {
    el.innerHTML = `<div class="empty">No predictions yet.</div>`;
    return;
  }
  // preds arrive ranked by probability; group per game, keep that order.
  const byGame = new Map();
  for (const p of preds) {
    if (!byGame.has(p.match_id)) byGame.set(p.match_id, []);
    byGame.get(p.match_id).push(p);
  }
  el.innerHTML = Array.from(byGame.values()).map(predGameCard).join("");
}

function predGameCard(calls) {
  const g = calls[0];
  const meta = (g.group ? "Group " + escapeHtml(g.group) + " · " : "") + "starts " + timeUntil(g.commence_time);
  const rows = calls
    .slice()
    .sort((a, b) => b.prob - a.prob)
    .map((p) => {
      const cls = pctClass(p.prob_pct);
      return `
      <div class="line">
        <span class="line-mkt">${MARKET_LABEL[p.market] || escapeHtml(p.market)}</span>
        <span class="line-pick">${escapeHtml(p.pick)}</span>
        <span class="line-pct ${cls}">${p.prob_pct}%</span>
      </div>`;
    })
    .join("");
  return `
  <article class="card">
    <div class="card-head">
      <span class="matchup">${escapeHtml(g.home)} vs ${escapeHtml(g.away)}</span>
      <span class="meta">${meta}</span>
    </div>
    <div class="lines">${rows}</div>
  </article>`;
}

function renderWcGroups(groups) {
  const el = document.getElementById("wcGroups");
  if (!groups.length) {
    el.innerHTML = `<div class="empty">No group projections yet.</div>`;
    return;
  }
  el.innerHTML = groups.map(groupCard).join("");
}

function groupCard(g) {
  const rows = g.teams
    .map((t) => {
      const cls = t.p_advance >= 0.5 ? "adv-in" : t.p_advance >= 0.2 ? "adv-edge" : "adv-out";
      return `
      <tr class="${cls}">
        <td class="team">${escapeHtml(t.team)}</td>
        <td class="num">${t.points}</td>
        <td class="advc">
          <div class="advbar"><div class="advfill" style="width:${t.p_advance_pct}%"></div></div>
          <span class="advnum">${t.p_advance_pct}%</span>
        </td>
      </tr>`;
    })
    .join("");
  return `
  <article class="card group">
    <div class="card-head">
      <span class="matchup">Group ${escapeHtml(g.group)}</span>
      <span class="meta">${g.matches_played}/${g.matches_total} played</span>
    </div>
    <table class="gtable">
      <thead><tr><th>Team</th><th>Pts</th><th>Advance</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </article>`;
}

/* ---------------------------------------------------------- Hard Rock --- */
function evClass(ev) {
  if (ev >= 5) return "ev-strong";
  if (ev >= 3) return "ev-good";
  return "ev-lean";
}

function renderBets(bets) {
  const el = document.getElementById("bets");
  const list = bets.slice().sort((a, b) => b.ev_pct - a.ev_pct);
  if (!list.length) {
    el.innerHTML = `<div class="empty">No +EV bets right now. Check back after the next refresh.</div>`;
    return;
  }
  el.innerHTML = list.map(betCard).join("");
}

function betCard(b) {
  return `
  <article class="card">
    <div class="card-head">
      <div>
        <div class="bet-label">${escapeHtml(b.label)}</div>
        <span class="meta">${escapeHtml(b.away_team)} @ ${escapeHtml(b.home_team)} · ${escapeHtml(b.sport_title)}</span>
      </div>
      <div class="ev-badge ${evClass(b.ev_pct)}">
        <div class="ev">+${b.ev_pct}%</div>
        <div class="ev-k">edge</div>
      </div>
    </div>
    <div class="prices">
      <div class="price-box hr"><div class="k">Hard Rock</div><div class="v">${b.price_display}</div></div>
      <div class="price-box"><div class="k">Fair · ${b.chance_pct ?? b.fair_prob_pct}% to hit</div>
        <div class="v">${fmtAmerican(b.fair_price_american)}</div></div>
    </div>
  </article>`;
}

load();
