"use strict";
(() => {
  const REFRESH_MS = 20000;

  function q(id) { return document.getElementById(id); }

  function el(tag, opts = {}) {
    const node = document.createElement(tag);
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined) node.textContent = opts.text;
    return node;
  }

  function chip(ok, label) {
    return el("span", { className: "chip " + (ok ? "ok" : "warn"), text: label });
  }

  function row(cells) {
    const tr = el("tr");
    for (const cell of cells) {
      const td = el("td");
      if (typeof cell === "string") td.textContent = cell; else td.append(cell);
      tr.append(td);
    }
    return tr;
  }

  function bytes(value) {
    if (!Number.isFinite(value)) return "—";
    const units = ["o", "Ko", "Mo", "Go", "To"];
    let index = 0, size = value;
    while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
    return (index === 0 ? size : size.toFixed(1)) + " " + units[index];
  }

  function renderEngines(engines) {
    const body = q("engines");
    body.replaceChildren();
    for (const engine of engines || []) {
      body.append(row([
        engine.engine || "—",
        engine.label || "",
        chip(engine.available, engine.available ? "disponible" : "indisponible — " + (engine.state || "?")),
      ]));
    }
    if (!body.children.length) body.append(row(["—", "", "aucun moteur"]));
  }

  function renderStack(data) {
    const body = q("stack");
    body.replaceChildren();
    const knowledge = data.knowledge || {};
    const documents = Number(knowledge.documents || 0);
    body.append(row(["Base de connaissances",
      chip(knowledge.ready, knowledge.ready
        ? documents + " passage(s) indexé(s) · recherche " + (knowledge.mode === "hybrid" ? "hybride (vectorielle)" : "lexicale")
        : "vide")]));
    const arena = data.arena || {};
    body.append(row(["Arène", chip(arena.available,
      arena.available ? (arena.matches != null ? arena.matches + " match(s) joués" : "active") : "indisponible")]));
    const corpus = data.corpus || {};
    body.append(row(["Incréments de corpus", chip(corpus.available,
      corpus.available ? (corpus.total || 0) + " incrément(s), dont " + (corpus.validated || 0) + " validé(s)" : "indisponible")]));
    const workspace = data.workspace || {};
    body.append(row(["Dossier de travail", chip(workspace.configured,
      workspace.configured ? (workspace.files || 0) + " fichier(s) produit(s)" : "non configuré")]));
    const actions = data.actions || {};
    body.append(row(["Outils de l’assistant", chip(actions.tools_enabled,
      (actions.tools_enabled ? "outils actifs" : "outils désactivés")
      + " · exécution de code " + (actions.sandbox ? "disponible (bac à sable)" : "indisponible"))]));
  }

  function renderResources(resources) {
    const body = q("resources");
    body.replaceChildren();
    const memory = resources.memory;
    if (memory) {
      body.append(row(["Mémoire", bytes(memory.total_bytes - (memory.available_bytes || 0)) + " utilisés sur "
        + bytes(memory.total_bytes) + (memory.used_percent != null ? " (" + memory.used_percent + " %)" : "")]));
    }
    const disk = resources.disk;
    if (disk) {
      body.append(row(["Disque (données de la passerelle)", bytes(disk.total_bytes - disk.free_bytes) + " utilisés sur "
        + bytes(disk.total_bytes) + (disk.used_percent != null ? " (" + disk.used_percent + " %)" : "")]));
    }
    if (Array.isArray(resources.load) && resources.load.length) {
      body.append(row(["Charge moyenne (1 / 5 / 15 min)", resources.load.join("  ·  ")]));
    }
    if (!body.children.length) body.append(row(["—", "mesures indisponibles"]));
  }

  async function refresh() {
    try {
      const response = await fetch("/v1/health", { credentials: "same-origin", cache: "no-store" });
      if (response.status === 401) { q("status").textContent = "Session expirée — reconnectez-vous depuis le chat."; return; }
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      renderEngines(data.engines);
      renderStack(data);
      renderResources(data.resources || {});
      q("status").textContent = "À jour · " + new Date().toLocaleTimeString("fr-FR");
    } catch (error) {
      q("status").textContent = "État indisponible : " + (error.message || error);
    }
  }

  refresh();
  setInterval(refresh, REFRESH_MS);
})();
