"use strict";

const state = { bets: [], filter: "ALL", view: "worldcup", wc: null, wcSub: "predictions" };

async function load() {
  // Hard Rock and World Cup are independent feeds; load both, tolerate either missing.
  const [hr, wc] = await Promise.allSettled([
    fetchJson("data.json"),
    fetchJson("worldcup.json"),
  ]);

  if (hr.status === "fulfilled") {
    renderHardRock(hr.value);
  } else {
    document.getElementById("bets").innerHTML = loadError(hr.reason, "agent.pipeline");
  }

  if (wc.status === "fulfilled") {
    state.wc = wc.value;
    renderWorldCup(wc.value);
  } else {
    document.getElementById("wcPredictions").innerHTML = loadError(wc.reason, "agent.worldcup.pipeline");
  }

  initTabs();
}

async function fetchJson(name) {
  const res = await fetch(name + "?_=" + Date.now());
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

function loadError(err, mod) {
  const msg = err && err.message ? err.message : String(err);
  return `<div class="empty">Couldn't load (${escapeHtml(msg)}).<br/>Run <code>python -m ${mod}</code> first.</div>`;
}

/* ------------------------------------------------------------------ tabs --- */
function initTabs() {
  document.body.dataset.view = state.view;
  document.querySelectorAll("#tabs .tab").forEach((t) =>
    t.addEventListener("click", () => switchView(t.dataset.view))
  );
  document.querySelectorAll("#wcSubtabs .subtab").forEach((t) =>
    t.addEventListener("click", () => switchWcSub(t.dataset.sub))
  );
}

function switchView(view) {
  state.view = view;
  document.querySelectorAll("#tabs .tab").forEach((t) =>
    t.setAttribute("aria-selected", String(t.dataset.view === view))
  );
  document.getElementById("view-hardrock").hidden = view !== "hardrock";
  document.getElementById("view-worldcup").hidden = view !== "worldcup";
  document.body.dataset.view = view;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function switchWcSub(sub) {
  state.wcSub = sub;
  document.querySelectorAll("#wcSubtabs .subtab").forEach((t) =>
    t.setAttribute("aria-selected", String(t.dataset.sub === sub))
  );
  document.getElementById("wcPredictions").hidden = sub !== "predictions";
  document.getElementById("wcGroups").hidden = sub !== "groups";
}

/* -------------------------------------------------------------- Hard Rock --- */
function renderHardRock(data) {
  state.bets = data.bets || [];
  renderTrackRecord(data.track_record || {}, data.calibration || {});
  document.getElementById("updated").textContent =
    "Updated " + timeAgo(data.generated_at) + " · target: " + (data.target_book || "—");
  document.getElementById("disclaimer").textContent = data.disclaimer || "";
  renderFilters();
  renderBets();
}

function renderTrackRecord(tr, cal) {
  const el = document.getElementById("trackRecord");
  const calStat =
    cal && cal.graded
      ? `<div class="tr-stat"><div class="v">${cal.brier}</div><div class="k">Brier (cal.)</div></div>`
      : "";
  if (tr.avg_clv_pct === null || tr.avg_clv_pct === undefined) {
    el.innerHTML =
      `<span class="tr-note">📈 ${tr.note || "Track record builds as games settle."}</span>` + calStat;
    return;
  }
  const sign = tr.avg_clv_pct >= 0 ? "+" : "";
  el.innerHTML = `
    <div class="tr-stat"><div class="v">${sign}${tr.avg_clv_pct}%</div><div class="k">Avg CLV</div></div>
    <div class="tr-stat"><div class="v">${tr.beat_close_pct}%</div><div class="k">Beat close</div></div>
    <div class="tr-stat"><div class="v">${tr.graded}</div><div class="k">Graded bets</div></div>` + calStat;
}

function renderFilters() {
  const sports = ["ALL", ...new Set(state.bets.map((b) => b.sport_title))];
  const nav = document.getElementById("filters");
  nav.innerHTML = sports
    .map(
      (s) =>
        `<button class="chip" role="button" aria-pressed="${s === state.filter}" data-sport="${s}">${
          s === "ALL" ? "All" : s
        }</button>`
    )
    .join("");
  nav.querySelectorAll(".chip").forEach((c) =>
    c.addEventListener("click", () => {
      state.filter = c.dataset.sport;
      renderFilters();
      renderBets();
    })
  );
}

function renderBets() {
  const list = (state.filter === "ALL"
    ? state.bets
    : state.bets.filter((b) => b.sport_title === state.filter)
  )
    .slice()
    .sort((a, b) => b.ev_pct - a.ev_pct);
  const el = document.getElementById("bets");
  if (!list.length) {
    el.innerHTML = `<div class="empty">No +EV bets right now. Check back after the next refresh.</div>`;
    return;
  }
  el.innerHTML = list.map(card).join("");
}

function evClass(ev) {
  if (ev >= 5) return "ev-strong";
  if (ev >= 3) return "ev-good";
  return "ev-lean";
}

function card(b) {
  const conf = Math.round((b.confidence || 0) * 100);
  const tags = [];
  tags.push(`<span class="tag chance">🎯 ${b.chance_pct ?? b.fair_prob_pct}% to hit</span>`);
  if (b.kelly_pct && b.kelly_pct >= 0.05)
    tags.push(`<span class="tag stake">💰 stake ~${b.kelly_pct}%</span>`);
  if (b.movement && b.movement.direction === "toward")
    tags.push(`<span class="tag toward">↗ line moving your way</span>`);
  if (b.movement && b.movement.direction === "away")
    tags.push(`<span class="tag away">↘ line drifting away</span>`);
  if (b.movement && b.movement.sharp && b.movement.sharp.direction === "toward")
    tags.push(`<span class="tag toward">⚡ sharp money in</span>`);
  if (b.model_flag === "disagree")
    tags.push(`<span class="tag warn">⚠︎ model disagrees${b.model_prob_pct != null ? " (" + b.model_prob_pct + "%)" : ""}</span>`);
  if (b.interpolated) tags.push(`<span class="tag">≈ alt line</span>`);
  if (b.longshot) tags.push(`<span class="tag">🐶 underdog</span>`);
  tags.push(`<span class="tag">vig ${b.market_vig_pct}%</span>`);
  tags.push(`<span class="tag">starts ${timeUntil(b.commence_time)}</span>`);
  if (b.context && b.context.notes) tags.push(`<span class="tag">ℹ︎ context</span>`);

  return `
  <article class="card">
    <div class="card-top">
      <div>
        <div class="bet-label">${escapeHtml(b.label)}</div>
        <div class="matchup">${escapeHtml(b.away_team)} @ ${escapeHtml(b.home_team)}</div>
        <span class="sport-tag">${escapeHtml(b.sport_title)}</span>
      </div>
      <div class="ev-badge ${evClass(b.ev_pct)}">
        <div class="ev">+${b.ev_pct}%</div>
        <div class="ev-k">edge</div>
      </div>
    </div>

    <div class="prices">
      <div class="price-box hr"><div class="k">Hard Rock</div><div class="v">${b.price_display}</div></div>
      <div class="price-box"><div class="k">Fair (${escapeHtml(b.reference_book)})</div>
        <div class="v">${fmtAmerican(b.fair_price_american)} · ${b.fair_prob_pct}%</div></div>
    </div>

    <div class="conf-row">
      <span class="conf-label">Confidence</span>
      <div class="conf-bar"><div class="conf-fill" style="width:${conf}%"></div></div>
      <span class="conf-val">${conf}%</span>
    </div>

    <p class="rationale">${escapeHtml(b.rationale)}</p>
    <div class="tags">${tags.join("")}</div>
  </article>`;
}

/* -------------------------------------------------------------- World Cup --- */
const MARKET_LABEL = {
  result: "Result",
  total: "Total goals",
  btts: "Both teams to score",
  handicap: "Handicap",
};

function renderWorldCup(data) {
  const preds = data.predictions || [];
  const games = new Set(preds.map((p) => p.match_id)).size;
  document.getElementById("wcUpdated").textContent =
    "Updated " + timeAgo(data.generated_at) +
    " · " + (data.prediction_count || preds.length) + " predictions across " + games + " games · " +
    (data.groups ? data.groups.length : 0) + " groups · " +
    (data.sims ? data.sims.toLocaleString() + " sims" : "");
  renderWcPredictions(preds);
  renderWcGroups(data.groups || [], data.sim_note || "");
}

function pctClass(pct) {
  if (pct >= 60) return "p-strong";
  if (pct >= 45) return "p-good";
  return "p-lean";
}

function renderWcPredictions(preds) {
  const el = document.getElementById("wcPredictions");
  if (!preds.length) {
    el.innerHTML = `<div class="empty">No predictions yet. Run <code>python -m agent.worldcup.pipeline</code> to generate them.</div>`;
    return;
  }
  // Group the per-market calls by game. preds arrive ranked by probability, so a
  // game with a strong single call naturally floats to the top.
  const byGame = new Map();
  for (const p of preds) {
    if (!byGame.has(p.match_id)) byGame.set(p.match_id, []);
    byGame.get(p.match_id).push(p);
  }
  el.innerHTML = Array.from(byGame.values()).map(predGameCard).join("");
}

function predGameCard(calls) {
  const g = calls[0];
  const rows = calls
    .slice()
    .sort((a, b) => b.prob - a.prob)
    .map(predRow)
    .join("");
  return `
  <article class="card wc pred">
    <div class="card-top">
      <div>
        <div class="matchup">${escapeHtml(g.home)} vs ${escapeHtml(g.away)}</div>
        <span class="sport-tag wc-tag">${g.group ? "Group " + escapeHtml(g.group) + " · " : ""}starts ${timeUntil(g.commence_time)}</span>
      </div>
    </div>
    <div class="preds">${rows}</div>
  </article>`;
}

function predRow(p) {
  const pct = p.prob_pct;
  const conf = Math.round((p.confidence || 0) * 100);
  const cls = pctClass(pct);
  const split =
    p.market_prob_pct != null
      ? `model ${p.model_prob_pct}% · market ${p.market_prob_pct}%`
      : "model only";
  return `
  <div class="pred-row">
    <div class="pred-head">
      <span class="pred-mkt">${MARKET_LABEL[p.market] || escapeHtml(p.market)}</span>
      <span class="pred-pick">${escapeHtml(p.pick)}</span>
      <span class="pred-pct ${cls}">${pct}%</span>
    </div>
    <div class="pbar"><div class="pfill ${cls}" style="width:${pct}%"></div></div>
    <div class="pred-meta">${split} · confidence ${conf}%</div>
    <p class="rationale">${escapeHtml(p.rationale)}</p>
  </div>`;
}

function renderWcGroups(groups, note) {
  const el = document.getElementById("wcGroups");
  if (!groups.length) {
    el.innerHTML = `<div class="empty">${escapeHtml(note || "No group projections available.")}</div>`;
    return;
  }
  el.innerHTML = groups.map(groupCard).join("");
}

function groupCard(g) {
  const rows = g.teams
    .map((t) => {
      const adv = t.p_advance_pct;
      const cls = t.p_advance >= 0.5 ? "adv-in" : t.p_advance >= 0.2 ? "adv-edge" : "adv-out";
      return `
      <tr class="${cls}">
        <td class="team">${escapeHtml(t.team)}</td>
        <td class="num">${t.points}</td>
        <td class="num">${t.goal_diff >= 0 ? "+" : ""}${t.goal_diff}</td>
        <td class="num dim">${t.exp_points}</td>
        <td class="advc">
          <div class="advbar"><div class="advfill" style="width:${adv}%"></div></div>
          <span class="advnum">${adv}%</span>
        </td>
        <td class="num dim">${t.p_win_group_pct}%</td>
      </tr>`;
    })
    .join("");

  return `
  <article class="card group">
    <div class="group-head">
      <h3>Group ${escapeHtml(g.group)}</h3>
      <span class="played">${g.matches_played}/${g.matches_total} played</span>
    </div>
    <table class="gtable">
      <thead>
        <tr><th>Team</th><th>Pts</th><th>GD</th><th>xPts</th><th>Advance</th><th>Win</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </article>`;
}

/* --------------------------------------------------------------- helpers --- */
function fmtAmerican(n) {
  return n > 0 ? "+" + n : "" + n;
}

function timeAgo(iso) {
  const t = Date.parse(iso);
  if (isNaN(t)) return "—";
  const mins = Math.round((Date.now() - t) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return mins + "m ago";
  const h = Math.round(mins / 60);
  return h < 24 ? h + "h ago" : Math.round(h / 24) + "d ago";
}

function timeUntil(iso) {
  const t = Date.parse(iso);
  if (isNaN(t)) return "soon";
  const mins = Math.round((t - Date.now()) / 60000);
  if (mins <= 0) return "live/started";
  if (mins < 60) return "in " + mins + "m";
  const h = Math.round(mins / 60);
  return h < 24 ? "in " + h + "h" : "in " + Math.round(h / 24) + "d";
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

load();
