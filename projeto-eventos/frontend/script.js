const API_BASE = "http://127.0.0.1:8000";
const TOKEN_KEY = "showline_token";
const USERNAME_KEY = "showline_username";

let allEvents = [];
let currentEventId = null;
let activeCategory = null;
let editingEventId = null; // null = modo "criar", número = modo "editar"
let authMode = "login"; // "login" ou "register"

const $ = (sel) => document.querySelector(sel);
const grid = $("#eventsGrid");
const emptyState = $("#emptyState");
const eventCount = $("#eventCount");
const listTitle = $("#listTitle");

// ---------- Autenticação ----------
function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
function setSession(token, username) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USERNAME_KEY, username);
  updateAuthUI(username);
}
function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USERNAME_KEY);
  updateAuthUI(null);
}
function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
function updateAuthUI(username) {
  const loggedOut = $("#authLoggedOut");
  const loggedIn = $("#authLoggedIn");
  if (username) {
    loggedOut.hidden = true;
    loggedIn.hidden = false;
    $("#authUsername").textContent = username;
  } else {
    loggedOut.hidden = false;
    loggedIn.hidden = true;
  }
}

async function verificarSessaoSalva() {
  const token = getToken();
  if (!token) return;
  try {
    const res = await fetch(`${API_BASE}/usuarios/me`, { headers: authHeaders() });
    if (!res.ok) throw new Error();
    const data = await res.json();
    updateAuthUI(data.username);
  } catch {
    clearSession(); // token expirado/inválido
  }
}

function openAuthModal(mode) {
  authMode = mode;
  $("#authForm").reset();
  $("#authFeedback").textContent = "";
  $("#tabLogin").classList.toggle("auth-tab--active", mode === "login");
  $("#tabRegister").classList.toggle("auth-tab--active", mode === "register");
  $("#authSubmitBtn").textContent = mode === "login" ? "Entrar" : "Criar conta";
  $("#authModalBackdrop").hidden = false;
}
function closeAuthModal() {
  $("#authModalBackdrop").hidden = true;
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const username = $("#authUsernameInput").value.trim();
  const senha = $("#authPasswordInput").value;
  const rota = authMode === "login" ? "/usuarios/login" : "/usuarios/registrar";

  try {
    const res = await fetch(`${API_BASE}${rota}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, senha }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Erro ao autenticar");
    setSession(data.token, data.username);
    closeAuthModal();
    await loadEvents();
  } catch (err) {
    showFeedback("#authFeedback", err.message, false);
  }
}

async function handleLogout() {
  try {
    await fetch(`${API_BASE}/usuarios/logout`, { method: "POST", headers: authHeaders() });
  } catch {
    /* mesmo se falhar, limpa local */
  }
  clearSession();
  await loadEvents();
}

// ---------- API status ----------
async function checkApi() {
  const dot = $("#apiDot");
  const text = $("#apiStatusText");
  try {
    const res = await fetch(`${API_BASE}/eventos/`);
    if (!res.ok) throw new Error();
    dot.className = "dot dot--ok";
    text.textContent = "API conectada";
  } catch {
    dot.className = "dot dot--err";
    text.textContent = "API offline — rode o backend (uvicorn main:app --reload)";
  }
}

// ---------- Datas em dd/mm/aaaa ----------
function maskDateInput(el) {
  el.addEventListener("input", () => {
    let v = el.value.replace(/\D/g, "").slice(0, 8);
    if (v.length >= 5) v = `${v.slice(0, 2)}/${v.slice(2, 4)}/${v.slice(4)}`;
    else if (v.length >= 3) v = `${v.slice(0, 2)}/${v.slice(2)}`;
    el.value = v;
  });
}

function brParaIso(br) {
  const m = br.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!m) return null;
  const [, d, mes, y] = m;
  return `${y}-${mes}-${d}`;
}

function isoParaBr(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

function formatDate(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

// ---------- Render ----------
function renderChips() {
  const categorias = [...new Set(allEvents.map((e) => e.categoria))].sort();
  const chipsEl = $("#categoryChips");
  chipsEl.innerHTML = "";
  if (categorias.length === 0) return;

  const allChip = document.createElement("button");
  allChip.className = "chip" + (activeCategory === null ? " chip--active" : "");
  allChip.textContent = "Todos";
  allChip.onclick = () => { activeCategory = null; renderEvents(); renderChips(); };
  chipsEl.appendChild(allChip);

  categorias.forEach((cat) => {
    const chip = document.createElement("button");
    chip.className = "chip" + (activeCategory === cat ? " chip--active" : "");
    chip.textContent = cat;
    chip.onclick = () => { activeCategory = cat; renderEvents(); renderChips(); };
    chipsEl.appendChild(chip);
  });
}

function renderEvents() {
  let list = allEvents;
  if (activeCategory) list = list.filter((e) => e.categoria === activeCategory);

  grid.innerHTML = "";
  eventCount.textContent = `${list.length} evento${list.length === 1 ? "" : "s"}`;
  emptyState.hidden = list.length > 0;

  list.forEach((ev) => {
    const card = document.createElement("div");
    card.className = "card";
    card.onclick = () => openEventModal(ev.id);

    const imgStyle = ev.imagem_url
      ? `background-image:url('${ev.imagem_url}')`
      : "";

    card.innerHTML = `
      <div class="card__image" style="${imgStyle}">
        <span class="card__category">${ev.categoria}</span>
      </div>
      <div class="card__body">
        <span class="card__date">${formatDate(ev.data)}</span>
        <h3 class="card__title">${ev.nome}</h3>
        <span class="card__location">${ev.local}${ev.criador ? " · por " + ev.criador : ""}</span>
      </div>
      <div class="card__perforation"></div>
      <div class="card__footer">
        <span class="card__price">${ev.preco > 0 ? "R$ " + ev.preco.toFixed(2) : "Gratuito"}</span>
        <span class="card__status ${ev.esgotado ? "status--full" : "status--open"}">
          ${ev.esgotado ? "Lotado" : ev.vagas_restantes + " vagas"}
        </span>
      </div>
    `;
    grid.appendChild(card);
  });
}

// ---------- Load events ----------
async function loadEvents() {
  try {
    const res = await fetch(`${API_BASE}/eventos/`, { headers: authHeaders() });
    allEvents = await res.json();
    renderChips();
    renderEvents();
  } catch (e) {
    grid.innerHTML = "";
    emptyState.hidden = false;
    $("#emptyState p").textContent = "Não foi possível conectar à API.";
  }
}

// ---------- Event modal ----------
async function openEventModal(id) {
  const res = await fetch(`${API_BASE}/eventos/${id}`, { headers: authHeaders() });
  if (!res.ok) return;
  const ev = await res.json();
  currentEventId = id;

  $("#modalCategoria").textContent = ev.categoria;
  $("#modalNome").textContent = ev.nome;
  $("#modalDescricao").textContent = ev.descricao || "Sem descrição.";
  $("#modalData").textContent = formatDate(ev.data);
  $("#modalLocal").textContent = ev.local;
  $("#modalPreco").textContent = ev.preco > 0 ? `R$ ${ev.preco.toFixed(2)}` : "Gratuito";
  $("#modalId").textContent = `#${String(ev.id).padStart(3, "0")}`;
  $("#modalCriador").textContent = ev.criador || "desconhecido";

  const pct = ev.lotacao_maxima > 0 ? Math.min(100, (ev.vagas_ocupadas / ev.lotacao_maxima) * 100) : 0;
  $("#modalCapacityFill").style.width = `${pct}%`;
  $("#modalCapacityLabel").textContent = `${ev.vagas_ocupadas}/${ev.lotacao_maxima} vagas ocupadas`;

  const queueBadge = $("#modalQueueBadge");
  if (ev.fila_espera.length > 0) {
    queueBadge.hidden = false;
    $("#modalQueueCount").textContent = ev.fila_espera.length;
  } else {
    queueBadge.hidden = true;
  }

  // Só quem criou o evento vê os botões de editar/excluir
  $("#ownerActions").hidden = !ev.pode_editar;
  $("#btnEditarEvento").onclick = () => openEditModal(ev);

  $("#formFeedback").textContent = "";
  $("#inscricaoNome").value = "";
  $("#inscricaoEmail").value = "";
  $("#cancelarNome").value = "";

  $("#eventModalBackdrop").hidden = false;
}

function closeEventModal() {
  $("#eventModalBackdrop").hidden = true;
  currentEventId = null;
}

function showFeedback(elId, message, ok) {
  const el = $(elId);
  el.textContent = message;
  el.className = "form-feedback " + (ok ? "ok" : "err");
}

// ---------- Inscrição ----------
async function handleInscricao(e) {
  e.preventDefault();
  const nome = $("#inscricaoNome").value.trim();
  const email = $("#inscricaoEmail").value.trim();
  if (!nome) return;

  try {
    const res = await fetch(`${API_BASE}/eventos/${currentEventId}/inscrever`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome_participante: nome, email }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Erro ao inscrever");
    showFeedback("#formFeedback", data.mensagem, true);
    await loadEvents();
    await openEventModal(currentEventId);
  } catch (err) {
    showFeedback("#formFeedback", err.message, false);
  }
}

// ---------- Cancelamento ----------
async function handleCancelar() {
  const nome = $("#cancelarNome").value.trim();
  if (!nome) return;

  try {
    const res = await fetch(
      `${API_BASE}/eventos/${currentEventId}/cancelar?nome_participante=${encodeURIComponent(nome)}`,
      { method: "DELETE" }
    );
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Erro ao cancelar");
    showFeedback("#formFeedback", data.mensagem, true);
    await loadEvents();
    await openEventModal(currentEventId);
  } catch (err) {
    showFeedback("#formFeedback", err.message, false);
  }
}

// ---------- Excluir evento ----------
async function handleExcluirEvento() {
  if (!confirm("Tem certeza que deseja excluir este evento? Essa ação não pode ser desfeita.")) return;
  try {
    const res = await fetch(`${API_BASE}/eventos/${currentEventId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Erro ao excluir evento");
    closeEventModal();
    await loadEvents();
  } catch (err) {
    showFeedback("#formFeedback", err.message, false);
  }
}

// ---------- Criar / editar evento ----------
function openCreateModal() {
  if (!getToken()) {
    openAuthModal("login");
    return;
  }
  editingEventId = null;
  $("#createForm").reset();
  $("#cCategoria").value = "Geral";
  $("#cLotacao").value = 50;
  $("#cPreco").value = 0;
  $("#createFeedback").textContent = "";
  $("#createModalTitle").textContent = "Criar novo evento";
  $("#createSubmitBtn").textContent = "Criar evento";
  $("#createModalBackdrop").hidden = false;
}

function openEditModal(ev) {
  editingEventId = ev.id;
  closeEventModal();
  $("#cNome").value = ev.nome;
  $("#cDescricao").value = ev.descricao || "";
  $("#cCategoria").value = ev.categoria;
  $("#cLocal").value = ev.local;
  $("#cData").value = isoParaBr(ev.data);
  $("#cLotacao").value = ev.lotacao_maxima;
  $("#cPreco").value = ev.preco;
  $("#cImagem").value = ev.imagem_url || "";
  $("#createFeedback").textContent = "";
  $("#createModalTitle").textContent = "Editar evento";
  $("#createSubmitBtn").textContent = "Salvar alterações";
  $("#createModalBackdrop").hidden = false;
}

function closeCreateModal() {
  $("#createModalBackdrop").hidden = true;
  editingEventId = null;
}

async function handleCreateEvent(e) {
  e.preventDefault();

  const dataIso = brParaIso($("#cData").value.trim());
  if (!dataIso) {
    showFeedback("#createFeedback", "Data inválida. Use o formato dd/mm/aaaa.", false);
    return;
  }

  const payload = {
    nome: $("#cNome").value.trim(),
    descricao: $("#cDescricao").value.trim(),
    categoria: $("#cCategoria").value.trim() || "Geral",
    local: $("#cLocal").value.trim() || "A definir",
    data_iso: dataIso,
    lotacao_maxima: parseInt($("#cLotacao").value, 10),
    preco: parseFloat($("#cPreco").value || "0"),
    imagem_url: $("#cImagem").value.trim(),
  };

  const editando = editingEventId !== null;
  const url = editando ? `${API_BASE}/eventos/${editingEventId}` : `${API_BASE}/eventos/`;
  const method = editando ? "PUT" : "POST";

  try {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Erro ao salvar evento");
    closeCreateModal();
    await loadEvents();
  } catch (err) {
    showFeedback("#createFeedback", err.message, false);
  }
}

// ---------- Busca ----------
async function handleBuscar() {
  const nome = $("#searchInput").value.trim().toLowerCase();
  const dataBr = $("#searchDate").value.trim();

  if (dataBr) {
    const dataIso = brParaIso(dataBr);
    if (!dataIso) {
      listTitle.textContent = "Data inválida — use dd/mm/aaaa";
      return;
    }
    const res = await fetch(`${API_BASE}/eventos/buscar/data?data_iso=${dataIso}`, { headers: authHeaders() });
    allEvents = await res.json();
    listTitle.textContent = `Eventos em ${dataBr}`;
  } else if (nome) {
    const res = await fetch(`${API_BASE}/eventos/`, { headers: authHeaders() });
    const todos = await res.json();
    allEvents = todos.filter((e) => e.nome.toLowerCase().includes(nome));
    listTitle.textContent = `Resultados para "${nome}"`;
  } else {
    await loadEvents();
    listTitle.textContent = "Próximos eventos";
    return;
  }
  activeCategory = null;
  renderChips();
  renderEvents();
}

function handleLimpar() {
  $("#searchInput").value = "";
  $("#searchDate").value = "";
  listTitle.textContent = "Próximos eventos";
  loadEvents();
}

// ---------- Relatório ordenado (BST) ----------
async function handleRelatorio() {
  const res = await fetch(`${API_BASE}/eventos/relatorio-ordenado`, { headers: authHeaders() });
  allEvents = await res.json();
  listTitle.textContent = "Relatório ordenado (BST A–Z)";
  activeCategory = null;
  renderChips();
  renderEvents();
}

// ---------- Wire up ----------
document.addEventListener("DOMContentLoaded", () => {
  checkApi();
  verificarSessaoSalva();
  loadEvents();

  maskDateInput($("#searchDate"));
  maskDateInput($("#cData"));

  $("#closeEventModal").onclick = closeEventModal;
  $("#eventModalBackdrop").onclick = (e) => { if (e.target.id === "eventModalBackdrop") closeEventModal(); };

  $("#btnNovoEvento").onclick = openCreateModal;
  $("#closeCreateModal").onclick = closeCreateModal;
  $("#createModalBackdrop").onclick = (e) => { if (e.target.id === "createModalBackdrop") closeCreateModal(); };

  $("#btnAbrirLogin").onclick = () => openAuthModal("login");
  $("#btnLogout").onclick = handleLogout;
  $("#closeAuthModal").onclick = closeAuthModal;
  $("#authModalBackdrop").onclick = (e) => { if (e.target.id === "authModalBackdrop") closeAuthModal(); };
  $("#tabLogin").onclick = () => openAuthModal("login");
  $("#tabRegister").onclick = () => openAuthModal("register");
  $("#authForm").onsubmit = handleAuthSubmit;

  $("#inscricaoForm").onsubmit = handleInscricao;
  $("#btnCancelar").onclick = handleCancelar;
  $("#btnExcluirEvento").onclick = handleExcluirEvento;
  $("#createForm").onsubmit = handleCreateEvent;

  $("#btnBuscar").onclick = handleBuscar;
  $("#btnLimpar").onclick = handleLimpar;
  $("#btnRelatorio").onclick = handleRelatorio;

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeEventModal(); closeCreateModal(); closeAuthModal(); }
  });
});
