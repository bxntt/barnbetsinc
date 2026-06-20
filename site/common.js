"use strict";

/* Shared helpers used across the site pages (app.js, record.js, groups.js,
   injuries.js). Kept tiny and dependency-free. */

async function fetchJson(name) {
  const res = await fetch(name + "?_=" + Date.now());
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

function loadError(err, mod) {
  const msg = err && err.message ? err.message : String(err);
  return `<div class="empty">Couldn't load (${escapeHtml(msg)}).<br/>Run <code>python -m ${mod}</code> first.</div>`;
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
  if (mins <= 0) return "live";
  if (mins < 60) return "in " + mins + "m";
  const h = Math.round(mins / 60);
  return h < 24 ? "in " + h + "h" : "in " + Math.round(h / 24) + "d";
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}
