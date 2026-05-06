"use strict";

const els = {
  messageList: document.querySelector("#messageList"),
  composerForm: document.querySelector("#composerForm"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  attachmentButton: document.querySelector("#attachmentButton"),
  fileInput: document.querySelector("#fileInput"),
  pendingAttachment: document.querySelector("#pendingAttachment"),
  pendingPreview: document.querySelector("#pendingPreview"),
  pendingName: document.querySelector("#pendingName"),
  pendingMeta: document.querySelector("#pendingMeta"),
  removeAttachmentButton: document.querySelector("#removeAttachmentButton"),
  endpointInput: document.querySelector("#endpointInput"),
  scenarioSelect: document.querySelector("#scenarioSelect"),
  scenarioParamList: document.querySelector("#scenarioParamList"),
  conversationInput: document.querySelector("#conversationInput"),
  userInput: document.querySelector("#userInput"),
  evalPresetManager: document.querySelector("#evalPresetManager"),
  evalPresetStatus: document.querySelector("#evalPresetStatus"),
  evalTagList: document.querySelector("#evalTagList"),
  feedbackTagList: document.querySelector("#feedbackTagList"),
  feedbackText: document.querySelector("#feedbackText"),
  submitFeedbackButton: document.querySelector("#submitFeedbackButton"),
  newConversationButton: document.querySelector("#newConversationButton"),
  exportJsonlButton: document.querySelector("#exportJsonlButton"),
  connectionPill: document.querySelector("#connectionPill"),
  phoneStatus: document.querySelector("#phoneStatus"),
  mockStatePanel: document.querySelector("#mockStatePanel"),
  toolLedgerPanel: document.querySelector("#toolLedgerPanel"),
  scenarioQuickActions: document.querySelector("#scenarioQuickActions"),
};

const evalTagOptions = [
  { value: "eval:candidate", label: "Candidate", group: "Curation" },
  { value: "eval:needs-review", label: "Needs review", group: "Curation" },
  { value: "eval:dataset-ready", label: "Dataset ready", group: "Curation" },
  { value: "eval:regression", label: "Regression", group: "Curation" },
  { value: "eval:discarded", label: "Discarded", group: "Curation" },
  { value: "sales:new-lead", label: "New lead", group: "Sales task" },
  { value: "sales:qualification", label: "Qualification", group: "Sales task" },
  { value: "sales:activation", label: "Activation", group: "Sales task" },
  { value: "sales:payment", label: "Payment", group: "Sales task" },
  { value: "sales:follow-up", label: "Follow-up", group: "Sales task" },
  { value: "sales:opt-out", label: "Opt-out", group: "Sales task" },
  { value: "sales:human-review", label: "Human review", group: "Sales task" },
  { value: "risk:prompt-injection", label: "Prompt injection", group: "Risk" },
  { value: "quality:state-mutation", label: "State mutation", group: "Evidence" },
  { value: "quality:multi-turn", label: "Multi-turn", group: "Evidence" },
];

const legacyEvalTagAliases = {
  "eval:missing-data": "sales:qualification",
  "eval:confirmation": "quality:state-mutation",
  "eval:multi-turn": "quality:multi-turn",
  "eval:error-recovery": "eval:needs-review",
};

const feedbackTagOptions = [
  { value: "manual:pass", label: "Pass" },
  { value: "manual:partial", label: "Partial" },
  { value: "manual:fail", label: "Fail" },
  { value: "manual:needs-review", label: "Needs review" },
  { value: "manual:wrong-state", label: "Wrong state" },
  { value: "manual:missing-data", label: "Missing data" },
  { value: "manual:good-handoff", label: "Good handoff" },
  { value: "manual:unsafe", label: "Unsafe" },
];

const storageKeys = {
  endpoint: "sumampa-demo-endpoint",
  conversationId: "sumampa-demo-conversation-id",
  userId: "sumampa-demo-user-id",
  evalTag: "sumampa-demo-eval-tag",
  evalTags: "sumampa-demo-eval-tags",
  evalTagsByConversation: "sumampa-demo-eval-tags-by-conversation",
  scenarioId: "sumampa-demo-scenario-id",
  scenarioParams: "sumampa-demo-scenario-params",
};

const scenarioParamLabels = {
  control_state: "Control",
  commercial_state: "Odoo commercial",
  payment_state: "Odoo payment",
  subscription_state: "Odoo subscription",
  activation_link_status: "Activation link",
  contact_role: "Contact role",
  followup_state: "Follow-up",
};

const state = {
  pendingAttachment: null,
  sending: false,
  healthTimer: null,
  resizeTimer: null,
  evalTags: [],
  feedbackTags: [],
  presetLocked: false,
  conversationStarted: false,
  transcript: [],
  scenarioCatalog: null,
  selectedScenarioId: "",
  scenarioParams: {},
  mockState: null,
  toolLedger: [],
};

async function init() {
  els.endpointInput.value = normalizeEndpoint(
    localStorage.getItem(storageKeys.endpoint) || defaultMessagesEndpoint(),
  );
  els.conversationInput.value =
    localStorage.getItem(storageKeys.conversationId) || buildConversationId();
  els.userInput.value = localStorage.getItem(storageKeys.userId) || els.userInput.value;
  state.scenarioParams = readScenarioParams();
  state.evalTags = [];
  localStorage.removeItem(storageKeys.evalTag);
  localStorage.removeItem(storageKeys.evalTags);
  renderEvalTags();
  renderFeedbackTags();
  renderMockState();

  bindEvents();
  await loadScenarios();
  startConversation();
  checkBackendHealth();
  state.healthTimer = window.setInterval(checkBackendHealth, 8000);
}

function bindEvents() {
  els.composerForm.addEventListener("submit", handleSubmit);
  els.attachmentButton.addEventListener("click", () => els.fileInput.click());
  els.fileInput.addEventListener("change", handleFileInput);
  els.removeAttachmentButton.addEventListener("click", clearPendingAttachment);
  els.newConversationButton.addEventListener("click", startNewConversation);
  els.exportJsonlButton.addEventListener("click", exportConversationJsonl);
  els.submitFeedbackButton.addEventListener("click", submitManualFeedback);
  els.scenarioSelect.addEventListener("change", handleScenarioChange);

  [els.endpointInput, els.userInput].forEach((input) => {
    input.addEventListener("input", () => {
      persistControls();
      if (input === els.endpointInput) {
        checkBackendHealth();
        loadScenarios();
      }
    });
  });

  els.conversationInput.addEventListener("input", () => {
    localStorage.setItem(storageKeys.conversationId, els.conversationInput.value.trim());
  });
  els.conversationInput.addEventListener("change", () => {
    state.evalTags = [];
    renderEvalTags();
    persistControls();
  });

  document.querySelectorAll("[data-message]").forEach((button) => {
    button.addEventListener("click", () => {
      els.messageInput.value = button.dataset.message;
      autoSizeComposer();
      els.messageInput.focus();
    });
  });

  els.messageInput.addEventListener("input", autoSizeComposer);
  els.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      els.composerForm.requestSubmit();
    }
  });

  document.addEventListener("dragover", (event) => {
    event.preventDefault();
    document.body.classList.add("drop-active");
  });

  document.addEventListener("dragleave", (event) => {
    if (!event.relatedTarget) {
      document.body.classList.remove("drop-active");
    }
  });

  document.addEventListener("drop", async (event) => {
    event.preventDefault();
    document.body.classList.remove("drop-active");
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      await setPendingAttachment(file);
    }
  });

  window.addEventListener("resize", () => {
    window.clearTimeout(state.resizeTimer);
    state.resizeTimer = window.setTimeout(scrollMessagesToBottom, 80);
  });
}

function persistControls() {
  els.endpointInput.value = normalizeEndpoint(els.endpointInput.value.trim());
  localStorage.setItem(storageKeys.endpoint, els.endpointInput.value.trim());
  localStorage.setItem(storageKeys.conversationId, els.conversationInput.value.trim());
  localStorage.setItem(storageKeys.userId, els.userInput.value.trim());
  localStorage.setItem(storageKeys.scenarioId, state.selectedScenarioId);
  localStorage.setItem(storageKeys.scenarioParams, JSON.stringify(state.scenarioParams));
  localStorage.removeItem(storageKeys.evalTag);
  localStorage.removeItem(storageKeys.evalTags);
  localStorage.removeItem(storageKeys.evalTagsByConversation);
}

function defaultMessagesEndpoint() {
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    return `${window.location.origin}/demo/api/messages`;
  }
  return els.endpointInput.value;
}

function normalizeEndpoint(value) {
  const fallback = defaultMessagesEndpoint();
  const rawValue = String(value || "").trim() || fallback;
  try {
    const url = new URL(rawValue);
    if (url.pathname.replace(/\/+$/, "") === "/api/v1/messages") {
      if (window.location.protocol === "http:" || window.location.protocol === "https:") {
        return `${window.location.origin}/demo/api/messages`;
      }
      url.pathname = "/demo/api/messages";
      return url.toString();
    }
    return rawValue;
  } catch {
    return fallback;
  }
}

async function loadScenarios() {
  const scenariosUrl = buildScenariosUrl();
  if (!scenariosUrl) {
    renderScenarioFallback("Endpoint invalido");
    return;
  }

  try {
    const response = await fetch(scenariosUrl, { method: "GET", cache: "no-store" });
    const body = await readJsonBody(response);
    if (!response.ok || !body) {
      throw new Error(body?.message || body?.detail || `HTTP ${response.status}`);
    }
    state.scenarioCatalog = body;
    const storedScenario = localStorage.getItem(storageKeys.scenarioId);
    const firstScenario = body.scenarios?.[0]?.scenario_id || "";
    state.selectedScenarioId = body.scenarios?.some(
      (scenario) => scenario.scenario_id === storedScenario,
    )
      ? storedScenario
      : firstScenario;
    normalizeScenarioParams();
    renderScenarioControls();
    renderQuickMessages();
    persistControls();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    renderScenarioFallback(message);
  }
}

function renderScenarioFallback(message) {
  els.scenarioSelect.textContent = "";
  const option = document.createElement("option");
  option.value = "";
  option.textContent = "Sin escenarios";
  els.scenarioSelect.append(option);
  els.scenarioParamList.textContent = "";
  appendMessage({ role: "system", text: `No pude cargar escenarios: ${message}` });
}

function renderScenarioControls() {
  const catalog = state.scenarioCatalog;
  if (!catalog) {
    return;
  }
  els.scenarioSelect.textContent = "";
  catalog.scenarios.forEach((scenario) => {
    const option = document.createElement("option");
    option.value = scenario.scenario_id;
    option.textContent = scenario.label;
    option.selected = scenario.scenario_id === state.selectedScenarioId;
    els.scenarioSelect.append(option);
  });

  els.scenarioParamList.textContent = "";
  Object.entries(catalog.params || {}).forEach(([name, definition]) => {
    const label = document.createElement("label");
    label.className = "field";

    const labelText = document.createElement("span");
    labelText.textContent = scenarioParamLabels[name] || definition.label || name;

    const select = document.createElement("select");
    select.dataset.scenarioParam = name;
    (definition.options || []).forEach((optionDef) => {
      const option = document.createElement("option");
      option.value = optionDef.value;
      option.textContent = optionDef.label;
      option.selected = state.scenarioParams[name] === optionDef.value;
      select.append(option);
    });
    select.addEventListener("change", () => {
      state.scenarioParams[name] = select.value;
      persistControls();
      resetConversationForScenarioChange();
    });

    label.append(labelText, select);
    els.scenarioParamList.append(label);
  });
}

function handleScenarioChange() {
  state.selectedScenarioId = els.scenarioSelect.value;
  state.scenarioParams = {};
  normalizeScenarioParams();
  renderScenarioControls();
  renderQuickMessages();
  persistControls();
  resetConversationForScenarioChange();
}

function normalizeScenarioParams() {
  const scenario = selectedScenario();
  if (!scenario || !state.scenarioCatalog) {
    return;
  }
  const params = { ...(scenario.default_params || {}), ...state.scenarioParams };
  Object.entries(state.scenarioCatalog.params || {}).forEach(([name, definition]) => {
    const allowed = (definition.options || []).map((option) => option.value);
    if (!allowed.includes(params[name])) {
      params[name] = scenario.default_params?.[name] || allowed[0] || "";
    }
  });
  state.scenarioParams = params;
}

function selectedScenario() {
  return state.scenarioCatalog?.scenarios?.find(
    (scenario) => scenario.scenario_id === state.selectedScenarioId,
  );
}

function renderQuickMessages() {
  const scenario = selectedScenario();
  const messages = scenario?.quick_messages?.length
    ? scenario.quick_messages
    : [
        "Me interesa comprar por mayor, como seguimos?",
        "Cual es el proximo paso?",
      ];
  const buttons = Array.from(els.scenarioQuickActions.querySelectorAll("button"));
  buttons.forEach((button, index) => {
    const message = messages[index % messages.length];
    button.dataset.message = message;
    button.textContent = message;
  });
}

function readScenarioParams() {
  const stored = localStorage.getItem(storageKeys.scenarioParams);
  if (!stored) {
    return {};
  }
  try {
    const parsed = JSON.parse(stored);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    localStorage.removeItem(storageKeys.scenarioParams);
    return {};
  }
}

function resetConversationForScenarioChange() {
  startNewConversation();
}

function toggleEvalTag(tag) {
  if (state.presetLocked) {
    return;
  }
  if (state.evalTags.includes(tag)) {
    state.evalTags = state.evalTags.filter((item) => item !== tag);
  } else {
    state.evalTags = [...state.evalTags, tag];
  }
  renderEvalTags();
  persistControls();
}

function renderEvalTags() {
  els.evalTagList.textContent = "";
  els.evalPresetManager.dataset.locked = String(state.presetLocked);
  els.evalPresetStatus.textContent = state.presetLocked
    ? "locked"
    : state.evalTags.length
      ? "selected"
      : "required";
  els.evalPresetStatus.dataset.status = state.presetLocked
    ? "locked"
    : state.evalTags.length
      ? "ok"
      : "required";
  let currentGroup = "";
  evalTagOptions.forEach((option) => {
    if (option.group !== currentGroup) {
      currentGroup = option.group;
      const group = document.createElement("span");
      group.className = "tag-group-label";
      group.textContent = currentGroup;
      els.evalTagList.append(group);
    }
    const selected = state.evalTags.includes(option.value);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-pill";
    button.dataset.selected = String(selected);
    button.setAttribute("aria-pressed", String(selected));
    button.disabled = state.presetLocked;
    button.title = option.value;
    button.textContent = option.label;
    button.addEventListener("click", () => toggleEvalTag(option.value));
    els.evalTagList.append(button);
  });
}

function toggleFeedbackTag(tag) {
  if (state.feedbackTags.includes(tag)) {
    state.feedbackTags = state.feedbackTags.filter((item) => item !== tag);
  } else {
    state.feedbackTags = [...state.feedbackTags, tag];
  }
  renderFeedbackTags();
}

function renderFeedbackTags() {
  els.feedbackTagList.textContent = "";
  feedbackTagOptions.forEach((option) => {
    const selected = state.feedbackTags.includes(option.value);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-pill";
    button.dataset.selected = String(selected);
    button.setAttribute("aria-pressed", String(selected));
    button.title = option.value;
    button.textContent = option.label;
    button.addEventListener("click", () => toggleFeedbackTag(option.value));
    els.feedbackTagList.append(button);
  });
}

function normalizeEvalTags(tags) {
  const normalized = [];
  tags.forEach((tag) => {
    const value = normalizeEvalTag(tag);
    if (value && !normalized.includes(value)) {
      normalized.push(value);
    }
  });
  return normalized;
}

function normalizeEvalTag(tag) {
  const rawValue = String(tag || "").trim().slice(0, 200);
  const value = legacyEvalTagAliases[rawValue] || rawValue;
  return evalTagOptions.some((option) => option.value === value) ? value : "";
}

function startConversation() {
  state.pendingAttachment = null;
  state.transcript = [];
  state.conversationStarted = false;
  state.presetLocked = false;
  state.feedbackTags = [];
  clearPendingAttachment();
  els.messageList.textContent = "";
  els.feedbackText.value = "";
  renderEvalTags();
  renderFeedbackTags();
}

function startNewConversation(options = {}) {
  if (options.syncReset !== false) {
    resetBackendConversation(els.conversationInput.value.trim()).catch(() => {});
  }
  els.conversationInput.value = buildConversationId();
  state.evalTags = [];
  state.mockState = null;
  state.toolLedger = [];
  els.messageInput.value = "";
  autoSizeComposer();
  startConversation();
  renderMockState();
  renderEvalTags();
  persistControls();
  els.messageInput.focus();
}

async function handleFileInput(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) {
    return;
  }
  await setPendingAttachment(file);
}

async function setPendingAttachment(file) {
  const maxBytes = 25 * 1024 * 1024;
  if (file.size > maxBytes) {
    appendMessage({
      role: "system",
      text: "El archivo supera 25 MB, que es el limite local del backend.",
    });
    return;
  }

  const dataUrl = await readFileAsDataUrl(file);
  const base64 = dataUrl.split(",", 2)[1] || "";
  state.pendingAttachment = {
    filename: file.name || "factura.jpg",
    mimeType: file.type || guessMimeType(file.name),
    size: file.size,
    dataUrl,
    contentBase64: base64,
  };
  renderPendingAttachment();
}

function renderPendingAttachment() {
  const attachment = state.pendingAttachment;
  if (!attachment) {
    clearPendingAttachment();
    return;
  }

  els.pendingPreview.textContent = "";
  if (attachment.mimeType.startsWith("image/")) {
    const img = document.createElement("img");
    img.alt = "";
    img.src = attachment.dataUrl;
    els.pendingPreview.append(img);
  } else {
    const icon = document.createElement("div");
    icon.className = "file-icon";
    icon.textContent = attachment.mimeType.includes("pdf") ? "PDF" : "TXT";
    els.pendingPreview.append(icon);
  }

  els.pendingName.textContent = attachment.filename;
  els.pendingMeta.textContent = `${attachment.mimeType} - ${formatBytes(attachment.size)}`;
  els.pendingAttachment.classList.remove("is-hidden");
}

function clearPendingAttachment() {
  state.pendingAttachment = null;
  els.pendingPreview.textContent = "";
  els.pendingName.textContent = "";
  els.pendingMeta.textContent = "";
  els.pendingAttachment.classList.add("is-hidden");
}

async function handleSubmit(event) {
  event.preventDefault();
  if (state.sending) {
    return;
  }

  const text = els.messageInput.value.trim();
  const attachment = state.pendingAttachment;
  if (!text && !attachment) {
    return;
  }
  if (!state.conversationStarted && !state.evalTags.length) {
    appendMessage({
      role: "system",
      text: "Selecciona al menos un Evals preset antes de comenzar.",
    });
    return;
  }

  state.sending = true;
  state.conversationStarted = true;
  state.presetLocked = true;
  renderEvalTags();
  setComposerDisabled(true);

  appendMessage({ role: "user", text, attachment });
  els.messageInput.value = "";
  autoSizeComposer();
  clearPendingAttachment();

  const payload = buildPayload({ text, attachment });
  showTyping();
  setConnectionLabel("enviando", "checking");

  try {
    const body = await sendToBackend(payload);
    hideTyping();
    const replies = extractReplyTexts(body);
    replies.forEach((reply) => appendMessage({ role: "assistant", text: reply }));
    updateMockStateFromResponse(body);
    setConnectionLabel("online", "ok");
  } catch (error) {
    hideTyping();
    const message = error instanceof Error ? error.message : String(error);
    appendMessage({
      role: "system",
      text: `Backend local no respondio: ${message}`,
    });
    setConnectionLabel("offline", "error");
  } finally {
    state.sending = false;
    setComposerDisabled(false);
    els.messageInput.focus();
  }
}

function buildPayload({ text, attachment }) {
  const now = new Date();
  const conversationId = els.conversationInput.value.trim() || buildConversationId();
  const userId = els.userInput.value.trim() || "demo-user-001";
  els.conversationInput.value = conversationId;
  els.userInput.value = userId;
  persistControls();

  return {
    conversation_id: conversationId,
    channel: "whatsapp",
    user_id: userId,
    text,
    scenario_id: state.selectedScenarioId,
    scenario_params: { ...state.scenarioParams },
    eval_tags: state.evalTags.slice(),
    attachments: attachment
      ? [
          {
            filename: attachment.filename,
            mime_type: attachment.mimeType,
            content_base64: attachment.contentBase64,
          },
        ]
      : [],
    context: {
      demo: true,
      demo_sales: true,
      evals_preset: state.evalTags.slice(),
      transport_profile: "whatsapp-mobile",
      locale: "es-AR",
      client_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      wa_message_id: `wamid.demo-${now.getTime()}`,
      timestamp: now.toISOString(),
      ui: {
        source: "demo/static-whatsapp",
        has_invoice_photo: Boolean(attachment),
      },
    },
  };
}

async function sendToBackend(payload) {
  const endpoint = els.endpointInput.value.trim();
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const body = await readJsonBody(response);
  if (!response.ok) {
    throw new Error(body?.message || body?.detail || `HTTP ${response.status}`);
  }

  return body;
}

function extractReplyTexts(body) {
  const messages = Array.isArray(body?.messages) ? body.messages : [];
  if (!messages.length) {
    return ["El backend respondio sin mensajes."];
  }
  return messages.map((message) => message.text || "").filter(Boolean);
}

function updateMockStateFromResponse(body) {
  if (!body || typeof body !== "object") {
    return;
  }
  if (body.state) {
    state.mockState = body.state;
  }
  if (Array.isArray(body.recent_tool_calls)) {
    state.toolLedger = [...state.toolLedger, ...body.recent_tool_calls].slice(-12);
  } else if (state.mockState?.tool_ledger) {
    state.toolLedger = state.mockState.tool_ledger.slice(-12);
  }
  renderMockState();
}

function renderMockState() {
  els.mockStatePanel.textContent = "";
  els.toolLedgerPanel.textContent = "";

  if (!state.mockState) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Sin turnos todavia.";
    els.mockStatePanel.append(empty);
    return;
  }

  const lead = state.mockState.lead || {};
  const payment = state.mockState.payment || {};
  const subscription = state.mockState.subscription || {};
  const activation = state.mockState.activation || {};
  const followup = state.mockState.followup || {};
  [
    ["Lead", lead.name || lead.lead_id || "-"],
    ["Control", lead.control_state || "-"],
    ["Commercial", lead.commercial_state || "-"],
    ["Role", lead.contact_role || "-"],
    ["Payment", payment.state || "-"],
    ["Subscription", subscription.state || "-"],
    ["Activation", activation.link_status || "-"],
    ["Follow-up", `${followup.state || "-"} (${followup.count || 0})`],
    ["Tags", (lead.tags || []).join(", ") || "-"],
    ["Interest", (lead.interest_tags || []).join(", ") || "-"],
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "state-item";
    const key = document.createElement("span");
    key.textContent = label;
    const val = document.createElement("strong");
    val.textContent = String(value);
    item.append(key, val);
    els.mockStatePanel.append(item);
  });

  const toolCalls = state.toolLedger.length
    ? state.toolLedger
    : state.mockState.tool_ledger || [];
  if (!toolCalls.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Sin tools.";
    els.toolLedgerPanel.append(empty);
    return;
  }

  toolCalls.slice(-8).reverse().forEach((call) => {
    const row = document.createElement("div");
    row.className = "tool-row";
    const name = document.createElement("strong");
    name.textContent = call.tool || "tool";
    const meta = document.createElement("span");
    const action = call.arguments?.action || call.result?.action || "";
    const mutationCount = Array.isArray(call.mutations) ? call.mutations.length : 0;
    meta.textContent = [action, mutationCount ? `${mutationCount} changes` : ""]
      .filter(Boolean)
      .join(" - ");
    row.append(name, meta);
    els.toolLedgerPanel.append(row);
  });
}

async function readJsonBody(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function checkBackendHealth() {
  const healthUrl = buildHealthUrl();
  if (!healthUrl) {
    setConnectionLabel("endpoint invalido", "error");
    return;
  }

  setConnectionLabel("checando", "checking");
  try {
    const response = await fetch(healthUrl, {
      method: "GET",
      cache: "no-store",
    });
    setConnectionLabel(response.ok ? "online" : "offline", response.ok ? "ok" : "error");
  } catch {
    setConnectionLabel("offline", "error");
  }
}

function buildHealthUrl() {
  try {
    const endpoint = new URL(els.endpointInput.value.trim());
    return `${endpoint.origin}/health`;
  } catch {
    return null;
  }
}

function buildScenariosUrl() {
  try {
    const endpoint = new URL(els.endpointInput.value.trim());
    const endpointPath = endpoint.pathname.replace(/\/+$/, "");
    endpoint.pathname = endpointPath.endsWith("/messages")
      ? `${endpointPath.slice(0, -"/messages".length)}/scenarios`
      : `${endpointPath}/scenarios`;
    endpoint.search = "";
    endpoint.hash = "";
    return endpoint.toString();
  } catch {
    return null;
  }
}

function buildResetUrl(conversationId) {
  try {
    const endpoint = new URL(els.endpointInput.value.trim());
    const endpointPath = endpoint.pathname.replace(/\/+$/, "");
    const basePath = endpointPath.endsWith("/messages")
      ? endpointPath.slice(0, -"/messages".length)
      : endpointPath;
    endpoint.pathname = `${basePath}/conversations/${encodeURIComponent(conversationId)}/reset`;
    endpoint.search = "";
    endpoint.hash = "";
    return endpoint.toString();
  } catch {
    return null;
  }
}

async function resetBackendConversation(conversationId) {
  if (!conversationId) {
    return;
  }
  const resetUrl = buildResetUrl(conversationId);
  if (!resetUrl) {
    return;
  }
  await fetch(resetUrl, { method: "POST" });
}

function buildExportUrl(conversationId) {
  try {
    const endpoint = new URL(els.endpointInput.value.trim());
    const endpointPath = endpoint.pathname.replace(/\/+$/, "");
    const basePath = endpointPath.endsWith("/messages")
      ? endpointPath.slice(0, -"/messages".length)
      : endpointPath;
    endpoint.pathname = `${basePath}/conversations/${encodeURIComponent(
      conversationId,
    )}/export.jsonl`;
    endpoint.search = "";
    endpoint.hash = "";
    return endpoint.toString();
  } catch {
    return null;
  }
}

function buildFeedbackUrl(conversationId) {
  try {
    const endpoint = new URL(els.endpointInput.value.trim());
    const endpointPath = endpoint.pathname.replace(/\/+$/, "");
    const basePath = endpointPath.endsWith("/messages")
      ? endpointPath.slice(0, -"/messages".length)
      : endpointPath;
    endpoint.pathname = `${basePath}/conversations/${encodeURIComponent(
      conversationId,
    )}/feedback`;
    endpoint.search = "";
    endpoint.hash = "";
    return endpoint.toString();
  } catch {
    return null;
  }
}

async function exportConversationJsonl() {
  const conversationId = els.conversationInput.value.trim();
  const exportUrl = buildExportUrl(conversationId);
  if (!conversationId || !exportUrl) {
    appendMessage({ role: "system", text: "No hay conversacion valida para exportar." });
    return;
  }

  try {
    const response = await fetch(exportUrl, { method: "GET", cache: "no-store" });
    const body = await response.text();
    if (!response.ok) {
      throw new Error(body || `HTTP ${response.status}`);
    }
    saveTextFile(
      `sumampa-demo-${conversationId}.jsonl`,
      body,
      "application/x-ndjson;charset=utf-8",
    );
    appendMessage({ role: "system", text: "JSONL exportado para dataset local." });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    appendMessage({ role: "system", text: `No pude exportar JSONL: ${message}` });
  }
}

async function submitManualFeedback() {
  const conversationId = els.conversationInput.value.trim();
  const feedbackUrl = buildFeedbackUrl(conversationId);
  const feedbackText = els.feedbackText.value.trim();
  if (!conversationId || !feedbackUrl) {
    appendMessage({ role: "system", text: "No hay conversacion valida para feedback." });
    return;
  }
  if (!state.feedbackTags.length && !feedbackText) {
    appendMessage({
      role: "system",
      text: "Agrega un feedback tag o una nota antes de guardar feedback.",
    });
    return;
  }

  const userId = els.userInput.value.trim() || "demo-user-001";
  try {
    const response = await fetch(feedbackUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        channel: "whatsapp",
        feedback_tags: state.feedbackTags.slice(),
        feedback_text: feedbackText,
        context: {
          source: "demo/manual-feedback",
          timestamp: new Date().toISOString(),
          transcript: buildTranscriptSnapshot(),
          evals_preset: state.evalTags.slice(),
        },
      }),
    });
    const body = await readJsonBody(response);
    if (!response.ok) {
      throw new Error(body?.message || body?.detail || `HTTP ${response.status}`);
    }
    appendMessage({ role: "system", text: "Manual feedback guardado." });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    appendMessage({ role: "system", text: `No pude guardar feedback: ${message}` });
  }
}

function saveTextFile(filename, text, mimeType) {
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function appendMessage(message) {
  const timestamp = new Date();
  recordTranscriptMessage(message, timestamp);

  const row = document.createElement("article");
  row.className = `message ${message.role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (message.attachment) {
    bubble.append(buildAttachmentNode(message.attachment));
  }

  if (message.text) {
    const text = document.createElement("div");
    text.className = "bubble-text";
    text.textContent = message.text;
    bubble.append(text);
  }

  const time = document.createElement("div");
  time.className = "message-time";
  time.append(document.createTextNode(formatTime(timestamp)));
  if (message.role === "user") {
    const check = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#icon-check");
    check.append(use);
    time.append(check);
  }
  bubble.append(time);

  row.append(bubble);
  els.messageList.append(row);
  scrollMessagesToBottom();
}

function recordTranscriptMessage(message, timestamp) {
  const text = String(message.text || "").trim();
  const attachments = message.attachment ? [attachmentMetadata(message.attachment)] : [];
  if (!text && !attachments.length) {
    return;
  }
  const role = ["user", "assistant", "system"].includes(message.role) ? message.role : "system";
  state.transcript.push({
    role,
    text,
    attachments,
    timestamp: timestamp.toISOString(),
  });
  state.transcript = state.transcript.slice(-80);
}

function buildTranscriptSnapshot() {
  return state.transcript.map((message) => ({
    role: message.role,
    text: message.text,
    attachments: message.attachments.map((attachment) => ({ ...attachment })),
    timestamp: message.timestamp,
  }));
}

function attachmentMetadata(attachment) {
  return {
    filename: attachment.filename,
    mime_type: attachment.mimeType,
    size_bytes: attachment.size,
    has_content_base64: Boolean(attachment.contentBase64),
    source: "demo/static-whatsapp",
  };
}

function buildAttachmentNode(attachment) {
  const wrapper = document.createElement("div");
  wrapper.className = "bubble-attachment";

  if (attachment.mimeType.startsWith("image/")) {
    const img = document.createElement("img");
    img.alt = attachment.filename;
    img.src = attachment.dataUrl;
    wrapper.append(img);
    return wrapper;
  }

  const tile = document.createElement("div");
  tile.className = "file-tile";
  const icon = document.createElement("div");
  icon.className = "file-icon";
  icon.textContent = attachment.mimeType.includes("pdf") ? "PDF" : "TXT";
  const copy = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = attachment.filename;
  const meta = document.createElement("span");
  meta.textContent = formatBytes(attachment.size);
  copy.append(title, meta);
  tile.append(icon, copy);
  wrapper.append(tile);
  return wrapper;
}

function showTyping() {
  hideTyping();
  const row = document.createElement("article");
  row.className = "message assistant typing";
  row.dataset.typing = "true";
  row.innerHTML =
    '<div class="bubble"><span class="typing-dots"><span></span><span></span><span></span></span></div>';
  els.messageList.append(row);
  scrollMessagesToBottom();
}

function hideTyping() {
  const typing = els.messageList.querySelector("[data-typing='true']");
  if (typing) {
    typing.remove();
  }
}

function setConnectionLabel(label, status = "ok") {
  els.connectionPill.textContent = label;
  els.connectionPill.dataset.status = status;
  els.phoneStatus.textContent = label;
}

function setComposerDisabled(disabled) {
  els.sendButton.disabled = disabled;
  els.attachmentButton.disabled = disabled;
  els.messageInput.disabled = disabled;
}

function autoSizeComposer() {
  els.messageInput.style.height = "auto";
  els.messageInput.style.height = `${Math.min(112, els.messageInput.scrollHeight)}px`;
}

function scrollMessagesToBottom() {
  els.messageList.scrollTop = els.messageList.scrollHeight;
}

function buildConversationId() {
  const random =
    globalThis.crypto && typeof globalThis.crypto.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : String(Date.now());
  const value = `whatsapp-demo-${random}`;
  localStorage.setItem(storageKeys.conversationId, value);
  return value;
}

function formatTime(date) {
  return date.toLocaleTimeString("es-AR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(bytes) {
  if (!bytes) {
    return "0 B";
  }
  const units = ["B", "KB", "MB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function guessMimeType(filename) {
  const lower = String(filename || "").toLowerCase();
  if (lower.endsWith(".pdf")) {
    return "application/pdf";
  }
  if (lower.endsWith(".txt")) {
    return "text/plain";
  }
  if (lower.endsWith(".png")) {
    return "image/png";
  }
  return "image/jpeg";
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result)));
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsDataURL(file);
  });
}

init().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  appendMessage({ role: "system", text: `Error inicializando demo: ${message}` });
});
