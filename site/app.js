"use strict";

const state = { bets: [], filter: "ALL" };

async function load() {
  try {
    const res = await fetch("data.json?_=" + Date.now());
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    render(data);
  } catch (err) {
    document.getElementById("bets").innerHTML =
      `<div class="empty">Couldn't load data.json (${err.message}).<br/>Run <code>python -m agent.pipeline</code> first.</div>`;
  }
}

function render(data) {
  state.bets = data.bets || [];
  renderTrackRecord(data.track_record || {});
  document.getElementById("updated").textContent =
    "Updated " + timeAgo(data.generated_at) + " · target: " + (data.target_book || "—");
  document.getElementById("disclaimer").textContent = data.disclaimer || "";
  renderFilters();
  renderBets();
}

function renderTrackRecord(tr) {
  const el = document.getElementById("trackRecord");
  if (tr.avg_clv_pct === null || tr.avg_clv_pct === undefined) {
    el.innerHTML = `<span class="tr-note">📈 ${tr.note || "Track record builds as games settle."}</span>`;
    return;
  }
  const sign = tr.avg_clv_pct >= 0 ? "+" : "";
  el.innerHTML = `
    <div class="tr-stat"><div class="v">${sign}${tr.avg_clv_pct}%</div><div class="k">Avg CLV</div></div>
    <div class="tr-stat"><div class="v">${tr.beat_close_pct}%</div><div class="k">Beat close</div></div>
    <div class="tr-stat"><div class="v">${tr.graded}</div><div class="k">Graded bets</div></div>`;
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
  const list =
    state.filter === "ALL"
      ? state.bets
      : state.bets.filter((b) => b.sport_title === state.filter);
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
  if (b.movement && b.movement.direction === "toward")
    tags.push(`<span class="tag toward">↗ line moving your way</span>`);
  if (b.movement && b.movement.direction === "away")
    tags.push(`<span class="tag away">↘ line drifting away</span>`);
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
