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
  conversationInput: document.querySelector("#conversationInput"),
  userInput: document.querySelector("#userInput"),
  evalTagList: document.querySelector("#evalTagList"),
  newConversationButton: document.querySelector("#newConversationButton"),
  connectionPill: document.querySelector("#connectionPill"),
  phoneStatus: document.querySelector("#phoneStatus"),
};

const evalTagOptions = [
  { value: "eval:candidate", label: "Candidate" },
  { value: "eval:dataset-ready", label: "Dataset ready" },
  { value: "eval:regression", label: "Regression" },
  { value: "eval:invoice-upload", label: "Invoice upload" },
  { value: "eval:invoice-review", label: "Invoice review" },
  { value: "eval:missing-data", label: "Missing data" },
  { value: "eval:odoo-search", label: "Odoo search" },
  { value: "eval:confirmation", label: "Confirmation" },
  { value: "eval:attachment", label: "Attachment" },
  { value: "eval:multi-turn", label: "Multi-turn" },
  { value: "eval:error-recovery", label: "Error recovery" },
  { value: "eval:discarded", label: "Discarded" },
];

const storageKeys = {
  endpoint: "sumampa-demo-endpoint",
  conversationId: "sumampa-demo-conversation-id",
  userId: "sumampa-demo-user-id",
  evalTag: "sumampa-demo-eval-tag",
  evalTags: "sumampa-demo-eval-tags",
  evalTagsByConversation: "sumampa-demo-eval-tags-by-conversation",
};

const state = {
  pendingAttachment: null,
  sending: false,
  healthTimer: null,
  resizeTimer: null,
  evalTags: [],
};

function init() {
  els.endpointInput.value =
    localStorage.getItem(storageKeys.endpoint) || els.endpointInput.value;
  els.conversationInput.value =
    localStorage.getItem(storageKeys.conversationId) || buildConversationId();
  els.userInput.value = localStorage.getItem(storageKeys.userId) || els.userInput.value;
  state.evalTags = loadEvalTagsForConversation(els.conversationInput.value.trim());
  renderEvalTags();

  bindEvents();
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

  [els.endpointInput, els.userInput].forEach((input) => {
    input.addEventListener("input", () => {
      persistControls();
      if (input === els.endpointInput) {
        checkBackendHealth();
      }
    });
  });

  els.conversationInput.addEventListener("input", () => {
    localStorage.setItem(storageKeys.conversationId, els.conversationInput.value.trim());
  });
  els.conversationInput.addEventListener("change", () => {
    state.evalTags = loadEvalTagsForConversation(els.conversationInput.value.trim());
    renderEvalTags();
    persistControls();
  });

  document.querySelectorAll("[data-message]").forEach((button) => {
    button.addEventListener("click", async () => {
      els.messageInput.value = button.dataset.message;
      autoSizeComposer();
      els.messageInput.focus();
      if (button.dataset.mockAttachment === "invoice") {
        await setMockInvoiceAttachment();
      }
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
  localStorage.setItem(storageKeys.endpoint, els.endpointInput.value.trim());
  localStorage.setItem(storageKeys.conversationId, els.conversationInput.value.trim());
  localStorage.setItem(storageKeys.userId, els.userInput.value.trim());
  saveEvalTagsForConversation(els.conversationInput.value.trim());
  localStorage.removeItem(storageKeys.evalTag);
  localStorage.removeItem(storageKeys.evalTags);
}

function loadEvalTagsForConversation(conversationId) {
  const tagsByConversation = readEvalTagsByConversation();
  const storedConversationTags = tagsByConversation[conversationId];
  if (Array.isArray(storedConversationTags)) {
    return normalizeEvalTags(storedConversationTags);
  }

  const storedTags = localStorage.getItem(storageKeys.evalTags);
  if (storedTags) {
    try {
      const parsed = JSON.parse(storedTags);
      if (Array.isArray(parsed)) {
        return normalizeEvalTags(parsed);
      }
    } catch {
      localStorage.removeItem(storageKeys.evalTags);
    }
  }

  const legacyTag = localStorage.getItem(storageKeys.evalTag);
  return normalizeEvalTags([legacyTag || "eval:candidate"]);
}

function saveEvalTagsForConversation(conversationId) {
  if (!conversationId) {
    return;
  }
  const tagsByConversation = readEvalTagsByConversation();
  tagsByConversation[conversationId] = normalizeEvalTags(state.evalTags);
  localStorage.setItem(storageKeys.evalTagsByConversation, JSON.stringify(tagsByConversation));
}

function readEvalTagsByConversation() {
  const stored = localStorage.getItem(storageKeys.evalTagsByConversation);
  if (!stored) {
    return {};
  }
  try {
    const parsed = JSON.parse(stored);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    localStorage.removeItem(storageKeys.evalTagsByConversation);
    return {};
  }
}

function toggleEvalTag(tag) {
  if (state.evalTags.includes(tag)) {
    state.evalTags = state.evalTags.filter((item) => item !== tag);
  } else {
    state.evalTags = [...state.evalTags, tag];
  }
  renderEvalTags();
  persistControls();
  syncEvalTags();
}

function renderEvalTags() {
  els.evalTagList.textContent = "";
  evalTagOptions.forEach((option) => {
    const selected = state.evalTags.includes(option.value);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-pill";
    button.dataset.selected = String(selected);
    button.setAttribute("aria-pressed", String(selected));
    button.title = option.value;
    button.textContent = option.label;
    button.addEventListener("click", () => toggleEvalTag(option.value));
    els.evalTagList.append(button);
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
  const value = String(tag || "").trim().slice(0, 200);
  return evalTagOptions.some((option) => option.value === value) ? value : "";
}

function startConversation() {
  state.pendingAttachment = null;
  clearPendingAttachment();
  els.messageList.textContent = "";
}

function startNewConversation() {
  els.conversationInput.value = buildConversationId();
  state.evalTags = normalizeEvalTags(["eval:candidate"]);
  els.messageInput.value = "";
  autoSizeComposer();
  startConversation();
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

async function setMockInvoiceAttachment() {
  const dataUrl = await buildMockInvoiceDataUrl();
  const base64 = dataUrl.split(",", 2)[1] || "";
  state.pendingAttachment = {
    filename: "factura-mock.jpg",
    mimeType: "image/jpeg",
    size: Math.ceil((base64.length * 3) / 4),
    dataUrl,
    contentBase64: base64,
  };
  renderPendingAttachment();
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

  state.sending = true;
  setComposerDisabled(true);

  appendMessage({ role: "user", text, attachment });
  els.messageInput.value = "";
  autoSizeComposer();
  clearPendingAttachment();

  const payload = buildPayload({ text, attachment });
  showTyping();
  setConnectionLabel("enviando", "checking");

  try {
    const replies = await sendToBackend(payload);
    hideTyping();
    replies.forEach((reply) => appendMessage({ role: "assistant", text: reply }));
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
  const userId = els.userInput.value.trim() || "5491123456789";
  els.conversationInput.value = conversationId;
  els.userInput.value = userId;
  persistControls();

  return {
    conversation_id: conversationId,
    channel: "whatsapp",
    user_id: userId,
    text,
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

  const messages = Array.isArray(body.messages) ? body.messages : [];
  if (!messages.length) {
    return ["El backend respondio sin mensajes."];
  }
  return messages.map((message) => message.text || "").filter(Boolean);
}

function syncEvalTags() {
  const tagsUrl = buildTagsUrl();
  if (!tagsUrl) {
    setConnectionLabel("endpoint invalido", "error");
    return;
  }

  sendTagsToBackend(tagsUrl, buildTagsPayload()).catch(() => {
    setConnectionLabel("offline", "error");
  });
}

function buildTagsPayload() {
  const conversationId = els.conversationInput.value.trim() || buildConversationId();
  const userId = els.userInput.value.trim() || "5491123456789";
  els.conversationInput.value = conversationId;
  els.userInput.value = userId;
  persistControls();

  return {
    conversation_id: conversationId,
    channel: "whatsapp",
    user_id: userId,
    eval_tags: state.evalTags.slice(),
    context: {
      demo: true,
      source: "demo/static-whatsapp",
      timestamp: new Date().toISOString(),
    },
  };
}

async function sendTagsToBackend(tagsUrl, payload) {
  const response = await fetch(tagsUrl, {
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
  setConnectionLabel("online", "ok");
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

function buildTagsUrl() {
  try {
    const endpoint = new URL(els.endpointInput.value.trim());
    const endpointPath = endpoint.pathname.replace(/\/+$/, "");
    endpoint.pathname = endpointPath.endsWith("/messages")
      ? `${endpointPath.slice(0, -"/messages".length)}/conversation-tags`
      : `${endpointPath}/conversation-tags`;
    endpoint.search = "";
    endpoint.hash = "";
    return endpoint.toString();
  } catch {
    return null;
  }
}

function appendMessage(message) {
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
  time.append(document.createTextNode(formatTime(new Date())));
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

function buildMockInvoiceDataUrl() {
  const canvas = document.createElement("canvas");
  canvas.width = 720;
  canvas.height = 960;
  const ctx = canvas.getContext("2d");

  ctx.fillStyle = "#fffaf0";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#143c33";
  ctx.fillRect(0, 0, canvas.width, 122);
  ctx.fillStyle = "#f2d27b";
  ctx.fillRect(42, 32, 58, 58);
  ctx.fillStyle = "#143c33";
  ctx.font = "700 30px Arial";
  ctx.fillText("A", 62, 72);
  ctx.fillStyle = "#ffffff";
  ctx.font = "700 38px Arial";
  ctx.fillText("FACTURA MOCK", 128, 56);
  ctx.font = "400 22px Arial";
  ctx.fillText("Proveedor Demo SRL", 128, 90);

  ctx.fillStyle = "#1d2a26";
  ctx.font = "700 26px Arial";
  ctx.fillText("Cliente: Sumampa Agro", 50, 178);
  ctx.font = "400 20px Arial";
  ctx.fillText("CUIT: 30-71122334-9", 50, 214);
  ctx.fillText("Fecha: 2026-04-25", 50, 246);

  const rows = [
    ["Producto", "Cant.", "Subtotal"],
    ["Insumo agricola", "3", "$82.800"],
    ["Flete", "1", "$18.400"],
    ["IVA 21%", "", "$21.252"],
  ];
  const x = 50;
  const y = 330;
  const w = 620;
  const h = 56;
  ctx.strokeStyle = "#d0c4b4";
  rows.forEach((row, index) => {
    const top = y + index * h;
    ctx.fillStyle = index === 0 ? "#ead8ac" : "#fffdf8";
    ctx.fillRect(x, top, w, h);
    ctx.strokeRect(x, top, w, h);
    ctx.fillStyle = "#1d2a26";
    ctx.font = index === 0 ? "700 18px Arial" : "400 18px Arial";
    ctx.fillText(row[0], x + 18, top + 35);
    ctx.fillText(row[1], x + 390, top + 35);
    ctx.fillText(row[2], x + 500, top + 35);
  });

  ctx.fillStyle = "#143c33";
  ctx.fillRect(426, 740, 244, 92);
  ctx.fillStyle = "#ffffff";
  ctx.font = "700 22px Arial";
  ctx.fillText("TOTAL", 454, 778);
  ctx.font = "700 30px Arial";
  ctx.fillText("$122.452", 454, 814);

  return canvas.toDataURL("image/jpeg", 0.9);
}

init();
