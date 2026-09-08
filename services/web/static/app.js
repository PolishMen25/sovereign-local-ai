/* Same-origin, dependency-free UI. No conversation or credential browser storage. */
"use strict";

(function () {
  const MAX_STREAM_CHARS = 524288;
  const MAX_ANSWER_CHARS = 45000;
  const ERROR_MESSAGES = {
    unauthorized: "Votre session a expiré. Reconnectez-vous.",
    authentication_failed: "Nom d’utilisateur ou mot de passe incorrect.",
    setup_unauthorized: "Le code d’installation est incorrect.",
    setup_refused: "Création du compte refusée. Vérifiez le nom et les critères du mot de passe.",
    invalid_request: "Ce message ne peut pas être envoyé. Vérifiez sa longueur.",
    conversation_not_found: "Cette conversation n’existe plus. Créez une nouvelle conversation.",
    not_found: "L’élément demandé n’existe plus.",
    busy: "L’assistant répond déjà à une demande. Réessayez dans un instant.",
    runtime_unavailable: "Le moteur local est indisponible. Votre historique reste accessible.",
    generation_failed: "Le moteur local n’a pas terminé sa réponse.",
    quality_gate_failed: "CORE-700M est encore en entraînement : sa sortie a été refusée car elle n’est pas exploitable. Sélectionnez BOOTSTRAP pour obtenir une réponse claire.",
    unknown_profile: "Ce profil d’assistant n’est pas disponible.",
  };

  function errorMessage(error) {
    return ERROR_MESSAGES[error.code] || (error.name === "TypeError"
      ? "Le serveur est injoignable. Vérifiez la connexion et réessayez."
      : error.message || "Une erreur est survenue.");
  }

  function engineLabel(value) {
    return value === "BOOTSTRAP" ? "BOOTSTRAP · modèle local provisoire"
      : value === "CORE-700M" ? "CORE-700M expérimental"
        : value === "" ? "Aucun moteur vérifié" : "Moteur indisponible";
  }

  async function readEventStream(body, onEvent) {
    if (!body || typeof body.getReader !== "function") throw new Error("La réponse progressive n’est pas disponible.");
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    let total = 0;
    let completed = false;
    const dispatch = (frame) => {
      let event = "message";
      const lines = [];
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) lines.push(line.slice(5).replace(/^ /, ""));
      }
      if (!lines.length) return;
      const payload = JSON.parse(lines.join("\n"));
      if (event === "completed") completed = true;
      onEvent(event, payload);
    };
    try {
      while (true) {
        const {value, done} = await reader.read();
        const text = decoder.decode(value, {stream: !done});
        total += text.length;
        if (total > MAX_STREAM_CHARS) throw new Error("La réponse dépasse la taille autorisée.");
        pending += text;
        let boundary;
        while ((boundary = /\r?\n\r?\n/.exec(pending)) !== null) {
          dispatch(pending.slice(0, boundary.index));
          pending = pending.slice(boundary.index + boundary[0].length);
        }
        if (done) break;
      }
      if (pending.trim()) dispatch(pending);
      if (!completed) throw new Error("La réponse a été interrompue. Consultez l’historique avant de renvoyer votre message.");
    } catch (error) {
      await reader.cancel().catch(() => {});
      throw error;
    } finally {
      reader.releaseLock();
    }
  }

  // Pure stream helpers are exercised with Node's built-in test runner.
  if (typeof module !== "undefined" && module.exports) module.exports = {readEventStream, engineLabel, errorMessage};
  if (typeof document === "undefined") return;

  const q = (id) => document.getElementById(id);
  const state = {csrf: "", conversation: "", engine: "unavailable", ragMode: "", busy: false, profiles: [], engines: []};

  function notice(message = "") {
    q("notice").textContent = message;
    q("notice").hidden = !message;
  }

  function showAuth(mode) {
    state.csrf = "";
    state.conversation = "";
    q("workspace").hidden = true;
    q("logout").hidden = true;
    q("username").textContent = "";
    q("messages").replaceChildren();
    q("conversations").replaceChildren();
    q("setup").hidden = mode !== "setup";
    q("login").hidden = mode !== "login";
    q("status").textContent = mode === "setup" ? "Première configuration" : "Connexion requise";
  }

  async function checkedResponse(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body) headers.set("Content-Type", "application/json");
    if (state.csrf && ["POST", "DELETE", "PUT", "PATCH"].includes(options.method)) headers.set("X-CSRF-Token", state.csrf);
    const result = await fetch(path, {...options, headers, credentials: "same-origin", cache: "no-store"});
    if (!result.ok) {
      const payload = await result.json().catch(() => ({}));
      const error = new Error(payload.answer || "La demande n’a pas abouti.");
      error.code = payload.error || (result.status === 503 ? "runtime_unavailable" : "");
      error.status = result.status;
      if (result.status === 401 && !["/v1/login", "/v1/setup"].includes(path)) showAuth("login");
      throw error;
    }
    return result;
  }

  async function api(path, options) {
    return (await checkedResponse(path, options)).json();
  }

  function updateEngine(engine = state.engine, ragMode = state.ragMode) {
    state.engine = engine;
    state.ragMode = ragMode;
    const rag = ragMode === "lexical" || ragMode === "lexical-only" ? "Recherche documentaire locale" : ragMode === "hybrid" ? "Recherche documentaire hybride locale" : "";
    q("engine-info").textContent = [engineLabel(engine), rag].filter(Boolean).join(" · ");
    q("status").textContent = state.busy ? "L’assistant prépare sa réponse…" : "Connecté · " + engineLabel(engine);
  }

  function setBusy(busy) {
    state.busy = busy;
    for (const id of ["new", "history", "engine", "profile", "logout"]) q(id).disabled = busy;
    q("send").disabled = busy || !q("engine").value;
    for (const button of q("conversations").querySelectorAll("button")) button.disabled = busy;
    q("export").disabled = busy || !state.conversation;
    q("delete").disabled = busy || !state.conversation;
    q("send").textContent = busy ? "Réponse en cours…" : "Envoyer";
    q("chat-form").setAttribute("aria-busy", String(busy));
    if (!q("workspace").hidden) updateEngine();
  }

  function scrollMessages(force = false) {
    const messages = q("messages");
    if (force || messages.scrollHeight - messages.scrollTop - messages.clientHeight < 180) messages.scrollTop = messages.scrollHeight;
  }

  function addMessage(role, content = "", engine = "") {
    q("welcome")?.remove();
    const article = document.createElement("article");
    article.className = "message " + (role === "user" ? "user" : "assistant");
    const label = document.createElement("p");
    label.className = "message-role";
    label.textContent = role === "user" ? "Vous" : "Assistant · " + (engine ? engineLabel(engine) : "moteur non enregistré");
    const text = document.createElement("div");
    text.className = "message-content";
    text.textContent = content;
    article.append(label, text);
    q("messages").append(article);
    return {article, label, text};
  }

  function showCitations(article, citations) {
    article.querySelector(".sources")?.remove();
    if (!Array.isArray(citations) || !citations.length) return;
    const details = document.createElement("details");
    details.className = "sources";
    const summary = document.createElement("summary");
    summary.textContent = "Sources locales consultées (" + Math.min(citations.length, 10) + ")";
    const list = document.createElement("ol");
    for (const source of citations.slice(0, 10)) {
      if (!source || typeof source !== "object") continue;
      const item = document.createElement("li");
      item.textContent = String(source.title || source.document_id || "Document").slice(0, 300);
      const provenance = document.createElement("span");
      provenance.className = "source-id";
      provenance.textContent = String(source.provenance_id || "Provenance indisponible").slice(0, 300);
      item.append(provenance);
      list.append(item);
    }
    details.append(summary, list);
    article.append(details);
  }

  function newConversation() {
    state.conversation = "";
    q("conversation-title").textContent = "Nouvelle conversation";
    q("messages").replaceChildren();
    const welcome = document.createElement("div");
    welcome.id = "welcome";
    welcome.className = "welcome";
    const title = document.createElement("h2");
    title.textContent = "Que voulez-vous faire aujourd’hui ?";
    const text = document.createElement("p");
    text.textContent = "Posez une question, préparez un projet ou demandez de l’aide sur du code.";
    welcome.append(title, text);
    q("messages").append(welcome);
    for (const item of q("conversations").querySelectorAll("button")) item.removeAttribute("aria-current");
    setBusy(false);
    q("message").focus();
  }

  async function refreshHistory() {
    const data = await api("/v1/conversations");
    q("conversations").replaceChildren();
    const conversations = Array.isArray(data.conversations) ? data.conversations.slice(0, 500) : [];
    if (!conversations.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "Vos conversations apparaîtront ici.";
      q("conversations").append(empty);
    }
    for (const conversation of conversations) {
      if (!/^[A-Za-z0-9_-]{8,80}$/.test(conversation.conversation_id)) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "conversation-item";
      button.disabled = state.busy;
      if (conversation.conversation_id === state.conversation) button.setAttribute("aria-current", "true");
      const title = document.createElement("span");
      title.className = "title";
      title.textContent = conversation.title;
      const time = document.createElement("time");
      const date = new Date(conversation.updated_at);
      time.textContent = Number.isNaN(date.valueOf()) ? "" : date.toLocaleString("fr-FR", {dateStyle: "short", timeStyle: "short"});
      if (!Number.isNaN(date.valueOf())) time.dateTime = date.toISOString();
      button.append(title, time);
      button.addEventListener("click", () => loadConversation(conversation.conversation_id));
      q("conversations").append(button);
    }
  }

  async function loadConversation(id) {
    if (state.busy) return;
    notice();
    setBusy(true);
    try {
      const data = await api("/v1/conversations/" + encodeURIComponent(id) + "/export");
      state.conversation = data.conversation_id;
      q("conversation-title").textContent = data.title;
      q("messages").replaceChildren();
      for (const message of data.messages || []) {
        if (!["user", "assistant"].includes(message.role)) continue;
        const rendered = addMessage(message.role, message.content, message.engine || "");
        showCitations(rendered.article, message.citations);
      }
      await refreshHistory();
      scrollMessages(true);
    } catch (error) { notice(errorMessage(error)); }
    finally { setBusy(false); }
  }

  function describeProfile() {
    const profile = state.profiles.find((item) => item.profile_id === q("profile").value);
    q("profile-description").textContent = profile?.description || "";
  }

  async function loadProfiles() {
    const data = await api("/v1/profiles");
    state.profiles = (data.profiles || []).filter((item) => /^[a-z][a-z0-9_-]{1,63}$/.test(item.profile_id)).slice(0, 100);
    if (!state.profiles.length) return;
    q("profile").replaceChildren();
    for (const profile of state.profiles) {
      const option = document.createElement("option");
      option.value = profile.profile_id;
      option.textContent = profile.display_name || profile.profile_id;
      q("profile").append(option);
    }
    if (state.profiles.some((item) => item.profile_id === "coordination")) q("profile").value = "coordination";
    describeProfile();
  }

  function describeEngine() {
    const engine = state.engines.find((item) => item.engine === q("engine").value);
    q("engine-description").textContent = engine?.description || "";
  }

  async function loadEngines() {
    const data = await api("/v1/engines");
    state.engines = (data.engines || []).filter((item) => item && typeof item.engine === "string" && typeof item.available === "boolean").slice(0, 8);
    if (!state.engines.length) return;
    q("engine").replaceChildren();
    const bootstrap = state.engines.find((item) => item.engine === "BOOTSTRAP");
    if (!bootstrap?.available) {
      const option = document.createElement("option");
      option.value = "";
      option.disabled = true;
      option.selected = true;
      option.textContent = "BOOTSTRAP indisponible · choisissez CORE seulement pour un test";
      q("engine").append(option);
    }
    for (const engine of state.engines) {
      const option = document.createElement("option");
      option.value = engine.engine;
      option.textContent = engineLabel(engine.engine) + (engine.available ? "" : " · en préparation");
      option.disabled = !engine.available;
      q("engine").append(option);
    }
    if (bootstrap?.available) q("engine").value = "BOOTSTRAP";
    describeEngine();
    updateEngine(q("engine").value);
    setBusy(state.busy);
  }

  async function enterWorkspace(session) {
    state.csrf = session.csrf_token;
    q("setup").hidden = true;
    q("login").hidden = true;
    q("workspace").hidden = false;
    q("logout").hidden = false;
    q("username").textContent = session.username || "";
    updateEngine(session.engine, session.rag_mode || "");
    newConversation();
    const results = await Promise.allSettled([refreshHistory(), loadProfiles(), loadEngines()]);
    for (const result of results) if (result.status === "rejected") notice(errorMessage(result.reason));
  }

  q("setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    notice();
    const password = q("setup-password").value;
    if (password !== q("setup-password-confirm").value) return notice("Les deux mots de passe ne correspondent pas.");
    if (new Set(password).size < 8) return notice("Utilisez au moins 8 caractères différents dans votre mot de passe.");
    q("setup-button").disabled = true;
    try {
      await api("/v1/setup", {method: "POST", headers: {"X-Setup-Token": q("setup-token").value}, body: JSON.stringify({username: q("setup-user").value, password})});
      q("login-user").value = q("setup-user").value;
      q("setup-form").reset();
      showAuth("login");
      notice("Votre compte est créé. Connectez-vous avec votre mot de passe.");
      q("login-password").focus();
    } catch (error) { notice(errorMessage(error)); }
    finally { q("setup-button").disabled = false; }
  });

  q("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    notice();
    q("login-button").disabled = true;
    try {
      const session = await api("/v1/login", {method: "POST", body: JSON.stringify({username: q("login-user").value, password: q("login-password").value})});
      q("login-password").value = "";
      state.csrf = session.csrf_token;
      // Reading the session also proves that the browser accepted the secure cookie.
      await enterWorkspace(await api("/v1/session"));
    } catch (error) { notice(errorMessage(error)); }
    finally { q("login-button").disabled = false; }
  });

  q("chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = q("message").value.trim();
    if (state.busy || !message) return;
    notice();
    setBusy(true);
    const request = {schema_version: "local-chat-request.v1", request_id: crypto.randomUUID().replaceAll("-", ""), profile_id: q("profile").value, engine: q("engine").value, message};
    if (state.conversation) request.conversation_id = state.conversation;
    else q("conversation-title").textContent = message.slice(0, 80);
    addMessage("user", message);
    const answer = addMessage("assistant", "", state.engine);
    answer.article.classList.add("pending");
    q("message").value = "";
    scrollMessages(true);
    const applyMetadata = (data) => {
      if (typeof data.conversation_id === "string" && /^[A-Za-z0-9_-]{8,80}$/.test(data.conversation_id)) state.conversation = data.conversation_id;
      if (data.engine) {
        updateEngine(data.engine, data.rag_mode || state.ragMode);
        answer.label.textContent = "Assistant · " + engineLabel(data.engine);
      }
    };
    const complete = (data) => {
      applyMetadata(data);
      if (typeof data.answer !== "string" || data.answer.length > MAX_ANSWER_CHARS) throw new Error("Le serveur a envoyé une réponse invalide.");
      answer.text.textContent = data.answer;
      showCitations(answer.article, data.citations);
    };
    try {
      const result = await checkedResponse("/v1/chat", {method: "POST", headers: {Accept: "text/event-stream"}, body: JSON.stringify(request)});
      if ((result.headers.get("Content-Type") || "").includes("text/event-stream")) {
        await readEventStream(result.body, (type, data) => {
          if (type === "metadata") applyMetadata(data);
          if (type === "delta") {
            if (typeof data.delta !== "string" || answer.text.textContent.length + data.delta.length > MAX_ANSWER_CHARS) throw new Error("Le serveur a envoyé une réponse invalide.");
            answer.text.textContent += data.delta;
          }
          if (type === "completed") complete(data);
          if (type === "error") {
            applyMetadata(data);
            const error = new Error(data.answer || "La réponse a été interrompue. Consultez l’historique avant de réessayer.");
            error.code = data.error;
            throw error;
          }
          scrollMessages();
        });
      } else complete(await result.json());
      await refreshHistory();
    } catch (error) {
      answer.article.classList.add("error");
      const detail = document.createElement("p");
      detail.className = "field-help";
      detail.textContent = errorMessage(error);
      answer.article.append(detail);
      notice(errorMessage(error));
      if (!q("workspace").hidden) await refreshHistory().catch(() => {});
    } finally {
      answer.article.classList.remove("pending");
      setBusy(false);
      if (!q("workspace").hidden) q("message").focus();
    }
  });

  q("engine").addEventListener("change", () => {
    describeEngine();
    updateEngine(q("engine").value);
    setBusy(state.busy);
  });

  q("message").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!state.busy) q("chat-form").requestSubmit();
    }
  });
  q("new").addEventListener("click", () => { if (!state.busy) { notice(); newConversation(); } });
  q("history").addEventListener("click", () => refreshHistory().catch((error) => notice(errorMessage(error))));
  q("profile").addEventListener("change", describeProfile);

  q("export").addEventListener("click", async () => {
    if (!state.conversation || state.busy) return;
    const id = state.conversation;
    setBusy(true);
    notice();
    try {
      const data = await api("/v1/conversations/" + encodeURIComponent(id) + "/export");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json;charset=utf-8"}));
      const link = document.createElement("a");
      link.href = url;
      link.download = "conversation-" + id + ".json";
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { notice(errorMessage(error)); }
    finally { setBusy(false); }
  });

  q("delete").addEventListener("click", () => {
    if (!state.conversation || state.busy) return;
    q("delete-title").textContent = q("conversation-title").textContent;
    q("delete-dialog").showModal();
    q("delete-cancel").focus();
  });
  q("delete-cancel").addEventListener("click", () => q("delete-dialog").close());
  q("delete-confirm").addEventListener("click", async () => {
    if (!state.conversation || state.busy) return;
    q("delete-dialog").close();
    setBusy(true);
    notice();
    try {
      await api("/v1/conversations/" + encodeURIComponent(state.conversation), {method: "DELETE"});
      newConversation();
      await refreshHistory();
      notice("Conversation supprimée de l’historique actif.");
    } catch (error) { notice(errorMessage(error)); }
    finally { setBusy(false); }
  });

  q("logout").addEventListener("click", async () => {
    if (state.busy) return;
    setBusy(true);
    try {
      await api("/v1/logout", {method: "POST", body: "{}"});
      q("message").value = "";
      showAuth("login");
      notice();
    } catch (error) { notice(errorMessage(error)); }
    finally { setBusy(false); }
  });

  async function start() {
    try {
      const setup = await api("/v1/setup-status");
      if (setup.setup_required) return showAuth("setup");
      await enterWorkspace(await api("/v1/session"));
    } catch (error) {
      if (error.status === 401) showAuth("login");
      else { q("status").textContent = "Connexion au serveur impossible"; notice(errorMessage(error)); }
    }
  }
  start();
}());
