/**
 * Alifbo Production Admin Suite & Concierge Frontend Controller
 */

let state = {
  token: localStorage.getItem("alifbo_token") || "",
  currentTab: "dashboard",
  userSearchTimer: null,
  activeSessionId: "concierge_sim_" + Math.random().toString(36).substring(2, 9),
};

// DOM References
const elements = {
  navItems: document.querySelectorAll(".nav-item"),
  tabContents: document.querySelectorAll(".tab-content"),
  pageTitle: document.getElementById("page-title"),
  pageSubtitle: document.getElementById("page-subtitle"),
  adminName: document.getElementById("admin-name"),
  adminAvatar: document.getElementById("admin-avatar"),
  btnRefresh: document.getElementById("btn-refresh"),
  btnLogout: document.getElementById("btn-logout"),
  modalLogin: document.getElementById("modal-login"),
  formLogin: document.getElementById("form-login"),
  loginError: document.getElementById("login-error"),
  
  // Dashboard
  statTotalUsers: document.getElementById("stat-total-users"),
  statDailyActive: document.getElementById("stat-daily-active"),
  statConversions: document.getElementById("stat-conversions"),
  statCharsCount: document.getElementById("stat-chars-count"),
  statMrr: document.getElementById("stat-mrr"),
  chartActivity: document.getElementById("chart-activity"),
  tiersDistribution: document.getElementById("tiers-distribution"),

  // Users
  userSearchInput: document.getElementById("user-search-input"),
  userTierFilter: document.getElementById("user-tier-filter"),
  userStatusFilter: document.getElementById("user-status-filter"),
  usersTableBody: document.getElementById("users-table-body"),

  // Curriculum
  curriculumContainer: document.getElementById("curriculum-container"),
  btnAddLesson: document.getElementById("btn-add-lesson"),
  modalLesson: document.getElementById("modal-lesson"),
  formSaveLesson: document.getElementById("form-save-lesson"),
  editLessonModule: document.getElementById("edit-lesson-module"),

  // Audit
  auditTableBody: document.getElementById("audit-table-body"),

  // Support Concierge
  ticketsList: document.getElementById("tickets-list"),
  ticketFilter: document.getElementById("ticket-filter"),
  chatMessages: document.getElementById("chat-messages"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  btnClearChat: document.getElementById("btn-clear-chat"),

  // Broadcast
  broadcastForm: document.getElementById("broadcast-form"),
  broadcastTitle: document.getElementById("broadcast-title"),
  broadcastTier: document.getElementById("broadcast-tier"),
  broadcastContent: document.getElementById("broadcast-content"),
  btnSimulateBroadcast: document.getElementById("btn-simulate-broadcast"),
  broadcastResult: document.getElementById("broadcast-result"),

  // Orders
  badgeOrdersCount: document.getElementById("badge-orders-count"),
  ordersTableBody: document.getElementById("orders-table-body"),
  orderStatusFilter: document.getElementById("order-status-filter"),
  orderSearchInput: document.getElementById("order-search-input"),

  // User Tier Modal
  modalTier: document.getElementById("modal-tier"),
  formUpdateTier: document.getElementById("form-update-tier"),
  tierUserId: document.getElementById("tier-user-id"),
  tierUserName: document.getElementById("tier-user-name"),
  selectNewTier: document.getElementById("select-new-tier"),

  toastContainer: document.getElementById("toast-container"),
};

// Tab Meta Descriptions
const tabMeta = {
  dashboard: { title: "Boshqaruv Paneli", subtitle: "Alifbo platformasi real vaqt metrikalari va monitoringi" },
  users: { title: "Foydalanuvchilar & Kvota", subtitle: "Obunalar, balanslar va tezkor kvota chiplari boshqaruvi" },
  orders: { title: "Tarif Xarid So'rovlari", subtitle: "Mijozlardan kelgan buyurtmalar va 1-bosishda tasdiqlash / faollashtirish" },
  curriculum: { title: "Alifbo Ta'lim & Harflar", subtitle: "Yangi lotin harflari (Ö Ğ Ş Ç), qoidalar va viktorinalar" },
  audit: { title: "Audit & 1-Click Rollback", subtitle: "Ma'muriy harakatlar tarixi va xatolarni bir zumda qaytarish" },
  support: { title: "AI Concierge & Chiptalar", subtitle: "Gemini 2.5 asosidagi 24/7 yordamchi va eskalatsiya nazorati" },
  broadcast: { title: "Xabarnomalar (Broadcast)", subtitle: "Foydalanuvchilarga segmentlangan ommaviy bildirishnomalar" },
};

// API Helper
async function api(endpoint, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }

  try {
    const res = await fetch(endpoint, { ...options, headers });
    if (res.status === 401) {
      openModal("modal-login");
      throw new Error("Avtorizatsiyadan o'tilmagan");
    }
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Server xatosi yuz berdi");
    }
    return data;
  } catch (err) {
    throw err;
  }
}

// Toast Notifications
function showToast(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerText = message;
  elements.toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 4000);
}

// Modal Helpers
function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add("active");
}
function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove("active");
}
window.closeModal = closeModal;

// Initialize Application
async function init() {
  bindEvents();
  if (!state.token) {
    openModal("modal-login");
    return;
  }

  try {
    const me = await api("/api/admin/auth/me");
    elements.adminName.innerText = me.username;
    elements.adminAvatar.innerText = me.username.substring(0, 2).toUpperCase();
    closeModal("modal-login");
    loadTab(state.currentTab);
  } catch (e) {
    openModal("modal-login");
  }
}

// Event Bindings
function bindEvents() {
  // Navigation
  elements.navItems.forEach((btn) => {
    btn.addEventListener("click", () => {
      elements.navItems.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      loadTab(tab);
    });
  });

  // Refresh
  elements.btnRefresh.addEventListener("click", () => {
    loadTab(state.currentTab);
    showToast("Ma'lumotlar yangilandi");
  });

  // Logout
  elements.btnLogout.addEventListener("click", () => {
    localStorage.removeItem("alifbo_token");
    state.token = "";
    openModal("modal-login");
  });

  // Login Form
  elements.formLogin.addEventListener("submit", async (e) => {
    e.preventDefault();
    elements.loginError.innerText = "";
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value.trim();

    try {
      const res = await api("/api/admin/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      state.token = res.token;
      localStorage.setItem("alifbo_token", res.token);
      elements.adminName.innerText = res.username;
      closeModal("modal-login");
      showToast("Tizimga muvaffaqiyatli kirildi");
      loadTab("dashboard");
    } catch (err) {
      elements.loginError.innerText = err.message;
    }
  });

  // User Search & Filters
  elements.userSearchInput.addEventListener("input", () => {
    clearTimeout(state.userSearchTimer);
    state.userSearchTimer = setTimeout(loadUsers, 300);
  });
  elements.userTierFilter.addEventListener("change", loadUsers);
  elements.userStatusFilter.addEventListener("change", loadUsers);

  // Order Search & Filters
  if (elements.orderStatusFilter) {
    elements.orderStatusFilter.addEventListener("change", loadOrders);
  }
  if (elements.orderSearchInput) {
    elements.orderSearchInput.addEventListener("input", () => {
      clearTimeout(state.orderSearchTimer);
      state.orderSearchTimer = setTimeout(loadOrders, 300);
    });
  }

  // User Tier Modal Form
  elements.formUpdateTier.addEventListener("submit", async (e) => {
    e.preventDefault();
    const userId = elements.tierUserId.value;
    const tier = elements.selectNewTier.value;
    try {
      await api("/api/admin/users/tier", {
        method: "POST",
        body: JSON.stringify({ user_id: parseInt(userId), tier }),
      });
      closeModal("modal-tier");
      showToast(`Foydalanuvchi tarifi yangilandi: ${tier.toUpperCase()}`);
      loadUsers();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Curriculum Modals & Actions
  elements.btnAddLesson.addEventListener("click", () => {
    document.getElementById("modal-lesson-title").innerText = "Yangi Dars Qo'shish";
    document.getElementById("edit-lesson-id").value = "les_" + Date.now();
    document.getElementById("edit-lesson-name").value = "";
    document.getElementById("edit-lesson-letter").value = "";
    document.getElementById("edit-lesson-equiv").value = "";
    document.getElementById("edit-lesson-phonetic").value = "";
    document.getElementById("edit-lesson-rules").value = "";
    openModal("modal-lesson");
  });

  elements.formSaveLesson.addEventListener("submit", async (e) => {
    e.preventDefault();
    const lessonData = {
      id: document.getElementById("edit-lesson-id").value,
      module_id: document.getElementById("edit-lesson-module").value,
      title: document.getElementById("edit-lesson-name").value,
      letter_char: document.getElementById("edit-lesson-letter").value,
      old_latin_equiv: document.getElementById("edit-lesson-equiv").value,
      phonetic_guide: document.getElementById("edit-lesson-phonetic").value,
      rules_content: document.getElementById("edit-lesson-rules").value,
      order_num: 1,
    };
    try {
      await api("/api/admin/curriculum/lesson", {
        method: "POST",
        body: JSON.stringify(lessonData),
      });
      closeModal("modal-lesson");
      showToast("Ta'lim darsi muvaffaqiyatli saqlandi");
      loadCurriculum();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Support Concierge Chat Form
  elements.chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = elements.chatInput.value.trim();
    if (!msg) return;

    appendChatBubble("user", msg);
    elements.chatInput.value = "";

    try {
      const res = await api("/api/chat/message", {
        method: "POST",
        body: JSON.stringify({
          session_id: state.activeSessionId,
          message: msg,
          channel: "web",
        }),
      });

      appendChatBubble("ai", res.response, res.is_escalated);
      if (res.is_escalated) {
        showToast(`Eskalatsiya yuz berdi: Ticket #${res.ticket_id} yaratildi`, "error");
        loadTickets();
      }
    } catch (err) {
      appendChatBubble("ai", "Xatolik yuz berdi: " + err.message);
    }
  });

  elements.btnClearChat.addEventListener("click", () => {
    state.activeSessionId = "concierge_sim_" + Math.random().toString(36).substring(2, 9);
    elements.chatMessages.innerHTML = `
      <div class="chat-bubble ai">
        Assalomu alaykum! Men Alifbo AI Yordamchisiman. Yangi lotin harflari (Ö Ğ Ş Ç), qoidalar yoki tariflar bo'yicha savolingiz bormi?
      </div>
    `;
    showToast("Suhbat sessiyasi tozalandi");
  });

  elements.ticketFilter.addEventListener("change", loadTickets);

  // Broadcast Form
  elements.btnSimulateBroadcast.addEventListener("click", async () => {
    const title = elements.broadcastTitle.value.trim() || "Test Sarlavha";
    const content = elements.broadcastContent.value.trim() || "Test Matn";
    const target_tier = elements.broadcastTier.value;

    try {
      const res = await api("/api/admin/broadcast", {
        method: "POST",
        body: JSON.stringify({ title, content, target_tier, simulate: true }),
      });
      elements.broadcastResult.className = "broadcast-result success";
      elements.broadcastResult.innerText = `💡 ${res.message}`;
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  elements.broadcastForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = elements.broadcastTitle.value.trim();
    const content = elements.broadcastContent.value.trim();
    const target_tier = elements.broadcastTier.value;

    if (!confirm(`Haqiqatan ham barcha "${target_tier}" foydalanuvchilariga xabar yuborilsinmi?`)) return;

    try {
      const res = await api("/api/admin/broadcast", {
        method: "POST",
        body: JSON.stringify({ title, content, target_tier, simulate: false }),
      });
      elements.broadcastResult.className = "broadcast-result success";
      elements.broadcastResult.innerText = `✅ ${res.message}`;
      showToast(res.message);
      elements.broadcastTitle.value = "";
      elements.broadcastContent.value = "";
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

// Tab Switcher
function loadTab(tab) {
  state.currentTab = tab;
  elements.tabContents.forEach((c) => c.classList.remove("active"));
  const activeContent = document.getElementById(`tab-${tab}`);
  if (activeContent) activeContent.classList.add("active");

  const meta = tabMeta[tab] || { title: "Admin Suite", subtitle: "" };
  elements.pageTitle.innerText = meta.title;
  elements.pageSubtitle.innerText = meta.subtitle;

  if (tab === "dashboard") loadDashboard();
  else if (tab === "users") loadUsers();
  else if (tab === "orders") loadOrders();
  else if (tab === "curriculum") loadCurriculum();
  else if (tab === "audit") loadAudit();
  else if (tab === "support") {
    loadTickets();
  }
}

// 1. Dashboard Loader
async function loadDashboard() {
  try {
    const m = await api("/api/admin/metrics");
    elements.statTotalUsers.innerText = m.total_users.toLocaleString();
    elements.statDailyActive.innerText = m.daily_active_learners.toLocaleString();
    elements.statConversions.innerText = m.total_conversions.toLocaleString();
    elements.statCharsCount.innerText = `${m.total_chars_converted.toLocaleString()} belgi`;
    elements.statMrr.innerText = `${m.monthly_revenue_uzs.toLocaleString()} UZS`;

    if (m.pending_purchase_orders && m.pending_purchase_orders > 0) {
      if (elements.badgeOrdersCount) {
        elements.badgeOrdersCount.innerText = m.pending_purchase_orders;
        elements.badgeOrdersCount.style.display = "inline-block";
      }
    } else if (elements.badgeOrdersCount) {
      elements.badgeOrdersCount.style.display = "none";
    }

    // Render 7-day SVG Bars Chart
    renderChart(m.activity_chart || []);

    // Render Tiers breakdown
    renderTiersDistribution(m.active_subscriptions || {}, m.total_users);
  } catch (err) {
    showToast(err.message, "error");
  }
}

function renderChart(data) {
  if (!data || !data.length) {
    elements.chartActivity.innerHTML = "<p class='loading-state'>Ma'lumotlar mavjud emas</p>";
    return;
  }
  const max = Math.max(...data.map((d) => d.conversions), 10);
  elements.chartActivity.innerHTML = data
    .map((d) => {
      const heightPercent = Math.max(10, Math.round((d.conversions / max) * 100));
      return `
        <div class="chart-bar-group">
          <div class="chart-bar" style="height: ${heightPercent}%;" data-val="${d.conversions} so'rov"></div>
          <span class="chart-label">${d.date}</span>
        </div>
      `;
    })
    .join("");
}

function renderTiersDistribution(tiers, total) {
  const tierConfigs = [
    { key: "free", name: "Oddiy / Bepul", price: "0 UZS", class: "fill-free" },
    { key: "student", name: "Talaba & O'quvchi", price: "12 000 UZS/oy", class: "fill-student" },
    { key: "pro", name: "Muallim & Pro", price: "25 000 UZS/oy", class: "fill-pro" },
    { key: "business", name: "Tashkilot & Nashriyot", price: "75 000 UZS/oy", class: "fill-business" },
  ];

  const totalUsers = Math.max(total, 1);
  elements.tiersDistribution.innerHTML = tierConfigs
    .map((t) => {
      const count = tiers[t.key] || 0;
      const pct = Math.round((count / totalUsers) * 100);
      return `
        <div class="tier-item">
          <div class="tier-item-header">
            <strong>${t.name} <span class="tag-badge">${t.price}</span></strong>
            <span>${count} foydalanuvchi (${pct}%)</span>
          </div>
          <div class="progress-bar-bg">
            <div class="progress-bar-fill ${t.class}" style="width: ${Math.max(4, pct)}%;"></div>
          </div>
        </div>
      `;
    })
    .join("");
}

// 2. Users Loader
async function loadUsers() {
  const search = elements.userSearchInput.value.trim();
  const tier = elements.userTierFilter.value;
  const status = elements.userStatusFilter.value;

  let query = `/api/admin/users?limit=50`;
  if (search) query += `&search=${encodeURIComponent(search)}`;
  if (tier) query += `&tier=${encodeURIComponent(tier)}`;
  if (status !== "") query += `&is_blocked=${status === "1"}`;

  try {
    const res = await api(query);
    if (!res.users || !res.users.length) {
      elements.usersTableBody.innerHTML = `<tr><td colspan="7" class="loading-state">Hech qanday foydalanuvchi topilmadi</td></tr>`;
      return;
    }

    elements.usersTableBody.innerHTML = res.users
      .map((u) => {
        const balanceText = u.unlimited_quota ? "♾️ Cheksiz" : `${(u.credits_balance || 0).toLocaleString()} belgi`;
        const lastActive = u.last_active_at ? new Date(u.last_active_at * 1000).toLocaleDateString("uz-UZ") : "-";
        return `
          <tr>
            <td>
              <div style="font-weight: 600;">${u.first_name || u.username || 'Noma\'lum'}</div>
              <div style="font-size: 11px; color: var(--text-subtle); font-family: var(--font-mono);">ID: ${u.user_id} ${u.username ? '@' + u.username : ''}</div>
            </td>
            <td><span class="badge badge-${u.tier}">${u.tier.toUpperCase()}</span></td>
            <td><strong style="font-family: var(--font-mono);">${balanceText}</strong></td>
            <td>${u.conversions_count || 0} ta</td>
            <td>
              <div class="quota-chips">
                <button class="chip" onclick="adjustUserQuota(${u.user_id}, 5000, 'add')">+5K</button>
                <button class="chip" onclick="adjustUserQuota(${u.user_id}, 10000, 'add')">+10K</button>
                <button class="chip" onclick="adjustUserQuota(${u.user_id}, 30000, 'add')">+30K</button>
                <button class="chip" onclick="adjustUserQuota(${u.user_id}, 100000, 'add')">+100K</button>
                <button class="chip chip-unlimited" onclick="adjustUserQuota(${u.user_id}, 0, 'unlimited')">Cheksiz</button>
              </div>
            </td>
            <td>
              <span class="badge ${u.is_blocked ? 'badge-blocked' : 'badge-active'}">
                ${u.is_blocked ? 'Bloklangan' : 'Faol'}
              </span>
            </td>
            <td>
              <div style="display: flex; gap: 6px;">
                <button class="btn btn-sm btn-secondary" onclick="openTierModal(${u.user_id}, '${u.username || u.first_name || u.user_id}', '${u.tier}')">Tarif</button>
                <button class="btn btn-sm btn-secondary" style="color: ${u.is_blocked ? 'var(--accent-emerald)' : 'var(--accent-rose)'};" onclick="toggleUserStatus(${u.user_id}, ${!u.is_blocked})">
                  ${u.is_blocked ? 'Tiklash' : 'Bloklash'}
                </button>
              </div>
            </td>
          </tr>
        `;
      })
      .join("");
  } catch (err) {
    showToast(err.message, "error");
  }
}

window.adjustUserQuota = async function (userId, delta, actionType) {
  try {
    const res = await api("/api/admin/users/quota", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, delta: delta, action_type: actionType }),
    });
    showToast(res.message);
    loadUsers();
  } catch (err) {
    showToast(err.message, "error");
  }
};

window.openTierModal = function (userId, userName, currentTier) {
  elements.tierUserId.value = userId;
  elements.tierUserName.innerText = userName;
  elements.selectNewTier.value = currentTier;
  openModal("modal-tier");
};

window.toggleUserStatus = async function (userId, blockStatus) {
  if (!confirm(`Foydalanuvchini haqiqatan ham ${blockStatus ? 'bloklamoqchimisiz' : 'faollashtirmoqchimisiz'}?`)) return;
  try {
    const res = await api("/api/admin/users/status", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, is_blocked: blockStatus }),
    });
    showToast(res.message);
    loadUsers();
  } catch (err) {
    showToast(err.message, "error");
  }
};

// 3. Curriculum Loader
async function loadCurriculum() {
  try {
    const res = await api("/api/admin/curriculum");
    const modules = res.modules || [];

    // Populate module select in modal
    elements.editLessonModule.innerHTML = modules
      .map((m) => `<option value="${m.id}">${m.title}</option>`)
      .join("");

    if (!modules.length) {
      elements.curriculumContainer.innerHTML = "<p class='loading-state'>Darslar topilmadi</p>";
      return;
    }

    elements.curriculumContainer.innerHTML = modules
      .map((m) => {
        const lessonsHtml = (m.lessons || [])
          .map(
            (l) => `
            <div class="lesson-card">
              <div class="lesson-top">
                <div class="letter-box">${l.letter_char || 'A'}</div>
                <div class="lesson-title-info">
                  <h5>${l.title}</h5>
                  <span class="lesson-equiv">${l.old_latin_equiv ? 'Eski: ' + l.old_latin_equiv : ''} ${l.cyrillic_equiv ? '· Kirill: ' + l.cyrillic_equiv : ''}</span>
                </div>
              </div>
              <p class="lesson-rules">${l.rules_content || 'Qoida matni'}</p>
              <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: auto;">
                <button class="btn btn-sm btn-secondary" onclick="editLesson('${l.id}', '${m.id}', '${escapeAttr(l.title)}', '${l.letter_char || ''}', '${escapeAttr(l.old_latin_equiv || '')}', '${escapeAttr(l.phonetic_guide || '')}', '${escapeAttr(l.rules_content || '')}')">Tahrirlash</button>
                <button class="btn btn-sm btn-secondary" style="color: var(--accent-rose);" onclick="deleteLesson('${l.id}')">O'chirish</button>
              </div>
            </div>
          `
          )
          .join("");

        return `
          <div class="module-block">
            <div class="module-header">
              <div>
                <h4>${m.title}</h4>
                <p style="font-size: 13px; color: var(--text-muted);">${m.description || ''}</p>
              </div>
              <span class="badge badge-student">${m.level.toUpperCase()}</span>
            </div>
            <div class="lessons-grid">
              ${lessonsHtml || '<p class="loading-state">Ushbu modulda darslar yo\'q</p>'}
            </div>
          </div>
        `;
      })
      .join("");
  } catch (err) {
    showToast(err.message, "error");
  }
}

function escapeAttr(str) {
  return (str || "").replace(/"/g, "&quot;").replace(/'/g, "\\'");
}

window.editLesson = function (id, moduleId, title, letter, equiv, phonetic, rules) {
  document.getElementById("modal-lesson-title").innerText = "Darsni Tahrirlash";
  document.getElementById("edit-lesson-id").value = id;
  document.getElementById("edit-lesson-module").value = moduleId;
  document.getElementById("edit-lesson-name").value = title;
  document.getElementById("edit-lesson-letter").value = letter;
  document.getElementById("edit-lesson-equiv").value = equiv;
  document.getElementById("edit-lesson-phonetic").value = phonetic;
  document.getElementById("edit-lesson-rules").value = rules;
  openModal("modal-lesson");
};

window.deleteLesson = async function (id) {
  if (!confirm("Haqiqatan ham bu darsni o'chirmoqchimisiz? (Audit orqali tiklash mumkin)")) return;
  try {
    await api(`/api/admin/curriculum/lesson/${id}`, { method: "DELETE" });
    showToast("Dars o'chirildi (Audit jurnaliga yozildi)");
    loadCurriculum();
  } catch (err) {
    showToast(err.message, "error");
  }
};

// 4. Audit Trail Loader & 1-Click Rollback
async function loadAudit() {
  try {
    const res = await api("/api/admin/audit?limit=50");
    if (!res.logs || !res.logs.length) {
      elements.auditTableBody.innerHTML = `<tr><td colspan="7" class="loading-state">Audit jurnali bo'sh</td></tr>`;
      return;
    }

    elements.auditTableBody.innerHTML = res.logs
      .map((log) => {
        const timeStr = new Date(log.created_at * 1000).toLocaleString("uz-UZ");
        const detailsStr = JSON.stringify(log.details || {});
        const canRollback = log.rollback_payload && !log.is_rolled_back;

        return `
          <tr>
            <td><span style="font-family: var(--font-mono); font-size: 11px;">#${log.id}</span></td>
            <td style="white-space: nowrap;">${timeStr}</td>
            <td><strong>${log.actor}</strong></td>
            <td><span class="badge badge-free">${log.action}</span></td>
            <td><code>${log.target_type}: ${log.target_id}</code></td>
            <td style="max-width: 250px; font-family: var(--font-mono); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeAttr(detailsStr)}">
              ${detailsStr}
            </td>
            <td>
              ${
                log.is_rolled_back
                  ? `<span class="badge" style="background: rgba(148, 163, 184, 0.2); color: var(--text-muted);">Qaytarilgan</span>`
                  : canRollback
                  ? `<button class="btn-rollback" onclick="executeRollback(${log.id})">⏪ 1-Click Undo</button>`
                  : `<span style="font-size: 11px; color: var(--text-subtle);">-</span>`
              }
            </td>
          </tr>
        `;
      })
      .join("");
  } catch (err) {
    showToast(err.message, "error");
  }
}

window.executeRollback = async function (auditId) {
  if (!confirm(`Haqiqatan ham #${auditId} raqamli amalni bekor qilmoqchimisiz (Rollback)?`)) return;
  try {
    const res = await api("/api/admin/audit/rollback", {
      method: "POST",
      body: JSON.stringify({ audit_id: auditId }),
    });
    showToast(res.message);
    loadAudit();
    if (state.currentTab === "users") loadUsers();
  } catch (err) {
    showToast(err.message, "error");
  }
};

// 5. Support Concierge Loader
async function loadTickets() {
  const filter = elements.ticketFilter.value;
  try {
    const res = await api(`/api/admin/tickets?status_filter=${filter}`);
    const tickets = res.tickets || [];
    if (!tickets.length) {
      elements.ticketsList.innerHTML = `<p class="loading-state">Eskalatsiya qilingan ochiq chiptalar yo'q</p>`;
      return;
    }

    elements.ticketsList.innerHTML = tickets
      .map((t) => {
        const timeStr = new Date(t.created_at * 1000).toLocaleString("uz-UZ");
        return `
          <div class="ticket-item ${t.priority === 'high' ? 'urgent' : ''}">
            <div>
              <div class="ticket-title">#${t.id}: ${t.subject}</div>
              <div class="ticket-meta">Foydalanuvchi: ${t.user_id || 'Mehmon'} · ${timeStr} · Sabab: ${t.escalated_reason || 'Noma\'lum'}</div>
            </div>
            <div style="display: flex; gap: 8px;">
              <select class="select-control select-sm" onchange="updateTicketStatus(${t.id}, this.value)">
                <option value="open" ${t.status === 'open' ? 'selected' : ''}>Ochiq</option>
                <option value="in_progress" ${t.status === 'in_progress' ? 'selected' : ''}>Jarayonda</option>
                <option value="resolved" ${t.status === 'resolved' ? 'selected' : ''}>Hal qilindi</option>
              </select>
            </div>
          </div>
        `;
      })
      .join("");
  } catch (err) {
    showToast(err.message, "error");
  }
}

window.updateTicketStatus = async function (ticketId, newStatus) {
  try {
    const res = await api("/api/admin/tickets/update", {
      method: "POST",
      body: JSON.stringify({ ticket_id: ticketId, status: newStatus }),
    });
    showToast(res.message);
    loadTickets();
  } catch (err) {
    showToast(err.message, "error");
  }
};

function appendChatBubble(role, text, isEscalated = false) {
  const b = document.createElement("div");
  b.className = `chat-bubble ${role} ${isEscalated ? 'escalated' : ''}`;
  b.innerHTML = text.replace(/\n/g, "<br>");
  elements.chatMessages.appendChild(b);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

// 7. Orders Management
async function loadOrders() {
  if (!elements.ordersTableBody) return;
  const status = elements.orderStatusFilter ? elements.orderStatusFilter.value : "";
  const search = elements.orderSearchInput ? elements.orderSearchInput.value.trim().toLowerCase() : "";

  elements.ordersTableBody.innerHTML = `<tr><td colspan="8" class="loading-state">Xarid so'rovlari yuklanmoqda...</td></tr>`;

  try {
    const url = status ? `/api/admin/orders?status=${status}` : `/api/admin/orders`;
    const res = await api(url);
    let orders = res.orders || [];

    if (search) {
      orders = orders.filter(
        (o) =>
          (o.first_name && o.first_name.toLowerCase().includes(search)) ||
          (o.username && o.username.toLowerCase().includes(search)) ||
          String(o.user_id).includes(search) ||
          String(o.id).includes(search)
      );
    }

    if (orders.length === 0) {
      elements.ordersTableBody.innerHTML = `<tr><td colspan="8" class="empty-state">Hozircha xarid so'rovlari mavjud emas.</td></tr>`;
      return;
    }

    elements.ordersTableBody.innerHTML = orders
      .map((o) => {
        const dateStr = new Date(o.created_at * 1000).toLocaleString();
        const statusBadge =
          o.status === "approved"
            ? `<span class="badge badge-pro">Tasdiqlangan</span>`
            : o.status === "rejected"
            ? `<span class="badge badge-blocked">Rad etilgan</span>`
            : `<span class="badge badge-student">Kutilmoqda</span>`;

        let actionBtns = "";
        if (o.status === "pending") {
          actionBtns = `
          <div style="display:flex; gap:6px;">
            <button class="btn btn-sm btn-primary" onclick="approveOrder(${o.id})" style="padding:4px 8px; font-size:12px;">✅ Tasdiqlash</button>
            <button class="btn btn-sm btn-danger" onclick="rejectOrder(${o.id})" style="padding:4px 8px; font-size:12px; background:rgba(239,68,68,0.2); border:1px solid #ef4444; color:#ef4444;">❌ Rad etish</button>
          </div>
        `;
        } else {
          actionBtns = `<span style="font-size:12px; color:var(--text-muted);">${o.handled_by || '-'}</span>`;
        }

        return `
        <tr>
          <td><strong>#ORD-${o.id}</strong></td>
          <td>
            <div class="user-meta">
              <span class="user-name">${escapeHtml(o.first_name || 'Noma’lum')}</span>
              <span class="user-handle">${o.username ? '@' + o.username : 'yo’q'}</span>
            </div>
          </td>
          <td><code>${o.user_id}</code></td>
          <td><span class="badge badge-${o.tier_id}">${o.tier_name}</span></td>
          <td><strong>${Number(o.price_uzs).toLocaleString()} so'm</strong></td>
          <td>${statusBadge}</td>
          <td style="font-size:12px; color:var(--text-secondary);">${dateStr}</td>
          <td>${actionBtns}</td>
        </tr>
      `;
      })
      .join("");
  } catch (err) {
    elements.ordersTableBody.innerHTML = `<tr><td colspan="8" class="error-state">Xatolik: ${err.message}</td></tr>`;
  }
}

async function approveOrder(orderId) {
  if (!confirm(`#ORD-${orderId} buyurtmasini tasdiqlab, foydalanuvchiga yangi tarifni faollashtirasizmi?`)) return;
  try {
    await api(`/api/admin/orders/${orderId}/approve`, { method: "POST" });
    showToast(`Buyurtma #ORD-${orderId} tasdiqlandi va tarif yoqildi!`);
    loadOrders();
    loadDashboard();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function rejectOrder(orderId) {
  const reason = prompt("Rad etish sababini kiriting:", "Rad etildi");
  if (reason === null) return;
  try {
    await api(`/api/admin/orders/${orderId}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    showToast(`Buyurtma #ORD-${orderId} rad etildi`);
    loadOrders();
    loadDashboard();
  } catch (err) {
    showToast(err.message, "error");
  }
}

window.approveOrder = approveOrder;
window.rejectOrder = rejectOrder;

// Bootstrap
document.addEventListener("DOMContentLoaded", init);

