const state = {
  session: null,
  capability: null,
  tab: "brief",
  imageVersion: null,
  imageShot: null,
  videoVersion: null,
  imageDraftDirty: false,
  videoDraftDirty: false,
};
const $ = (id) => document.getElementById(id);

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined && text !== null) element.textContent = String(text);
  if (className) element.className = className;
  return element;
}

function message(text) { $("message").textContent = text || ""; }

function selectTab(name) {
  state.tab = name;
  document.querySelectorAll(".tab").forEach((button) => {
    const active = button.dataset.tab === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll(".view").forEach((view) => {
    const active = view.id === `view-${name}`;
    view.classList.toggle("active", active);
    view.hidden = !active;
  });
}

function renderIntro(session) {
  $("session-title").textContent = session.title;
  $("revision-label").textContent = `Revision ${session.revision}`;
  $("session-status").textContent = session.brief_status;
  $("brief-state").textContent = session.brief_status;
  const brief = session.brief || {};
  $("session-summary").textContent = brief.outcome || "Start with an idea, a reference, or an empty brief. The creative conversation shapes the prompt here.";
  $("media-count").textContent = String(session.references.length + session.previews.length + (session.assets || []).length);
}

function renderBrief(session) {
  const hasBrief = Object.keys(session.brief || {}).length > 0;
  $("empty-brief").hidden = hasBrief;
  $("brief-content").hidden = !hasBrief;
  if (!hasBrief) return;
  const fields = $("brief-fields");
  fields.replaceChildren();
  const order = ["outcome", "subject_action", "visual_priority", "frame", "camera", "blocking", "light", "styling", "production_design", "colour", "texture", "emotional_read"];
  const entries = [...order.filter((key) => session.brief[key] !== undefined), ...Object.keys(session.brief).filter((key) => !order.includes(key))];
  entries.forEach((key) => {
    const item = node("div", undefined, "brief-field");
    item.append(node("span", key.replaceAll("_", " ")), node("p", session.brief[key]));
    fields.append(item);
  });
  for (const [id, values, empty] of [
    ["lock-list", session.locks, "No continuity locks yet."],
    ["choice-list", session.open_choices, "No open scene choices."],
  ]) {
    const list = $(id);
    list.replaceChildren();
    (values.length ? values : [empty]).forEach((value) => list.append(node("li", value)));
  }
  const ledger = $("provenance-list");
  ledger.replaceChildren();
  if (!session.provenance.length) ledger.append(node("p", "No provenance notes yet.", "muted"));
  session.provenance.forEach((entry) => {
    const item = node("div", undefined, "provenance-item");
    item.append(node("strong", entry.kind), node("p", entry.text), node("small", entry.source));
    ledger.append(item);
  });
}

function selectedVersion(versions, requested) {
  return versions.find((item) => item.version === requested) || versions[versions.length - 1];
}

function renderImage(session) {
  const has = session.image_versions.length > 0;
  $("empty-image").hidden = has;
  $("image-content").hidden = !has;
  if (!has) return;
  const select = $("image-version");
  const previous = Number(select.value) || state.imageVersion || session.selected_image_version;
  const chosen = selectedVersion(session.image_versions, previous);
  state.imageVersion = chosen.version;
  select.replaceChildren();
  session.image_versions.forEach((version) => {
    const option = node("option", `Version ${version.version}`);
    option.value = String(version.version);
    select.append(option);
  });
  select.value = String(chosen.version);
  const shots = chosen.shots || [];
  $("image-shot-row").hidden = shots.length === 0;
  const shotSelect = $("image-shot");
  shotSelect.replaceChildren();
  shots.forEach((shot) => {
    const option = node("option", `${shot.id} · ${shot.title}`);
    option.value = shot.id;
    shotSelect.append(option);
  });
  const selectedShot = shots.find((shot) => shot.id === state.imageShot) || shots[0];
  if (selectedShot) {
    state.imageShot = selectedShot.id;
    shotSelect.value = selectedShot.id;
  } else state.imageShot = null;
  $("image-prompt").value = selectedShot ? selectedShot.prompt : chosen.prompt;
  const versionNote = chosen.note || `Agreed prompt version ${chosen.version}. Earlier versions remain available above.`;
  $("image-note").textContent = selectedShot ? `Selected frame: ${selectedShot.title}. ${versionNote}` : versionNote;
  const pending = session.drafts.filter((draft) => draft.target === "image" && draft.status === "pending");
  $("image-draft-state").textContent = pending.length ? `${pending.length} draft${pending.length === 1 ? "" : "s"} awaiting acceptance. Saved draft at revision ${pending[pending.length - 1].base_revision + 1}.` : "";
}

function renderVideo(session) {
  const has = session.video_versions.length > 0;
  $("empty-video").hidden = has;
  $("video-content").hidden = !has;
  if (!has) return;
  const select = $("video-version");
  const previous = Number(select.value) || state.videoVersion;
  const chosen = selectedVersion(session.video_versions, previous);
  state.videoVersion = chosen.version;
  select.replaceChildren();
  session.video_versions.forEach((version) => {
    const option = node("option", `Version ${version.version}`);
    option.value = String(version.version);
    select.append(option);
  });
  select.value = String(chosen.version);
  $("video-prompt").value = chosen.prompt;
  const meta = $("video-meta");
  meta.replaceChildren();
  [chosen.mode, `${chosen.duration} seconds`, `Image version ${chosen.source_image_version}`].forEach((item) => meta.append(node("span", item)));
  const pending = session.drafts.filter((draft) => draft.target === "video" && draft.status === "pending");
  $("video-draft-state").textContent = pending.length ? `${pending.length} draft${pending.length === 1 ? "" : "s"} awaiting acceptance. Saved draft at revision ${pending[pending.length - 1].base_revision + 1}.` : "";
}

function mediaCard(item, generated = false, saved = false) {
  const card = node("article", undefined, "media-card");
  const isVideo = item.source_kind === "supplied_video" || item.kind === "video" || /\.(mp4|mov)$/i.test(item.url || "");
  const media = node(isVideo ? "video" : "img");
  media.src = item.url;
  if (isVideo) {
    media.controls = true;
    media.preload = "metadata";
  } else {
    media.alt = saved ? item.label : generated ? "Generated local look study" : `${item.label}: ${item.role}`;
    media.loading = "lazy";
  }
  card.append(media);
  const body = node("div", undefined, "media-card-body");
  const previewTitle = `Look study for image v${item.prompt_version}${item.shot_id ? ` / frame ${item.shot_id}` : ""}`;
  body.append(node("strong", saved ? item.label : generated ? previewTitle : item.label));
  body.append(node("span", saved ? "Saved output · generated" : generated ? `${item.model} · ${item.status} · generated` : `${item.role} · supplied`));
  if (generated && item.limitations?.length) body.append(node("p", item.limitations.join(". ")));
  const link = node("a", "Open media");
  link.href = item.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  body.append(link);
  if (generated && !saved && item.status !== "promoted") {
    const button = node("button", "Promote As Visual Lock", "button");
    button.type = "button";
    button.addEventListener("click", () => sendEvent("promote_preview", { preview_id: item.id }));
    body.append(button);
  }
  card.append(body);
  return card;
}

function renderMedia(session) {
  const refs = $("reference-grid");
  refs.replaceChildren(...session.references.map((item) => mediaCard(item)));
  $("empty-references").hidden = session.references.length > 0;
  const previews = $("preview-grid");
  previews.replaceChildren(...session.previews.map((item) => mediaCard(item, true)));
  $("empty-previews").hidden = session.previews.length > 0;
  const assets = $("asset-grid");
  assets.replaceChildren(...(session.assets || []).map((item) => mediaCard(item, true, true)));
  $("empty-assets").hidden = Boolean(session.assets?.length);
  const cap = state.capability;
  $("request-preview").hidden = !cap?.available || !cap?.wholly_local || !session.image_versions.length;
  $("preview-capability").textContent = cap?.available && cap?.wholly_local
    ? `${cap.backend}: ${cap.model}. ${cap.reference_modes.join(", ")} preview. ${cap.limitations.join(". ")}.`
    : "No verified wholly local backend is active. Prompt work remains available.";
}

function render(session) {
  state.session = session;
  renderIntro(session);
  renderBrief(session);
  renderImage(session);
  renderVideo(session);
  renderMedia(session);
}

async function fetchSession() {
  const id = new URLSearchParams(location.search).get("session");
  const route = id ? `/api/session?id=${encodeURIComponent(id)}` : "/api/session";
  const response = await fetch(route, { cache: "no-store" });
  if (!response.ok) throw new Error("Could not load this workshop session");
  const session = await response.json();
  if (!id) history.replaceState(null, "", `/?session=${session.id}`);
  return session;
}

async function refresh() {
  try {
    const session = await fetchSession();
    if (!state.session || state.session.revision !== session.revision) render(session);
  } catch (error) { message(error.message); }
}

async function sendEvent(action, payload) {
  const session = state.session;
  if (!session) return;
  try {
    const response = await fetch("/api/event", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: session.id, expected_revision: session.revision, nonce: session.nonce, action, payload }),
    });
    const result = await response.json();
    if (response.status === 409 && result.current) {
      render(await fetchSession());
      message("The session changed. Review the newest version, then send your edit again.");
      return;
    }
    if (!response.ok) throw new Error(result.error || "The edit was not saved");
    render(result);
    message(action === "draft_edit" ? `Draft saved at revision ${result.revision}. The agreed prompt is unchanged.` : "Visual lock updated in the session.");
  } catch (error) { message(error.message); }
}

function sendDraft(target) {
  const field = $(target === "image" ? "image-draft" : "video-draft");
  const text = field.value.trim();
  if (!text) { message("Write an edit before sending a draft."); return; }
  const payload = { target, text, shot_id: target === "image" ? state.imageShot : undefined };
  const version = target === "image" ? state.imageVersion : state.videoVersion;
  if (target !== "image" || state.session.image_versions.length) payload.base_version = version;
  sendEvent("draft_edit", payload);
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
    $("manual-copy").hidden = true;
    message("Agreed prompt copied.");
  } catch {
    $("manual-copy").hidden = false;
    const field = $("manual-copy-text");
    field.value = value;
    field.focus();
    field.select();
    message("Clipboard unavailable. The agreed prompt is selected below for manual copying.");
  }
}

function download(value, kind, version) {
  const url = URL.createObjectURL(new Blob([value + "\n"], { type: "text/plain;charset=utf-8" }));
  const link = node("a");
  link.href = url;
  link.download = `vybe-check-${kind}-v${version}.txt`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function requestPreview() {
  const session = state.session;
  if (!session || !state.capability?.available || !state.capability?.wholly_local) return;
  const button = $("request-preview");
  button.disabled = true;
  message("Generating a local look study. The agreed prompt remains available.");
  try {
    const response = await fetch("/api/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: session.id, expected_revision: session.revision, nonce: session.nonce, prompt_version: state.imageVersion, shot_id: state.imageShot }),
    });
    const result = await response.json();
    if (response.status === 409 && result.current) {
      render(await fetchSession());
      message("The session changed. Review the newest version before requesting a study again.");
      return;
    }
    if (!response.ok) throw new Error(result.error || "Local preview failed");
    render(result);
    selectTab("references");
    message("Local look study saved as exploratory. Promote it only if it should guide the next version.");
  } catch (error) { message(error.message); }
  finally { button.disabled = false; }
}

async function start() {
  const tabs = [...document.querySelectorAll(".tab")];
  tabs.forEach((button, index) => {
    button.addEventListener("click", () => selectTab(button.dataset.tab));
    button.addEventListener("keydown", (event) => {
      const offsets = { ArrowRight: 1, ArrowLeft: -1 };
      let next;
      if (event.key in offsets) next = (index + offsets[event.key] + tabs.length) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault();
      selectTab(tabs[next].dataset.tab);
      tabs[next].focus();
    });
  });
  $("image-version").addEventListener("change", () => { state.imageVersion = Number($("image-version").value); renderImage(state.session); });
  $("image-shot").addEventListener("change", () => { state.imageShot = $("image-shot").value; renderImage(state.session); });
  $("video-version").addEventListener("change", () => { state.videoVersion = Number($("video-version").value); renderVideo(state.session); });
  $("send-image-draft").addEventListener("click", () => sendDraft("image"));
  $("send-video-draft").addEventListener("click", () => sendDraft("video"));
  $("copy-image").addEventListener("click", () => copyText($("image-prompt").value));
  $("copy-video").addEventListener("click", () => copyText($("video-prompt").value));
  $("download-image").addEventListener("click", () => download($("image-prompt").value, "image", state.imageVersion));
  $("download-video").addEventListener("click", () => download($("video-prompt").value, "video", state.videoVersion));
  $("request-preview").addEventListener("click", requestPreview);
  selectTab("brief");
  try {
    state.capability = await fetch("/api/capability", { cache: "no-store" }).then((response) => response.json());
    render(await fetchSession());
  } catch (error) { message(error.message); }
  setInterval(refresh, 4000);
  setInterval(async () => {
    try { state.capability = await fetch("/api/capability", { cache: "no-store" }).then((response) => response.json()); if (state.session) renderMedia(state.session); }
    catch { /* Text work continues when the local backend is unavailable. */ }
  }, 30000);
}

start();
