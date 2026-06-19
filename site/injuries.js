"use strict";

/* Injuries page: per-game availability report from site/injuries.json.
   For each upcoming match we list both sides' absences (out / doubtful /
   suspended). Games with reported absences float to the top; the rest are
   shown as "squad as expected" so the by-game picture stays complete. */

const STATUS_CLASS = {
  out: "st-out",
  suspended: "st-out",
  doubtful: "st-doubt",
  questionable: "st-doubt",
};

async function load() {
  const res = await Promise.allSettled([fetchJson("injuries.json")]);
  const el = document.getElementById("injuries");

  if (res[0].status !== "fulfilled") {
    el.innerHTML = loadError(res[0].reason, "agent.worldcup.pipeline");
    return;
  }
  const d = res[0].value;
  document.getElementById("updated").textContent =
    (d.generated_at ? "Updated · " + timeAgo(d.generated_at) + " · " : "") +
    (d.total_absences || 0) + " absences across " + (d.affected_games || 0) + " games" +
    (d.as_of ? " · snapshot " + d.as_of : "");
  renderInjuries(d);
}

function renderInjuries(d) {
  const el = document.getElementById("injuries");
  const games = (d.games || []).slice();
  if (!games.length) {
    el.innerHTML = `<div class="empty">No upcoming games to report.</div>`;
    return;
  }
  // Affected games first (most absences first), then the clean sheets.
  games.sort((a, b) => (b.total || 0) - (a.total || 0));
  el.innerHTML = games.map(gameCard).join("");
}

function gameCard(g) {
  const meta = (g.group ? "Group " + escapeHtml(g.group) + " · " : "") + "starts " + timeUntil(g.commence_time);
  if (!g.total) {
    return `
    <article class="card inj clean">
      <div class="card-head">
        <span class="matchup">${escapeHtml(g.home)} vs ${escapeHtml(g.away)}</span>
        <span class="meta">${meta}</span>
      </div>
      <p class="clean-note">✓ Squad as expected — no reported absences.</p>
    </article>`;
  }
  return `
  <article class="card inj">
    <div class="card-head">
      <span class="matchup">${escapeHtml(g.home)} vs ${escapeHtml(g.away)}</span>
      <span class="meta">${meta} · <span class="inj-count">${g.total} out</span></span>
    </div>
    <div class="teams">
      ${teamBlock(g.home, g.home_absences)}
      ${teamBlock(g.away, g.away_absences)}
    </div>
  </article>`;
}

function teamBlock(team, absences) {
  const list = absences || [];
  const body = list.length
    ? list.map(absenceRow).join("")
    : `<p class="clean-note small">✓ No reported absences.</p>`;
  return `
  <div class="team-block">
    <div class="team-name">${escapeHtml(team)}</div>
    ${body}
  </div>`;
}

function absenceRow(a) {
  const cls = STATUS_CLASS[(a.status || "").toLowerCase()] || "st-doubt";
  const detail = [a.position, a.reason].filter(Boolean).map(escapeHtml).join(" · ");
  const star = a.expected_starter ? `<span class="starter" title="Expected starter">★</span>` : "";
  return `
  <div class="absence">
    <span class="status ${cls}">${escapeHtml(a.status || "Out")}</span>
    <div class="absence-main">
      <div class="player">${escapeHtml(a.player)}${star}</div>
      ${detail ? `<div class="absence-detail">${detail}</div>` : ""}
    </div>
  </div>`;
}

load();
