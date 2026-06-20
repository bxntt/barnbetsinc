"use strict";

/* Group advancement page: the World Cup group-stage Monte Carlo on its own,
   with a touch more detail (win-group odds + the sim methodology note) than
   the compact summary that used to ride along on the Picks page. */

async function load() {
  let d;
  try {
    d = await fetchJson("worldcup.json");
  } catch (err) {
    document.getElementById("wcGroups").innerHTML = loadError(err, "agent.worldcup.pipeline");
    return;
  }
  renderGroups(d.groups || []);
  if (d.sim_note) document.getElementById("simNote").textContent = d.sim_note;
  if (d.generated_at) {
    document.getElementById("updated").textContent = "Updated · " + timeAgo(d.generated_at);
  }
}

// Left-edge accent: clear to advance, on the bubble, or trailing.
function advClass(p) {
  return p >= 0.5 ? "adv-in" : p >= 0.2 ? "adv-edge" : "adv-out";
}

function renderGroups(groups) {
  const el = document.getElementById("wcGroups");
  if (!groups.length) {
    el.innerHTML = `<div class="empty">No group projections yet.</div>`;
    return;
  }
  // Stable A→L order regardless of how the feed lists them.
  el.innerHTML = groups
    .slice()
    .sort((a, b) => String(a.group).localeCompare(String(b.group)))
    .map(groupCard)
    .join("");
}

function groupCard(g) {
  const rows = g.teams
    .map(
      (t) => `
      <tr class="${advClass(t.p_advance)}">
        <td class="team">${escapeHtml(t.team)}</td>
        <td class="num">${t.points}</td>
        <td class="num win">${t.p_win_group_pct}%</td>
        <td class="advc">
          <div class="advbar"><div class="advfill" style="width:${t.p_advance_pct}%"></div></div>
          <span class="advnum">${t.p_advance_pct}%</span>
        </td>
      </tr>`
    )
    .join("");
  return `
  <article class="card group">
    <div class="card-head">
      <span class="matchup">Group ${escapeHtml(g.group)}</span>
      <span class="meta">${g.matches_played}/${g.matches_total} played</span>
    </div>
    <table class="gtable">
      <thead><tr><th>Team</th><th>Pts</th><th>Win grp</th><th>Advance</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </article>`;
}

load();
