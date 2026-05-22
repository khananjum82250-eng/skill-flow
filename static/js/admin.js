document.querySelectorAll("[data-confirm]").forEach((element) => {
  element.addEventListener("click", async (event) => {
    if (element.dataset.confirmed === "true") {
      delete element.dataset.confirmed;
      return;
    }

    event.preventDefault();
    const confirmed = await SkillFlowUI.confirmDialog(element.dataset.confirm, {
      title: "Please confirm",
      confirmText: "OK",
      cancelText: "Close",
      danger: element.classList.contains("danger")
    });

    if (!confirmed) return;

    const form = element.closest("form");
    if (form) {
      element.dataset.confirmed = "true";
      if (typeof form.requestSubmit === "function") form.requestSubmit(element);
      else form.submit();
      return;
    }

    if (element.href) {
      window.location.href = element.href;
      return;
    }

    element.dataset.confirmed = "true";
    element.click();
  });
});

document.querySelectorAll("[data-reason-required]").forEach((element) => {
  element.addEventListener("click", async (event) => {
    if (element.dataset.reasonConfirmed === "true") {
      delete element.dataset.reasonConfirmed;
      return;
    }

    event.preventDefault();
    const action = element.dataset.reasonRequired || "action";
    const overlay = document.createElement("div");
    overlay.className = "sf-modal-overlay";
    overlay.innerHTML = `
      <div class="sf-modal warning" role="dialog" aria-modal="true">
        <button class="sf-modal-close" type="button" aria-label="Close"><i class="fa-solid fa-xmark"></i></button>
        <span class="sf-modal-icon"><i class="fa-solid fa-user-shield"></i></span>
        <h2 class="sf-modal-title">${action === "delete" ? "Delete User" : "Block User"}</h2>
        <p class="sf-modal-message">Reason for deleting/blocking this user</p>
        <div class="sf-modal-fields">
          <div class="sf-field">
            <label for="adminModerationReason">Reason</label>
            <textarea id="adminModerationReason" rows="4" maxlength="500" placeholder="Enter reason" required></textarea>
          </div>
        </div>
        <div class="sf-modal-actions">
          <button class="sf-btn sf-btn-secondary" type="button" data-cancel-reason>Cancel</button>
          <button class="sf-btn sf-btn-danger" type="button" data-confirm-reason><i class="fa-solid fa-check"></i> Confirm</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector(".sf-modal-close").addEventListener("click", close);
    overlay.querySelector("[data-cancel-reason]").addEventListener("click", close);
    overlay.addEventListener("click", (clickEvent) => {
      if (clickEvent.target === overlay) close();
    });
    const textarea = overlay.querySelector("textarea");
    textarea.focus();
    overlay.querySelector("[data-confirm-reason]").addEventListener("click", () => {
      const reason = textarea.value.trim();
      if (!reason) {
        SkillFlowUI.toast("Reason is required.", "warning");
        return;
      }
      const form = element.closest("form");
      if (!form) return;
      let input = form.querySelector('input[name="moderation_reason"]');
      if (!input) {
        input = document.createElement("input");
        input.type = "hidden";
        input.name = "moderation_reason";
        form.appendChild(input);
      }
      input.value = reason;
      element.dataset.reasonConfirmed = "true";
      close();
      if (typeof form.requestSubmit === "function") form.requestSubmit(element);
      else form.submit();
    });
  });
});

function normalizeAdminSearchText(value) {
  return (value || "").toString().toLowerCase().replace(/\s+/g, " ").trim();
}

function getAdminSearchRows() {
  return Array.from(document.querySelectorAll("[data-search-row]"));
}

function getAdminSearchText(row) {
  return normalizeAdminSearchText(row.dataset.searchText || row.textContent);
}

function getActiveAdminFilters() {
  const filters = {};
  document.querySelectorAll("[data-admin-filter].active").forEach((button) => {
    const key = button.dataset.adminFilter;
    const value = button.dataset.filterValue || "all";
    if (key && value !== "all") filters[key] = value;
  });
  return filters;
}

function doesAdminRowMatchFilters(row, filters) {
  return Object.entries(filters).every(([key, value]) => {
    if (key === "user-status") return row.dataset.userStatus === value;
    const datasetKey = key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    if (row.dataset[datasetKey] !== undefined) return row.dataset[datasetKey] === value;
    return true;
  });
}

function getOrCreateSearchEmptyState(container) {
  let emptyState = container.querySelector(":scope > .admin-search-empty-state");
  if (!emptyState) {
    emptyState = document.createElement("div");
    emptyState.className = "admin-search-empty-state";
    emptyState.hidden = true;
    emptyState.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i><span>No results found</span>';
    container.appendChild(emptyState);
  }
  return emptyState;
}

function updateAdminSearchResults(input) {
  const query = normalizeAdminSearchText(input?.value || document.querySelector("[data-admin-search]")?.value || "");
  const filters = getActiveAdminFilters();
  const auditCategory = document.querySelector("[data-audit-category-select]")?.value || "all";
  const auditFrom = document.querySelector("[data-audit-date-from]")?.value || "";
  const auditTo = document.querySelector("[data-audit-date-to]")?.value || "";
  const rows = getAdminSearchRows();
  const hasActiveFilters = Object.keys(filters).length > 0 || auditCategory !== "all" || auditFrom || auditTo;
  let visibleCount = 0;

  rows.forEach((row) => {
    const rowDate = row.dataset.auditDate || "";
    const isAuditCategoryMatch = auditCategory === "all" || row.dataset.auditCategory === auditCategory;
    const isAuditDateMatch = (!auditFrom || rowDate >= auditFrom) && (!auditTo || rowDate <= auditTo);
    const isMatch = (!query || getAdminSearchText(row).includes(query)) && doesAdminRowMatchFilters(row, filters) && isAuditCategoryMatch && isAuditDateMatch;
    row.hidden = !isMatch;
    if (isMatch) visibleCount += 1;
  });

  document.querySelectorAll("[data-admin-search-empty]").forEach((emptyState) => {
    emptyState.hidden = true;
  });

  const globalEmptyState = document.querySelector("[data-admin-search-empty='global']") || getOrCreateSearchEmptyState(document.querySelector(".admin-main") || document.body);
  globalEmptyState.dataset.adminSearchEmpty = "global";
  globalEmptyState.hidden = (!query && !hasActiveFilters) || visibleCount > 0;
}

function createAdminSearchInput(placeholder) {
  const input = document.createElement("input");
  input.type = "search";
  input.autocomplete = "off";
  input.dataset.adminSearch = "true";
  input.placeholder = placeholder || "Search admin data";
  input.setAttribute("aria-label", input.placeholder);
  return input;
}

document.querySelectorAll(".admin-toolbar-search").forEach((searchBox) => {
  if (searchBox.querySelector("[data-admin-search]")) return;
  const hint = searchBox.querySelector("span");
  const placeholder = hint?.textContent?.trim() || "Search admin data";
  if (hint) hint.remove();
  searchBox.appendChild(createAdminSearchInput(placeholder));
});

const firstSearchableSection = document.querySelector(".admin-table-wrap, .notification-list, .chat-admin-list");

if (firstSearchableSection && !document.querySelector("[data-admin-search]")) {
  const toolbar = document.createElement("section");
  toolbar.className = "admin-toolbar admin-section admin-generated-search";
  const searchBox = document.createElement("div");
  searchBox.className = "admin-toolbar-search";
  searchBox.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i>';
  searchBox.appendChild(createAdminSearchInput("Search this admin page"));
  toolbar.appendChild(searchBox);

  firstSearchableSection.before(toolbar);
}

document.querySelectorAll("[data-admin-search]").forEach((input) => {
  input.addEventListener("input", () => updateAdminSearchResults(input));
  input.addEventListener("search", () => updateAdminSearchResults(input));
});

document.querySelectorAll("[data-admin-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    const group = button.dataset.adminFilter;
    document.querySelectorAll(`[data-admin-filter="${group}"]`).forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    updateAdminSearchResults(document.querySelector("[data-admin-search]"));
  });
});

document.querySelectorAll("[data-audit-category-select], [data-audit-date-from], [data-audit-date-to]").forEach((input) => {
  input.addEventListener("input", () => updateAdminSearchResults(document.querySelector("[data-admin-search]")));
  input.addEventListener("change", () => updateAdminSearchResults(document.querySelector("[data-admin-search]")));
});

document.querySelectorAll("[data-audit-reset]").forEach((button) => {
  button.addEventListener("click", () => {
    const search = document.querySelector("[data-admin-search]");
    const category = document.querySelector("[data-audit-category-select]");
    const from = document.querySelector("[data-audit-date-from]");
    const to = document.querySelector("[data-audit-date-to]");
    if (search) search.value = "";
    if (category) category.value = "all";
    if (from) from.value = "";
    if (to) to.value = "";
    updateAdminSearchResults(search);
  });
});

const adminSidebar = document.querySelector(".admin-sidebar");
const adminNav = document.querySelector(".admin-nav");
if (adminSidebar && adminNav) {
  const savedSidebarScroll = sessionStorage.getItem("skillflowAdminSidebarScroll");
  if (savedSidebarScroll !== null) {
    adminSidebar.scrollTop = Number(savedSidebarScroll) || 0;
  }

  adminNav.querySelectorAll("a[href]:not(.admin-logout-link)").forEach((link) => {
    link.addEventListener("click", () => {
      sessionStorage.setItem("skillflowAdminSidebarScroll", String(adminSidebar.scrollTop));
    });
  });
}

function escapeExcelCell(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function exportVisibleUsersToExcel() {
  const rows = getAdminSearchRows().filter((row) => !row.hidden && row.dataset.exportUsername);
  const columns = [
    ["Full Name", "exportFullName"],
    ["Username", "exportUsername"],
    ["Email", "exportEmail"],
    ["Location", "exportLocation"],
    ["Skills", "exportSkills"],
    ["Verification", "exportVerification"],
    ["Status", "exportStatus"],
    ["Plan", "exportPlan"],
    ["Email On/Off", "exportEmailNotifications"],
    ["Match On/Off", "exportMatchNotifications"],
    ["Visibility", "exportVisibility"],
    ["Created Date", "exportCreatedDate"]
  ];

  const header = columns.map(([label]) => `<th>${escapeExcelCell(label)}</th>`).join("");
  const body = rows.map((row) => {
    return `<tr>${columns.map(([, key]) => `<td>${escapeExcelCell(row.dataset[key])}</td>`).join("")}</tr>`;
  }).join("");
  const workbook = `
    <html>
      <head><meta charset="UTF-8"></head>
      <body><table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table></body>
    </html>
  `;
  const blob = new Blob([workbook], { type: "application/vnd.ms-excel;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `skillflow-users-${new Date().toISOString().slice(0, 10)}.xls`;
  document.body.appendChild(link);
  link.click();
  URL.revokeObjectURL(link.href);
  link.remove();
}

document.querySelectorAll("[data-export-users]").forEach((button) => {
  button.addEventListener("click", exportVisibleUsersToExcel);
});

function exportVisiblePaymentsToExcel() {
  const rows = getAdminSearchRows().filter((row) => !row.hidden && row.dataset.exportPayer);
  const columns = [
    ["Payer Name", "exportPayer"],
    ["Amount", "exportAmount"],
    ["Payment Status", "exportPaymentStatus"],
    ["Gateway", "exportGateway"],
    ["Order / Payment ID", "exportReference"],
    ["Date", "exportDate"]
  ];

  const header = columns.map(([label]) => `<th>${escapeExcelCell(label)}</th>`).join("");
  const body = rows.map((row) => {
    return `<tr>${columns.map(([, key]) => `<td>${escapeExcelCell(row.dataset[key])}</td>`).join("")}</tr>`;
  }).join("");
  const workbook = `
    <html>
      <head><meta charset="UTF-8"></head>
      <body><table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table></body>
    </html>
  `;
  const blob = new Blob([workbook], { type: "application/vnd.ms-excel;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `skillflow-payments-${new Date().toISOString().slice(0, 10)}.xls`;
  document.body.appendChild(link);
  link.click();
  URL.revokeObjectURL(link.href);
  link.remove();
}

document.querySelectorAll("[data-export-payments]").forEach((button) => {
  button.addEventListener("click", exportVisiblePaymentsToExcel);
});

function exportVisibleAuditLogsToExcel() {
  const rows = getAdminSearchRows().filter((row) => !row.hidden && row.dataset.exportAuditDate);
  const columns = [
    ["Date & Time", "exportAuditDate"],
    ["Admin", "exportAuditAdmin"],
    ["Action", "exportAuditAction"],
    ["Target", "exportAuditTarget"],
    ["Description", "exportAuditDescription"],
    ["IP Address", "exportAuditIp"]
  ];
  const csvEscape = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const header = columns.map(([label]) => csvEscape(label)).join(",");
  const body = rows.map((row) => columns.map(([, key]) => csvEscape(row.dataset[key] || "")).join(",")).join("\n");
  const csv = `${header}${body ? `\n${body}` : ""}`;
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `skillflow-audit-logs-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  URL.revokeObjectURL(link.href);
  link.remove();
}

document.querySelectorAll("[data-export-audit]").forEach((button) => {
  button.addEventListener("click", exportVisibleAuditLogsToExcel);
});

const adminControlsBar = document.querySelector("[data-admin-controls]");
const adminTopbarActions = adminControlsBar?.querySelector(".admin-topbar-actions");
const adminPageHeader = document.querySelector(".admin-page-head, .settings-heading, .notifications-header");

if (adminTopbarActions) {
  if (adminPageHeader) {
    const headingRight = document.createElement("div");
    headingRight.className = "admin-heading-right";

    while (adminPageHeader.children.length > 1) {
      headingRight.appendChild(adminPageHeader.children[1]);
    }

    headingRight.appendChild(adminTopbarActions);
    adminPageHeader.appendChild(headingRight);
    adminControlsBar?.remove();
  } else {
    const pageTitle = document.querySelector(".admin-main > h1");
    const pageSubtitle = pageTitle?.nextElementSibling?.classList.contains("admin-muted")
      ? pageTitle.nextElementSibling
      : null;

    if (pageTitle) {
      const generatedHeader = document.createElement("section");
      generatedHeader.className = "admin-page-head admin-generated-head";
      const headingText = document.createElement("div");

      pageTitle.before(generatedHeader);
      headingText.appendChild(pageTitle);
      if (pageSubtitle) headingText.appendChild(pageSubtitle);
      generatedHeader.appendChild(headingText);

      const headingRight = document.createElement("div");
      headingRight.className = "admin-heading-right";
      headingRight.appendChild(adminTopbarActions);
      generatedHeader.appendChild(headingRight);
      adminControlsBar?.remove();
    }
  }
}

function applyAdminTheme(mode) {
  const isDark = mode === "dark";
  document.body.classList.toggle("admin-theme-dark", isDark);
  document.body.classList.toggle("admin-theme-light", !isDark);
  document.documentElement.dataset.adminTheme = isDark ? "dark" : "light";
}

try {
  const storedTheme = localStorage.getItem("skillflow_admin_theme");
  if (storedTheme === "dark" || storedTheme === "light") {
    applyAdminTheme(storedTheme);
  } else if (document.body.classList.contains("admin-theme-dark")) {
    localStorage.setItem("skillflow_admin_theme", "dark");
  } else if (document.body.classList.contains("admin-theme-light")) {
    localStorage.setItem("skillflow_admin_theme", "light");
  }
} catch (error) {
  console.warn("Unable to read admin theme preference.", error);
}

document.querySelectorAll("[data-admin-theme-toggle]").forEach((toggle) => {
  toggle.addEventListener("change", () => {
    const mode = toggle.checked ? "dark" : "light";
    applyAdminTheme(mode);
    try {
      localStorage.setItem("skillflow_admin_theme", mode);
    } catch (error) {
      console.warn("Unable to save admin theme preference.", error);
    }
  });
});
