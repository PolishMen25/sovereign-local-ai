"use strict";
// Arena view. Everything shown comes from model output or the arena database:
// it is rendered with textContent only, never as HTML.
(() => {
  const q = (selector) => document.querySelector(selector);
  const state = { csrf: "", lastEventId: 0, profiles: new Map(), overviewTimer: null, eventTimer: null };
  const REASONS = {
    started: "l’arène démarre",
    match: "match en cours",
    engine_busy: "en pause : un moteur répond à ton chat",
    hourly_budget: "en pause : budget horaire atteint",
    engine_unavailable: "en pause : moteur injoignable",
    not_enough_authors: "en pause : il faut au moins deux auteurs",
    sandbox_unavailable: "arrêtée : sandbox indisponible",
  };
  const PACKET_STATES = { awaiting_owner_approval: ["en attente de ton accord", "warn"], flagged: ["signalé : diversité insuffisante", "fail"], approved: ["approuvé", "ok"] };
  const EMPTY = "–";

  function el(tag, options = {}, ...children) {
    const node = document.createElement(tag);
    if (options.className) node.className = options.className;
    if (options.text !== undefined) node.textContent = String(options.text);
    for (const [key, value] of Object.entries(options.attrs || {})) node.setAttribute(key, value);
    for (const child of children) if (child) node.append(child);
    return node;
  }

  function notice(message) {
    const box = q("#notice");
    box.hidden = !message;
    box.textContent = message || "";
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body) headers.set("Content-Type", "application/json");
    if (state.csrf && options.method === "POST") headers.set("X-CSRF-Token", state.csrf);
    const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) throw new Error("unauthorized");
    if (!response.ok) throw new Error(data.error || "request_failed");
    return data;
  }

  function name(profileId) {
    const profile = state.profiles.get(profileId);
    return profile ? profile.display_name : profileId;
  }

  function engineChip(engine) {
    const label = engine === "QWEN-CODER" ? "Qwen Coder 7B" : engine === "CHAT-14B" ? "Qwen 14B" : "Bootstrap 1.5B";
    return el("span", { className: "chip " + (engine === "BOOTSTRAP" ? "bootstrap" : "qwen"), text: label });
  }

  function percent(part, whole) {
    return whole ? Math.round((100 * part) / whole) + " %" : EMPTY;
  }

  function sparkline(values) {
    const svgNS = "http://www.w3.org/2000/svg";
    const width = 96, height = 26, pad = 3;
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("class", "spark");
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    if (!values || values.length < 2) {
      svg.setAttribute("aria-label", "pas encore d’historique");
      return svg;
    }
    const low = Math.min(...values), high = Math.max(...values), span = high - low || 1;
    const points = values.map((value, index) => [pad + (index * (width - 2 * pad)) / (values.length - 1), height - pad - ((value - low) * (height - 2 * pad)) / span]);
    const path = document.createElementNS(svgNS, "path");
    path.setAttribute("d", points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" "));
    const end = document.createElementNS(svgNS, "circle");
    end.setAttribute("cx", points.at(-1)[0].toFixed(1));
    end.setAttribute("cy", points.at(-1)[1].toFixed(1));
    end.setAttribute("r", "2.2");
    svg.setAttribute("aria-label", `Elo de ${Math.round(values[0])} à ${Math.round(values.at(-1))}`);
    svg.append(path, end);
    return svg;
  }

  function confirmAction(text) {
    const dialog = q("#confirm-dialog");
    q("#confirm-text").textContent = text;
    return new Promise((resolve) => {
      const done = (value) => { dialog.close(); q("#confirm-ok").onclick = null; q("#confirm-cancel").onclick = null; resolve(value); };
      q("#confirm-ok").onclick = () => done(true);
      q("#confirm-cancel").onclick = () => done(false);
      dialog.showModal();
    });
  }

  async function approve(body, message) {
    if (!(await confirmAction(message))) return;
    try {
      await api("/v1/arena/approve", { method: "POST", body: JSON.stringify(body) });
      notice("Approbation enregistrée. L’arène l’appliquera à son prochain passage (moins d’une minute).");
      setTimeout(refreshOverview, 4000);
    } catch (error) {
      notice(error.message === "arena_unavailable" ? "L’arène ne peut pas recevoir d’approbation pour l’instant (boîte de dépôt absente)." : "Approbation refusée : " + error.message);
    }
  }

  function renderStatus(data) {
    const status = data.state || {};
    const heartbeat = status.heartbeat ? new Date(status.heartbeat) : null;
    const stale = !heartbeat || Date.now() - heartbeat.getTime() > 3 * 60 * 1000;
    let text = status.status === "running" ? "Arène active" : status.status === "stopped" ? "Arène arrêtée" : "Arène en pause";
    text += " — " + (REASONS[status.reason] || status.reason || "état inconnu");
    if (status.engines && status.reason !== "engine_busy") text += " · moteurs : " + [].concat(status.engines).join(", ");
    if (stale) text = "Pas de nouvelles de l’arène depuis plus de 3 minutes (service arrêté ?)";
    q("#status").textContent = text;
    const dot = q("#status-dot");
    dot.classList.toggle("is-stopped", stale || status.status === "stopped");
    dot.classList.toggle("is-paused", !stale && status.status === "paused");
    const totals = data.totals || {};
    q("#kpi-matches").textContent = totals.matches ?? EMPTY;
    q("#kpi-hour").textContent = totals.matches_last_hour ?? EMPTY;
    q("#kpi-accepted").textContent = totals.accepted ?? EMPTY;
    q("#kpi-tasks").textContent = totals.tasks_solved ?? EMPTY;
    q("#kpi-pending").textContent = totals.pending_solutions ?? EMPTY;
  }

  function renderProfiles(profiles) {
    state.profiles = new Map(profiles.map((p) => [p.profile_id, p]));
    const authors = profiles.filter((p) => p.role === "author" && p.status === "active").sort((a, b) => b.rating - a.rating);
    const tbody = q("#authors");
    tbody.replaceChildren();
    authors.forEach((p, index) => {
      const origin = p.parent_id ? "né de " + name(p.parent_id) + " · génération " + p.generation : "profil de départ";
      const chat = p.chat_approved
        ? el("span", { className: "chip ok", text: "dans le chat" })
        : el("button", { className: "quiet small-button", text: "Proposer au chat", attrs: { type: "button" } });
      if (!p.chat_approved) chat.onclick = () => approve({ kind: "profile_chat", target_id: p.profile_id }, `Proposer « ${p.display_name} » comme profil du chat ? Il restera aussi dans l’arène.`);
      const row = el("tr", { className: index === 0 ? "leader" : "" },
        el("td", { text: index + 1 }),
        el("td", {}, el("span", { className: "agent-name", text: p.display_name }), el("span", { className: "agent-id", text: p.profile_id })),
        el("td", {}, engineChip(p.engine)),
        el("td", { className: "num", text: Math.round(p.rating) }),
        el("td", {}, sparkline(p.rating_history)),
        el("td", { className: "num", text: p.matches }),
        el("td", { className: "num", text: percent(p.first_pass, p.matches) }),
        el("td", { className: "field-help origin", text: origin }),
        el("td", {}, chat));
      tbody.append(row);
    });
    if (!authors.length) tbody.append(el("tr", {}, el("td", { className: "muted", text: "Aucun auteur actif.", attrs: { colspan: "9" } })));
    const critics = q("#critics");
    critics.replaceChildren();
    profiles.filter((p) => p.role === "critic").forEach((p) => critics.append(el("tr", {},
      el("td", {}, el("span", { className: "agent-name", text: p.display_name })),
      el("td", {}, engineChip(p.engine)),
      el("td", { className: "num", text: p.advised }),
      el("td", { className: "num", text: percent(p.advice_success, p.advised) }))));
    const retired = profiles.filter((p) => p.status === "retired");
    q("#retired").textContent = retired.length ? retired.map((p) => `${p.display_name} (Elo ${Math.round(p.rating)})`).join(" · ") : "Aucun pour l’instant.";
  }

  function renderPackets(packets) {
    const tbody = q("#packets");
    tbody.replaceChildren();
    if (!packets.length) {
      tbody.append(el("tr", {}, el("td", { className: "muted", text: "Aucun paquet pour l’instant.", attrs: { colspan: "7" } })));
      return;
    }
    for (const packet of packets) {
      const [label, tone] = PACKET_STATES[packet.status] || [packet.status, "muted"];
      let action = el("span", { className: "field-help", text: packet.approved_by ? "par " + packet.approved_by : "" });
      if (packet.status === "awaiting_owner_approval") {
        action = el("button", { className: "small-button", text: "Approuver pour l’entraînement", attrs: { type: "button" } });
        action.onclick = () => approve({ kind: "packet", target_id: packet.packet_id, target_sha256: packet.solutions_sha256 },
          `Approuver le paquet ${packet.packet_id} (${packet.solutions} solutions, empreinte ${packet.solutions_sha256.slice(0, 12)}…) ? Il pourra entrer dans un incrément de corpus, plafonné à 20 % de données synthétiques.`);
      }
      tbody.append(el("tr", {},
        el("td", {}, el("span", { className: "agent-name", text: packet.packet_id })),
        el("td", { text: new Date(packet.created_at).toLocaleString("fr-FR") }),
        el("td", { className: "num", text: packet.solutions }),
        el("td", { className: "num", text: Math.round(packet.unique_ratio * 100) + " %" }),
        el("td", { className: "num", text: Math.round(packet.max_repetition * 100) + " %" }),
        el("td", {}, el("span", { className: "chip " + tone, text: label })),
        el("td", {}, action)));
    }
  }

  function describe(event) {
    const p = event.payload || {};
    switch (event.kind) {
      case "match_started":
        return { tone: "", title: `Match ${p.match_id} : ${name(p.authors[0])} contre ${name(p.authors[1])}`, text: p.prompt, extra: p.critic_id ? "Relecteur : " + name(p.critic_id) : "" };
      case "attempt":
        return { tone: p.passed ? "pass" : "fail", title: `${name(p.profile_id)} — ${p.attempt === 1 ? "première réponse" : "après correction"}`, chip: p.passed ? ["tests réussis", "ok"] : ["tests échoués", "fail"], code: p.source, failure: p.failure };
      case "critique":
        return { tone: "", title: `${name(p.critic_id)} conseille ${name(p.author_id)}`, text: p.text };
      case "match_finished": {
        const parts = Object.entries(p.results || {}).map(([id, r]) => `${name(id)} ${r.score} pt (Elo ${r.rating}, ${r.delta >= 0 ? "+" : ""}${r.delta})`);
        return { tone: "", title: `Fin du match ${p.match_id}`, text: parts.join(" · ") };
      }
      case "profile_created":
        return { tone: "birth", title: p.parent_id ? `Nouvel agent : ${p.display_name}, né de ${name(p.parent_id)}` : `Agent de départ : ${p.display_name}`, code: p.system_prompt, codeLabel: "Instructions" };
      case "profile_retired":
        return { tone: "alert", title: `${name(p.profile_id)} prend sa retraite (Elo ${p.rating})` };
      case "evolution_rejected":
        return { tone: "alert", title: `Variante de ${name(p.parent_id)} refusée`, text: "Instructions proposées invalides." };
      case "packet_created":
        return { tone: p.status === "flagged" ? "alert" : "pass", title: `Paquet ${p.packet_id} : ${p.solutions} solutions`, chip: (PACKET_STATES[p.status] || [p.status, "muted"]) };
      case "approval":
        return { tone: p.outcome === "applied" ? "pass" : "alert", title: `Approbation ${p.outcome === "applied" ? "appliquée" : "refusée"} : ${p.target_id}` };
      case "engine_unavailable":
        return { tone: "alert", title: "Moteur injoignable, l’arène attend", text: p.detail };
      case "arena_started":
        return { tone: "", title: "Arène démarrée", text: `${p.tasks} tâches · moteurs : ${(p.engines || []).join(", ")}` };
      default:
        return { tone: "", title: event.kind };
    }
  }

  function renderEvent(event) {
    const view = describe(event);
    const head = el("div", { className: "event-head" }, el("strong", { text: view.title }), el("time", { text: new Date(event.at).toLocaleTimeString("fr-FR"), attrs: { datetime: event.at } }));
    const item = el("li", { className: "event " + (view.tone || "") }, head);
    if (view.chip) item.append(el("span", { className: "chip " + view.chip[1], text: view.chip[0] }));
    if (view.text) item.append(el("p", { text: view.text }));
    if (view.extra) item.append(el("p", { className: "field-help", text: view.extra }));
    if (view.code) item.append(el("details", {}, el("summary", { text: view.codeLabel || "Voir le code" }), el("pre", { text: view.code })));
    if (view.failure) item.append(el("details", {}, el("summary", { text: "Sortie des tests" }), el("pre", { text: view.failure })));
    return item;
  }

  async function refreshOverview() {
    const data = await api("/v1/arena");
    if (!data.available) {
      q("#status").textContent = "L’arène n’a pas encore démarré sur ce serveur.";
      return;
    }
    notice("");
    renderStatus(data);
    renderProfiles(data.profiles || []);
    renderPackets(data.packets || []);
    if (!state.lastEventId && data.last_event_id) state.lastEventId = Math.max(0, data.last_event_id - 40);
  }

  async function refreshEvents() {
    const data = await api("/v1/arena/events?after=" + state.lastEventId);
    const feed = q("#feed");
    for (const event of data.events || []) {
      feed.prepend(renderEvent(event));
      state.lastEventId = Math.max(state.lastEventId, event.event_id);
    }
    while (feed.children.length > 200) feed.lastElementChild.remove();
  }

  async function start() {
    try {
      const session = await api("/v1/session");
      state.csrf = session.csrf_token || "";
      await refreshOverview();
      await refreshEvents();
      state.overviewTimer = setInterval(() => refreshOverview().catch(handle), 10000);
      state.eventTimer = setInterval(() => refreshEvents().catch(handle), 3000);
    } catch (error) {
      handle(error);
    }
  }

  function handle(error) {
    if (error.message === "unauthorized") {
      clearInterval(state.overviewTimer);
      clearInterval(state.eventTimer);
      q("#status").textContent = "Connecte-toi d’abord au chat, puis reviens sur cette page.";
      notice("Session absente ou expirée.");
      return;
    }
    notice("Erreur de lecture de l’arène : " + error.message);
  }

  start();
})();
