"use strict";

/* Picks page: an essentials-only view of World Cup match predictions and
   US-sports model picks. Group advancement lives on groups.html and the
   win-loss history lives on record.html, so this page stays uncluttered. */

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

// Games starting within this window show up front; anything further out is
// tucked behind a "Load more" button so the page leads with imminent matches.
const NEAR_WINDOW_MS = 3 * 24 * 60 * 60 * 1000;

/* Render a chronologically-sorted list of games (each an array of per-market
   calls) into `el`, leading with games that start within NEAR_WINDOW_MS and
   hiding the rest behind a "Load more" button. `cardFn` renders one game. */
function renderGameList(el, games, cardFn, emptyMsg) {
  if (!games.length) {
    el.innerHTML = `<div class="empty">${emptyMsg}</div>`;
    return;
  }
  const cutoff = Date.now() + NEAR_WINDOW_MS;
  const near = [];
  const far = [];
  for (const g of games) {
    (Date.parse(g[0].commence_time) <= cutoff ? near : far).push(g);
  }

  el.innerHTML = near.map(cardFn).join("");
  if (!far.length) return;

  // Far-out games render hidden; the button reveals them and removes itself.
  const more = document.createElement("div");
  more.className = "stack more-games";
  more.hidden = true;
  more.innerHTML = far.map(cardFn).join("");

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "load-more";
  btn.textContent = `Load ${far.length} more ${far.length === 1 ? "game" : "games"} (3+ days out)`;
  btn.addEventListener("click", () => {
    more.hidden = false;
    btn.remove();
  });

  el.append(more, btn);
}

async function load() {
  const [hr, wc, rec] = await Promise.allSettled([
    fetchJson("data.json"),
    fetchJson("worldcup.json"),
    fetchJson("record.json"),
  ]);

  renderRecord(rec.status === "fulfilled" ? rec.value : null);

  let updated = [];

  if (wc.status === "fulfilled") {
    const d = wc.value;
    renderWcPredictions(d.predictions || []);
    if (d.generated_at) updated.push("World Cup " + timeAgo(d.generated_at));
  } else {
    document.getElementById("wcPredictions").innerHTML = loadError(wc.reason, "agent.worldcup.pipeline");
  }

  if (hr.status === "fulfilled") {
    renderUsPredictions(hr.value.predictions || []);
    if (hr.value.generated_at) updated.push("US sports " + timeAgo(hr.value.generated_at));
  } else {
    document.getElementById("usPredictions").innerHTML = loadError(hr.reason, "agent.pipeline");
  }

  document.getElementById("updated").textContent = updated.length ? "Updated · " + updated.join(" · ") : "";
}

/* ------------------------------------------------------ Track record --- */
// A permanent, horizontally-scrolling ticker pinned to the top of the page:
// overall first, then one segment per bet category. Each shows the W-L of the
// published pick settled against final scores; colour tracks the win rate. The
// segment list is rendered twice so the CSS marquee loops seamlessly.
function renderRecord(rec) {
  const el = document.getElementById("recordTicker");
  if (!el) return;
  const cats = (rec && rec.categories) || [];
  const segments = [];
  if (rec && rec.overall) {
    segments.push(tickerSegment({ label: "Overall", ...rec.overall }, true));
  }
  for (const c of cats) segments.push(tickerSegment(c, false));
  if (!segments.length) {
    el.innerHTML = `<span class="ticker-seg"><span class="t-cat">No record yet</span></span>`;
    el.classList.add("is-static");
    return;
  }
  const inner = segments.join("");
  const runOne = `<div class="ticker-run">${inner}</div>`;
  const runTwo = `<div class="ticker-run" aria-hidden="true">${inner}</div>`;
  // Only scroll when one run actually overflows the viewport. If it fits, a
  // second run would just sit beside the first and read as a doubled record,
  // so we keep a single, centered run instead. Re-check on resize/rotate.
  const layout = () => {
    el.classList.remove("is-static");
    el.innerHTML = runOne;
    if (el.scrollWidth <= el.parentElement.clientWidth + 1) {
      el.classList.add("is-static");
    } else {
      el.innerHTML = runOne + runTwo;
    }
  };
  layout();
  let raf;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(layout);
  });
}

function tickerSegment(c, isOverall) {
  const decided = (c.wins || 0) + (c.losses || 0);
  const has = decided > 0;
  const cls = !has ? "t-none"
    : c.win_pct >= 55 ? "t-hot"
    : c.win_pct >= 50 ? "t-ok"
    : "t-cold";
  const wl = `${c.wins || 0}<span class="t-dash">–</span>${c.losses || 0}`;
  const pct = has ? `<span class="t-pct">${c.win_pct}%</span>` : "";
  return `
  <span class="ticker-seg ${cls}${isOverall ? " t-overall" : ""}">
    <span class="t-cat">${escapeHtml(c.label)}</span>
    <span class="t-wl">${wl}</span>
    ${pct}
  </span>`;
}

/* ---------------------------------------------------------- World Cup --- */
function pctClass(pct) {
  if (pct >= 60) return "p-strong";
  if (pct >= 45) return "p-good";
  return "p-lean";
}

function renderWcPredictions(preds) {
  const el = document.getElementById("wcPredictions");
  // preds arrive ranked by probability; group per game, then order games
  // chronologically by kickoff.
  const byGame = new Map();
  for (const p of preds) {
    if (!byGame.has(p.match_id)) byGame.set(p.match_id, []);
    byGame.get(p.match_id).push(p);
  }
  const games = Array.from(byGame.values())
    .sort((a, b) => new Date(a[0].commence_time) - new Date(b[0].commence_time));
  renderGameList(el, games, predGameCard, "No predictions yet.");
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
        <span class="line-pick">${escapeHtml(pickLabel(p.pick))}</span>
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

/* ---------------------------------------------------------- US sports --- */
function renderUsPredictions(preds) {
  const el = document.getElementById("usPredictions");
  // preds arrive ranked by probability; group per game, then order games
  // chronologically by start time.
  const byGame = new Map();
  for (const p of preds) {
    if (!byGame.has(p.game_id)) byGame.set(p.game_id, []);
    byGame.get(p.game_id).push(p);
  }
  const games = Array.from(byGame.values())
    .sort((a, b) => new Date(a[0].commence_time) - new Date(b[0].commence_time));
  renderGameList(el, games, usGameCard, "No predictions yet. Check back after the next refresh.");
}

function usGameCard(calls) {
  const g = calls[0];
  const meta = escapeHtml(g.sport_title) + " · starts " + timeUntil(g.commence_time);
  const rows = calls
    .slice()
    .sort((a, b) => b.prob - a.prob)
    .map((p) => {
      const cls = pctClass(p.prob_pct);
      return `
      <div class="line">
        <span class="line-mkt">${MARKET_LABEL[p.market] || escapeHtml(p.market)}</span>
        <span class="line-pick">${escapeHtml(pickLabel(p.pick))}</span>
        <span class="line-pct ${cls}">${p.prob_pct}%</span>
      </div>`;
    })
    .join("");
  return `
  <article class="card">
    <div class="card-head">
      <span class="matchup">${escapeHtml(g.away_team)} @ ${escapeHtml(g.home_team)}</span>
      <span class="meta">${meta}</span>
    </div>
    <div class="lines">${rows}</div>
  </article>`;
}

load();
