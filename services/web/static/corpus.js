"use strict";
(() => {
  const state = { csrf: "" };

  function q(id) { return document.getElementById(id); }

  function el(tag, opts = {}) {
    const node = document.createElement(tag);
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined) node.textContent = opts.text;
    return node;
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body) headers.set("Content-Type", "application/json");
    if (state.csrf && options.method === "POST") headers.set("X-CSRF-Token", state.csrf);
    const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.status === 202 ? {} : response.json();
  }

  function statusChip(status) {
    const map = { validated: ["validé", "ok"], raw: ["RAW — en attente", "warn"] };
    const [label, cls] = map[status] || [status, ""];
    return el("span", { className: "chip " + cls, text: label });
  }

  async function promote(increment) {
    const ok = window.confirm(
      "Promouvoir l'incrément « " + increment.increment_id + " » (" + increment.record_count +
      " records) vers le corpus validé ?\n\nDonnées seulement, plafonné à sa part max. Aucun entraînement n'est lancé.");
    if (!ok) return;
    q("status").textContent = "Envoi de l'approbation…";
    try {
      await api("/v1/corpus/promote", {
        method: "POST",
        body: JSON.stringify({ target_id: increment.increment_id, target_sha256: increment.content_sha256 }),
      });
      q("status").textContent = "Approbation enregistrée — le worker gaté la traitera sous peu.";
      setTimeout(refresh, 2000);
    } catch (err) {
      q("status").textContent = "Échec de l'approbation (" + err.message + ").";
    }
  }

  function pct(v) { return typeof v === "number" ? Math.round(v * 100) + " %" : "—"; }

  function render(increments) {
    const rows = q("rows");
    rows.textContent = "";
    if (!increments.length) {
      const tr = el("tr");
      const td = el("td", { text: "Aucun incrément pour l'instant." });
      td.colSpan = 7;
      tr.append(td);
      rows.append(tr);
      return;
    }
    for (const inc of increments) {
      const tr = el("tr");
      tr.append(el("td", { text: inc.increment_id }));
      tr.append(el("td", { text: String(inc.record_count ?? "—") }));
      tr.append(el("td", { text: inc.classification || "—" }));
      tr.append(el("td", { text: pct(inc.max_share_in_corpus_increment) }));
      tr.append(el("td", { text: inc.arena_packet_id || "—" }));
      const stateCell = el("td");
      stateCell.append(statusChip(inc.status));
      tr.append(stateCell);
      const action = el("td");
      if (inc.status === "raw") {
        const btn = el("button", { className: "btn", text: "Approuver la promotion" });
        btn.onclick = () => promote(inc);
        action.append(btn);
      }
      tr.append(action);
      rows.append(tr);
    }
  }

  async function refresh() {
    try {
      const data = await api("/v1/corpus/increments");
      if (!data.available) {
        q("status").textContent = "Corpus indisponible sur le serveur.";
        render([]);
        return;
      }
      q("status").textContent = "";
      render(data.increments || []);
    } catch (err) {
      q("status").textContent = "Erreur de chargement (" + err.message + ").";
    }
  }

  async function start() {
    try {
      const session = await api("/v1/session");
      state.csrf = session.csrf_token || "";
    } catch (err) {
      q("status").textContent = "Session requise — connecte-toi d'abord.";
      return;
    }
    refresh();
  }

  start();
})();
