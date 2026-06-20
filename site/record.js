"use strict";

/* Record page: the fuller view behind the ticker at the top of the picks page.
   Reads the same site/record.json — an overall hero, then one card per bet
   category, each showing wins-losses (pushes parked) and win %. */

async function load() {
  const rec = await fetchJson("record.json").catch((e) => e);
  if (rec instanceof Error) {
    document.getElementById("record").innerHTML = loadError(rec, "agent.record");
    return;
  }
  render(rec);
  if (rec.generated_at) {
    document.getElementById("updated").textContent = "Updated · " + timeAgo(rec.generated_at);
  }
  document.getElementById("recordNote").textContent = rec.note || "";
}

// win% colour mirrors the ticker: hot >=55, even >=50, otherwise cold.
function tone(pct, decided) {
  if (!decided) return "t-none";
  if (pct >= 55) return "t-hot";
  if (pct >= 50) return "t-ok";
  return "t-cold";
}

function statBlock(c, isOverall) {
  const decided = (c.wins || 0) + (c.losses || 0);
  const cls = tone(c.win_pct, decided);
  const pct = decided ? `${c.win_pct}%` : "—";
  const pushes = c.pushes ? `<span class="rec-push">${c.pushes} push${c.pushes === 1 ? "" : "es"}</span>` : "";
  return `
  <div class="rec-card ${cls}${isOverall ? " rec-overall" : ""}">
    <span class="rec-label">${escapeHtml(c.label)}</span>
    <span class="rec-wl">${c.wins || 0}<span class="t-dash">–</span>${c.losses || 0}</span>
    <span class="rec-pct">${pct}${decided ? " win" : ""}</span>
    ${pushes}
  </div>`;
}

function render(rec) {
  const el = document.getElementById("record");
  const cats = (rec && rec.categories) || [];
  const decided = rec && rec.overall
    ? (rec.overall.wins || 0) + (rec.overall.losses || 0) : 0;

  if (!rec || (!decided && !cats.some((c) => (c.wins || 0) + (c.losses || 0) > 0))) {
    const since = rec && rec.since ? ` Settles begin after ${escapeHtml(rec.since)}.` : "";
    el.innerHTML = `<div class="empty">No settled picks yet — the record builds as games finish.${since}</div>`;
    return;
  }

  const overall = rec.overall ? statBlock({ label: "Overall", ...rec.overall }, true) : "";
  const grid = cats.map((c) => statBlock(c, false)).join("");
  el.innerHTML = `${overall}<div class="rec-grid">${grid}</div>`;
}

load();
