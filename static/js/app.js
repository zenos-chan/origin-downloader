document.addEventListener("DOMContentLoaded", () => {
  initSidebar();
  initDropdowns();
  initToasts();
  initPasswordToggles();
  initCountUp();
  initDashboardTable();
  initDashboardLivePolling();
  initChartSwitcher();
  initSettingsTabs();
  initPasswordStrength();
  initFormSubmitStates();
  initMoviesBrowser();
  initTorrentsBrowser();
});

function initSidebar() {
  const sidebar = document.getElementById("mobile-sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  const openBtn = document.getElementById("open-sidebar-btn");
  const closeBtn = document.getElementById("close-sidebar-btn");

  if (!sidebar || !backdrop) return;

  const openSidebar = () => {
    sidebar.classList.remove("-translate-x-full");
    backdrop.classList.remove("opacity-0", "pointer-events-none");
    backdrop.classList.add("opacity-100");
    document.body.classList.add("overflow-hidden", "lg:overflow-auto");
  };

  const closeSidebar = () => {
    sidebar.classList.add("-translate-x-full");
    backdrop.classList.add("opacity-0", "pointer-events-none");
    backdrop.classList.remove("opacity-100");
    document.body.classList.remove("overflow-hidden", "lg:overflow-auto");
  };

  openBtn?.addEventListener("click", openSidebar);
  closeBtn?.addEventListener("click", closeSidebar);
  backdrop.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSidebar();
  });
}

function initDropdowns() {
  const toggles = document.querySelectorAll("[data-dropdown-toggle]");
  const menus = document.querySelectorAll("[data-dropdown-menu]");

  const closeAll = () => {
    menus.forEach((menu) => {
      menu.classList.add("hidden", "opacity-0", "scale-95");
      menu.classList.remove("opacity-100", "scale-100");
    });
  };

  toggles.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const targetId = btn.getAttribute("data-dropdown-toggle");
      const menu = document.getElementById(targetId);
      if (!menu) return;

      const isHidden = menu.classList.contains("hidden");
      closeAll();
      if (isHidden) {
        menu.classList.remove("hidden");
        requestAnimationFrame(() => {
          menu.classList.remove("opacity-0", "scale-95");
          menu.classList.add("opacity-100", "scale-100");
        });
      }
    });
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-dropdown-menu]")) {
      closeAll();
    }
  });
}

function initToasts() {
  const toasts = document.querySelectorAll("[data-toast]");
  toasts.forEach((toast) => {
    const closeBtn = toast.querySelector("[data-toast-close]");
    const dismiss = () => {
      toast.style.transition = "opacity 0.25s ease, transform 0.25s ease";
      toast.style.opacity = "0";
      toast.style.transform = "translateX(20px)";
      setTimeout(() => toast.remove(), 260);
    };
    closeBtn?.addEventListener("click", dismiss);
    setTimeout(dismiss, 5000);
  });
}

function initPasswordToggles() {
  document.querySelectorAll("[data-toggle-password]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-toggle-password");
      const input = document.getElementById(targetId);
      const icon = btn.querySelector("i");
      if (!input || !icon) return;

      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";
      icon.classList.toggle("fa-eye", !isPassword);
      icon.classList.toggle("fa-eye-slash", isPassword);
    });
  });
}

function initCountUp() {
  const counters = document.querySelectorAll("[data-count-target]");
  counters.forEach((el) => {
    const target = parseFloat(el.getAttribute("data-count-target"));
    const suffix = el.getAttribute("data-count-suffix") || "";
    const decimals = parseInt(el.getAttribute("data-count-decimals") || "0", 10);
    if (Number.isNaN(target)) return;

    const duration = 850;
    const start = performance.now();

    const step = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = target * eased;
      el.textContent =
        decimals > 0
          ? `${current.toFixed(decimals)}${suffix}`
          : `${Math.round(current).toLocaleString()}${suffix}`;
      if (progress < 1) {
        requestAnimationFrame(step);
      }
    };
    requestAnimationFrame(step);
  });
}

function initDashboardTable() {
  const searchInput = document.getElementById("activity-search");
  const filterButtons = document.querySelectorAll("[data-status-filter]");
  const rows = document.querySelectorAll("[data-activity-row]");
  const emptyState = document.getElementById("activity-empty");

  if (!rows.length) return;

  let activeFilter = "all";

  const applyFilter = () => {
    const query = (searchInput?.value || "").trim().toLowerCase();
    let visibleCount = 0;

    rows.forEach((row) => {
      const status = (row.getAttribute("data-status") || "").toLowerCase();
      const text = row.textContent.toLowerCase();
      const matchesStatus = activeFilter === "all" || status === activeFilter;
      const matchesQuery = !query || text.includes(query);

      if (matchesStatus && matchesQuery) {
        row.classList.remove("hidden");
        visibleCount++;
      } else {
        row.classList.add("hidden");
      }
    });

    if (emptyState) {
      emptyState.classList.toggle("hidden", visibleCount > 0);
    }
  };

  searchInput?.addEventListener("input", applyFilter);

  filterButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      activeFilter = btn.getAttribute("data-status-filter") || "all";
      filterButtons.forEach((b) => {
        b.classList.remove("bg-indigo-600", "text-white", "shadow-sm");
        b.classList.add("bg-slate-100", "text-slate-600", "hover:bg-slate-200");
      });
      btn.classList.remove("bg-slate-100", "text-slate-600", "hover:bg-slate-200");
      btn.classList.add("bg-indigo-600", "text-white", "shadow-sm");
      applyFilter();
    });
  });
}

function initDashboardLivePolling() {
  const tbody = document.getElementById("transfers-tbody");
  if (!tbody) return;

  const hasActive = () =>
    Boolean(tbody.querySelector('tr[data-status="active"]'));
  if (!hasActive()) return;

  const formatSize = (bytes) => {
    if (!bytes) return "—";
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return `${gb.toFixed(2)} GB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const timer = setInterval(async () => {
    try {
      const resp = await fetch("/api/downloads");
      if (!resp.ok) return;
      const data = await resp.json();
      const jobs = data.jobs || [];

      jobs.forEach((job) => {
        const row = tbody.querySelector(`tr[data-job-id="${job.id}"]`);
        if (!row) return;
        const status =
          job.status === "resolving" || job.status === "downloading"
            ? "active"
            : job.status;
        row.setAttribute("data-status", status);

        const sizeCell = row.querySelector("[data-col-size]");
        if (sizeCell) {
          sizeCell.textContent = formatSize(
            job.total_bytes || job.downloaded_bytes || 0
          );
        }

        const bar = row.querySelector("[data-col-bar]");
        if (bar) {
          bar.style.width = `${job.progress_pct}%`;
          bar.className = `h-full rounded-full ${
            status === "failed"
              ? "bg-rose-500"
              : status === "completed"
              ? "bg-emerald-500"
              : status === "cancelled"
              ? "bg-slate-400"
              : "bg-indigo-600"
          }`;
        }

        const pct = row.querySelector("[data-col-pct]");
        if (pct) pct.textContent = `${job.progress_pct}%`;

        const statusCell = row.querySelector("[data-col-status]");
        if (statusCell) {
          const badgeMap = {
            completed: "bg-emerald-50 text-emerald-700 border-emerald-200",
            active: "bg-sky-50 text-sky-700 border-sky-200",
            failed: "bg-rose-50 text-rose-700 border-rose-200",
            cancelled: "bg-slate-100 text-slate-600 border-slate-200",
          };
          const dot =
            status === "active"
              ? '<span class="h-1.5 w-1.5 rounded-full bg-sky-500 animate-pulse"></span>'
              : "";
          statusCell.innerHTML = `<span class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${
            badgeMap[status] || "bg-slate-100 text-slate-600 border-slate-200"
          }">${dot}${status}</span>`;
        }
      });

      if (!jobs.some((j) => j.status === "resolving" || j.status === "downloading")) {
        clearInterval(timer);
      }
    } catch (_) {
      // Ignore transient errors
    }
  }, 1500);
}

function initChartSwitcher() {
  const buttons = document.querySelectorAll("[data-chart-range]");
  const barsContainer = document.getElementById("traffic-chart-bars");
  if (!buttons.length || !barsContainer) return;

  let datasets = { "7d": [], "30d": [] };
  try {
    datasets = JSON.parse(
      barsContainer.getAttribute("data-chart-datasets") || '{"7d":[],"30d":[]}'
    );
  } catch (_) {
    return;
  }

  const renderBars = (range) => {
    const items = datasets[range] || datasets["7d"] || [];
    barsContainer.innerHTML = items
      .map(
        (item, idx) => `
      <div class="flex-1 flex flex-col items-center gap-2 group h-full justify-end">
        <div class="relative w-full flex-1 flex items-end justify-center">
          <span class="pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-200 absolute -top-7 px-2 py-0.5 rounded bg-slate-900 text-white text-[11px] font-medium whitespace-nowrap shadow">
            ${item.count} ${item.count === "1" ? "download" : "downloads"}
          </span>
          <div
            class="w-full max-w-[40px] rounded-t-xl transition-all duration-300 animate-bar-grow shadow-sm ${
              item.empty
                ? "bg-slate-200"
                : "bg-gradient-to-t from-indigo-600 via-indigo-500 to-violet-400 group-hover:from-indigo-500 group-hover:to-fuchsia-400"
            }"
            style="height: ${item.val}%; animation-delay: ${idx * 45}ms"
          ></div>
        </div>
        <span class="text-xs font-medium text-slate-500">${item.label}</span>
      </div>
    `
      )
      .join("");
  };

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const range = btn.getAttribute("data-chart-range");
      buttons.forEach((b) => {
        b.classList.remove("bg-white", "text-slate-900", "shadow-sm");
        b.classList.add("text-slate-500", "hover:text-slate-800");
      });
      btn.classList.add("bg-white", "text-slate-900", "shadow-sm");
      btn.classList.remove("text-slate-500", "hover:text-slate-800");
      renderBars(range);
    });
  });
}

function initSettingsTabs() {
  const tabBtns = document.querySelectorAll("[data-settings-tab]");
  const panels = document.querySelectorAll("[data-settings-panel]");
  if (!tabBtns.length || !panels.length) return;

  const activateTab = (tabName) => {
    tabBtns.forEach((btn) => {
      const isActive = btn.getAttribute("data-settings-tab") === tabName;
      btn.classList.toggle("bg-indigo-50", isActive);
      btn.classList.toggle("text-indigo-700", isActive);
      btn.classList.toggle("border-indigo-200", isActive);
      btn.classList.toggle("shadow-sm", isActive);
      btn.classList.toggle("text-slate-600", !isActive);
      btn.classList.toggle("border-transparent", !isActive);
      btn.classList.toggle("hover:bg-slate-100", !isActive);
    });

    panels.forEach((panel) => {
      const match = panel.getAttribute("data-settings-panel") === tabName;
      panel.classList.toggle("hidden", !match);
    });

    const activeInput = document.getElementById("active-settings-tab");
    if (activeInput) activeInput.value = tabName;
  };

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      activateTab(btn.getAttribute("data-settings-tab"));
    });
  });

  const initialTab =
    document.getElementById("settings-container")?.getAttribute("data-initial-tab") || "general";
  activateTab(initialTab);
}

function initPasswordStrength() {
  const input = document.getElementById("new_password");
  const bar = document.getElementById("password-strength-bar");
  const label = document.getElementById("password-strength-label");
  if (!input || !bar || !label) return;

  input.addEventListener("input", () => {
    const val = input.value;
    if (!val) {
      bar.style.width = "0%";
      bar.className = "h-full rounded-full transition-all duration-300 bg-slate-300";
      label.textContent = "Enter a new password to check strength";
      return;
    }

    let score = 0;
    if (val.length >= 8) score++;
    if (/[A-Z]/.test(val) && /[a-z]/.test(val)) score++;
    if (/\d/.test(val)) score++;
    if (/[^A-Za-z0-9]/.test(val)) score++;

    const stages = [
      { width: "25%", color: "bg-rose-500", text: "Weak — use at least 8 characters" },
      { width: "50%", color: "bg-amber-500", text: "Fair — add numbers or uppercase letters" },
      { width: "75%", color: "bg-sky-500", text: "Good — add a symbol for extra security" },
      { width: "100%", color: "bg-emerald-500", text: "Strong — great password!" },
    ];
    const stage = stages[Math.max(0, score - 1)];
    bar.style.width = stage.width;
    bar.className = `h-full rounded-full transition-all duration-300 ${stage.color}`;
    label.textContent = stage.text;
  });
}

function initFormSubmitStates() {
  document.querySelectorAll("form[data-loading-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      const btn = form.querySelector("button[type='submit']");
      if (!btn) return;
      btn.disabled = true;
      btn.classList.add("opacity-80", "cursor-not-allowed");
      const spinner = btn.querySelector("[data-submit-spinner]");
      const label = btn.querySelector("[data-submit-label]");
      spinner?.classList.remove("hidden");
      if (label && btn.getAttribute("data-loading-text")) {
        label.textContent = btn.getAttribute("data-loading-text");
      }
    });
  });
}

function initMoviesBrowser() {
  const container = document.getElementById("movies-browser");
  if (!container) return;

  const csrfToken =
    document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
  const folders = JSON.parse(container.getAttribute("data-folders") || "{}");

  const modal = document.getElementById("movie-modal");
  const modalBackdrop = document.getElementById("movie-modal-backdrop");
  const closeBtn = document.getElementById("movie-modal-close");
  const modalTitle = document.getElementById("modal-movie-title");
  const modalPoster = document.getElementById("modal-movie-poster");
  const modalImdbLink = document.getElementById("modal-imdb-link");
  const modalImdbText = document.getElementById("modal-imdb-text");
  const modalSourceLink = document.getElementById("modal-source-link");
  const mediaTypeSelect = document.getElementById("modal-media-type");
  const folderPreview = document.getElementById("modal-folder-preview");
  const optionsContainer = document.getElementById("modal-options-container");

  const queuePanel = document.getElementById("download-queue-panel");
  const queueList = document.getElementById("download-queue-list");

  let currentMovieTitle = "";
  let pollTimer = null;

  const updateFolderPreview = () => {
    if (!mediaTypeSelect || !folderPreview) return;
    folderPreview.textContent = folders[mediaTypeSelect.value] || "";
  };
  mediaTypeSelect?.addEventListener("change", updateFolderPreview);

  const closeModal = () => {
    modal?.classList.add("hidden");
    modal?.classList.remove("flex");
  };
  closeBtn?.addEventListener("click", closeModal);
  modalBackdrop?.addEventListener("click", closeModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  const escapeHtml = (str) =>
    String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const formatBytes = (bytes) => {
    if (!bytes) return "0 MB";
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return `${gb.toFixed(2)} GB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const startDownload = async (url, label, filename = "") => {
    const mediaType = mediaTypeSelect?.value || "movie";
    const resp = await fetch("/api/hdhub4u/download", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({
        title: currentMovieTitle,
        quality_label: label,
        url,
        media_type: mediaType,
        filename,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.error || "Failed to start download.");
    }
    closeModal();
    await refreshDownloads();
    startPolling();
  };

  const renderOptions = (options) => {
    if (!optionsContainer) return;
    if (!options || !options.length) {
      optionsContainer.innerHTML = `
        <div class="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-800">
          No direct download links were detected on this post. Try opening the Source Page link above.
        </div>
      `;
      return;
    }

    optionsContainer.innerHTML = options
      .map(
        (opt, idx) => `
      <div class="rounded-2xl border border-slate-200/80 bg-white p-3.5 shadow-sm" data-option-card="${idx}">
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0">
            <p class="truncate text-sm font-bold text-slate-800">${escapeHtml(opt.label)}</p>
            <p class="text-[11px] text-slate-400 truncate">${escapeHtml(opt.host)}</p>
          </div>
          <div class="flex flex-wrap items-center gap-2 shrink-0">
            ${
              opt.resolvable
                ? `
              <button
                type="button"
                data-resolve-idx="${idx}"
                class="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
              >
                <i class="fa-solid fa-server text-[11px]"></i>
                Mirrors
              </button>
              <button
                type="button"
                data-direct-dl-idx="${idx}"
                class="inline-flex items-center gap-1.5 rounded-xl bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-indigo-500"
              >
                <i class="fa-solid fa-download text-[11px]"></i>
                Download
              </button>
            `
                : `
              <a
                href="${escapeHtml(opt.url)}"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
              >
                <i class="fa-solid fa-arrow-up-right-from-square text-[11px]"></i>
                Open Host
              </a>
            `
            }
          </div>
        </div>
        <div class="hidden mt-3 border-t border-slate-100 pt-2.5 space-y-2" data-mirrors-box="${idx}"></div>
      </div>
    `
      )
      .join("");

    options.forEach((opt, idx) => {
      const dlBtn = optionsContainer.querySelector(`[data-direct-dl-idx="${idx}"]`);
      dlBtn?.addEventListener("click", async () => {
        dlBtn.disabled = true;
        dlBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Starting...';
        try {
          await startDownload(opt.url, opt.label);
        } catch (err) {
          dlBtn.disabled = false;
          dlBtn.innerHTML = '<i class="fa-solid fa-download"></i> Download';
          alert(err.message);
        }
      });

      const resolveBtn = optionsContainer.querySelector(`[data-resolve-idx="${idx}"]`);
      const mirrorsBox = optionsContainer.querySelector(`[data-mirrors-box="${idx}"]`);
      resolveBtn?.addEventListener("click", async () => {
        if (!mirrorsBox) return;
        resolveBtn.disabled = true;
        resolveBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Resolving...';
        try {
          const resp = await fetch("/api/hdhub4u/resolve", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRF-Token": csrfToken,
            },
            body: JSON.stringify({ url: opt.url, title: currentMovieTitle }),
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.error || "Could not resolve mirrors.");

          const mirrors = data.mirrors || [];
          const isPack = mirrors.some((m) => m.is_pack_item);
          mirrorsBox.classList.remove("hidden");
          mirrorsBox.innerHTML =
            (isPack && mirrors.length > 1
              ? `<div class="flex items-center justify-between pb-1">
                   <span class="text-[11px] font-semibold text-slate-500">${mirrors.length} episodes in pack</span>
                   <button type="button" data-pack-dl-all="${idx}" class="rounded-lg bg-indigo-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-indigo-500">
                     Download All
                   </button>
                 </div>`
              : "") +
            mirrors
              .map(
                (m, mIdx) => `
            <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between rounded-xl bg-slate-50 px-3 py-2">
              <div class="min-w-0">
                <p class="text-xs font-semibold text-slate-700">${escapeHtml(m.server)}</p>
                <p class="truncate font-mono text-[11px] text-slate-400">${escapeHtml(m.filename)}</p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <a
                  href="${escapeHtml(m.url)}"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-600 hover:bg-slate-100"
                >
                  Browser
                </a>
                <button
                  type="button"
                  data-mirror-dl="${idx}-${mIdx}"
                  class="rounded-lg bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-500"
                >
                  Save to Folder
                </button>
              </div>
            </div>
          `
              )
              .join("");

          const dlAllBtn = mirrorsBox.querySelector(`[data-pack-dl-all="${idx}"]`);
          dlAllBtn?.addEventListener("click", async () => {
            dlAllBtn.disabled = true;
            dlAllBtn.textContent = "Queuing...";
            try {
              for (const m of mirrors) {
                await startDownload(m.url, opt.label, m.filename);
              }
            } catch (err) {
              dlAllBtn.disabled = false;
              dlAllBtn.textContent = "Download All";
              alert(err.message);
            }
          });

          mirrors.forEach((m, mIdx) => {
            const mBtn = mirrorsBox.querySelector(`[data-mirror-dl="${idx}-${mIdx}"]`);
            mBtn?.addEventListener("click", async () => {
              mBtn.disabled = true;
              mBtn.textContent = "Starting...";
              try {
                await startDownload(m.url, opt.label, m.filename);
              } catch (err) {
                mBtn.disabled = false;
                mBtn.textContent = "Save to Folder";
                alert(err.message);
              }
            });
          });
          resolveBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mirrors Ready';
        } catch (err) {
          resolveBtn.disabled = false;
          resolveBtn.innerHTML = '<i class="fa-solid fa-server"></i> Mirrors';
          mirrorsBox.classList.remove("hidden");
          mirrorsBox.innerHTML = `<p class="text-xs text-rose-600">${escapeHtml(err.message)}</p>`;
        }
      });
    });
  };

  document.querySelectorAll("[data-open-movie]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const movieUrl = btn.getAttribute("data-movie-url") || "";
      currentMovieTitle = btn.getAttribute("data-movie-title") || "Release";
      const poster = btn.getAttribute("data-movie-poster") || "";
      const mediaType = btn.getAttribute("data-movie-type") || "movie";

      modalTitle.textContent = currentMovieTitle;
      modalSourceLink.href = movieUrl;
      if (poster) {
        modalPoster.src = poster;
        modalPoster.classList.remove("hidden");
      } else {
        modalPoster.classList.add("hidden");
      }
      modalImdbLink?.classList.add("hidden");
      if (mediaTypeSelect) {
        mediaTypeSelect.value = mediaType;
        updateFolderPreview();
      }

      optionsContainer.innerHTML = `
        <div class="flex items-center justify-center gap-2.5 py-8 text-sm text-slate-500">
          <i class="fa-solid fa-circle-notch fa-spin text-indigo-600"></i>
          Fetching download links...
        </div>
      `;

      modal.classList.remove("hidden");
      modal.classList.add("flex");

      try {
        const resp = await fetch(
          `/api/hdhub4u/details?url=${encodeURIComponent(movieUrl)}`
        );
        const details = await resp.json();
        if (!resp.ok) throw new Error(details.error || "Failed to load details.");

        if (details.imdb_url) {
          modalImdbLink.href = details.imdb_url;
          modalImdbText.textContent = details.imdb_rating
            ? `IMDb ${details.imdb_rating}`
            : "IMDb";
          modalImdbLink.classList.remove("hidden");
        }
        renderOptions(details.download_options || []);
      } catch (err) {
        optionsContainer.innerHTML = `
          <div class="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700">
            ${escapeHtml(err.message)}
          </div>
        `;
      }
    });
  });

  const renderQueue = (jobs) => {
    if (!queuePanel || !queueList) return;
    if (!jobs || !jobs.length) {
      queuePanel.classList.add("hidden");
      return;
    }

    queuePanel.classList.remove("hidden");
    queueList.innerHTML = jobs
      .map((job) => {
        const statusStyles = {
          resolving: "bg-indigo-50 text-indigo-700",
          downloading: "bg-sky-50 text-sky-700",
          completed: "bg-emerald-50 text-emerald-700",
          failed: "bg-rose-50 text-rose-700",
          cancelled: "bg-slate-100 text-slate-600",
        };
        const badge = statusStyles[job.status] || "bg-slate-100 text-slate-600";
        const isActive = job.status === "resolving" || job.status === "downloading";

        return `
        <div class="rounded-2xl border border-slate-200/80 bg-slate-50/70 p-4">
          <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div class="min-w-0">
              <p class="truncate text-sm font-bold text-slate-800">${escapeHtml(job.filename || job.title)}</p>
              <p class="truncate font-mono text-[11px] text-slate-500">${escapeHtml(job.destination_dir)}</p>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <span class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize ${badge}">
                ${escapeHtml(job.status)}
              </span>
              ${
                isActive
                  ? `<button type="button" data-cancel-job="${escapeHtml(job.id)}" class="rounded-lg border border-rose-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-rose-600 hover:bg-rose-50">Cancel</button>`
                  : ""
              }
            </div>
          </div>
          <div class="mt-3 flex items-center gap-3">
            <div class="h-2 flex-1 overflow-hidden rounded-full bg-slate-200">
              <div
                class="h-full rounded-full transition-all duration-300 ${job.status === "failed" ? "bg-rose-500" : job.status === "completed" ? "bg-emerald-500" : "bg-indigo-600"}"
                style="width: ${job.progress_pct}%"
              ></div>
            </div>
            <span class="text-xs font-semibold text-slate-600 whitespace-nowrap">
              ${job.progress_pct}% · ${formatBytes(job.downloaded_bytes)}${job.total_bytes ? " / " + formatBytes(job.total_bytes) : ""}${isActive && job.speed_mbps ? " · " + job.speed_mbps + " MB/s" : ""}
            </span>
          </div>
          ${job.error ? `<p class="mt-2 text-xs text-rose-600">${escapeHtml(job.error)}</p>` : ""}
        </div>
      `;
      })
      .join("");

    queueList.querySelectorAll("[data-cancel-job]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const jobId = btn.getAttribute("data-cancel-job");
        await fetch(`/api/downloads/${encodeURIComponent(jobId)}/cancel`, {
          method: "POST",
          headers: { "X-CSRF-Token": csrfToken },
        });
        refreshDownloads();
      });
    });
  };

  const refreshDownloads = async () => {
    try {
      const resp = await fetch("/api/downloads");
      if (!resp.ok) return;
      const data = await resp.json();
      const jobs = data.jobs || [];
      renderQueue(jobs);
      const hasActive = jobs.some(
        (j) => j.status === "resolving" || j.status === "downloading"
      );
      if (!hasActive && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } catch (_) {
      // Ignore transient polling errors
    }
  };

  const startPolling = () => {
    if (pollTimer) return;
    pollTimer = setInterval(refreshDownloads, 1200);
  };

  refreshDownloads().then(() => {
    if (queueList && queueList.querySelector("[data-cancel-job]")) {
      startPolling();
    }
  });
}

function initTorrentsBrowser() {
  const container = document.getElementById("torrents-browser");
  if (!container) return;

  const csrfToken =
    document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
  const category = container.getAttribute("data-category") || "movies";
  const folders = JSON.parse(container.getAttribute("data-folders") || "{}");

  const queuePanel = document.getElementById("torrent-queue-panel");
  const queueList = document.getElementById("torrent-queue-list");
  const modal = document.getElementById("torrent-modal");
  const modalBackdrop = document.getElementById("torrent-modal-backdrop");
  const modalClose = document.getElementById("tmodal-close");
  const modalTitle = document.getElementById("tmodal-title");
  const modalBody = document.getElementById("tmodal-body");

  let pollTimer = null;

  const escapeHtml = (str) =>
    String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const closeModal = () => {
    modal?.classList.add("hidden");
    modal?.classList.remove("flex");
  };
  modalClose?.addEventListener("click", closeModal);
  modalBackdrop?.addEventListener("click", closeModal);

  const renderQueue = (jobs) => {
    if (!queuePanel || !queueList) return;
    if (!jobs || !jobs.length) {
      queuePanel.classList.add("hidden");
      return;
    }
    queuePanel.classList.remove("hidden");
    queueList.innerHTML = jobs
      .map((job) => {
        const isActive = job.status === "resolving" || job.status === "downloading";
        const badgeMap = {
          resolving: "bg-indigo-50 text-indigo-700",
          downloading: "bg-sky-50 text-sky-700",
          completed: "bg-emerald-50 text-emerald-700",
          failed: "bg-rose-50 text-rose-700",
          cancelled: "bg-slate-100 text-slate-600",
        };
        return `
        <div class="rounded-2xl border border-slate-200/80 bg-slate-50/70 p-4">
          <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div class="min-w-0">
              <p class="truncate text-sm font-bold text-slate-800">${escapeHtml(job.filename || job.title)}</p>
              <p class="truncate font-mono text-[11px] text-slate-500">${escapeHtml(job.destination_dir)}</p>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <span class="rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize ${badgeMap[job.status] || "bg-slate-100 text-slate-600"}">
                ${escapeHtml(job.status)}
              </span>
              ${
                isActive
                  ? `<button type="button" data-tcancel="${escapeHtml(job.id)}" class="rounded-lg border border-rose-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-rose-600 hover:bg-rose-50">Cancel</button>`
                  : ""
              }
            </div>
          </div>
          <div class="mt-3 flex items-center gap-3">
            <div class="h-2 flex-1 overflow-hidden rounded-full bg-slate-200">
              <div class="h-full rounded-full ${job.status === "failed" ? "bg-rose-500" : job.status === "completed" ? "bg-emerald-500" : "bg-indigo-600"}" style="width: ${job.progress_pct}%"></div>
            </div>
            <span class="text-xs font-semibold text-slate-600">${job.progress_pct}%${isActive && job.speed_mbps ? ` · ${job.speed_mbps} MB/s` : ""}</span>
          </div>
          ${job.error ? `<p class="mt-2 text-xs text-rose-600">${escapeHtml(job.error)}</p>` : ""}
        </div>`;
      })
      .join("");

    queueList.querySelectorAll("[data-tcancel]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-tcancel");
        await fetch(`/api/downloads/${encodeURIComponent(id)}/cancel`, {
          method: "POST",
          headers: { "X-CSRF-Token": csrfToken },
        });
        refreshQueue();
      });
    });
  };

  const refreshQueue = async () => {
    try {
      const resp = await fetch("/api/downloads");
      if (!resp.ok) return;
      const data = await resp.json();
      const jobs = data.jobs || [];
      renderQueue(jobs);
      const hasActive = jobs.some(
        (j) => j.status === "resolving" || j.status === "downloading"
      );
      if (!hasActive && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } catch (_) {}
  };

  const startPolling = () => {
    if (!pollTimer) pollTimer = setInterval(refreshQueue, 1500);
  };

  const triggerTorrentDownload = async ({ title, mediaType, torrentPageUrl, magnet = "" }) => {
    const resp = await fetch("/api/1337x/download", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({
        title,
        media_type: mediaType,
        category,
        torrent_page_url: torrentPageUrl,
        magnet,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Could not start torrent download.");
    await refreshQueue();
    startPolling();
  };

  container.querySelectorAll("[data-torrent-download]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const orig = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Queuing...';
      try {
        await triggerTorrentDownload({
          title: btn.getAttribute("data-title"),
          mediaType: btn.getAttribute("data-media-type") || "movie",
          torrentPageUrl: btn.getAttribute("data-url"),
        });
      } catch (err) {
        alert(err.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
      }
    });
  });

  container.querySelectorAll("[data-torrent-inspect]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const url = btn.getAttribute("data-url");
      const title = btn.getAttribute("data-title");
      const mediaType = btn.getAttribute("data-media-type") || "movie";

      modalTitle.textContent = title;
      modalBody.innerHTML =
        '<div class="py-6 text-center text-slate-500"><i class="fa-solid fa-circle-notch fa-spin text-indigo-600 mr-2"></i>Fetching magnet link...</div>';
      modal.classList.remove("hidden");
      modal.classList.add("flex");

      try {
        const resp = await fetch(
          `/api/1337x/details?url=${encodeURIComponent(url)}&category=${encodeURIComponent(category)}`
        );
        const details = await resp.json();
        if (!resp.ok) throw new Error(details.error || "Failed to fetch torrent details.");

        const dest = folders[mediaType] || "";
        modalBody.innerHTML = `
          <p class="text-slate-500">Destination folder: <span class="font-mono text-slate-700">${escapeHtml(dest)}</span></p>
          <p>Size: <strong>${escapeHtml(details.size)}</strong> · Seeders: <strong class="text-emerald-600">${details.seeders}</strong> · Leechers: <strong class="text-rose-600">${details.leechers}</strong></p>
          ${
            details.magnet
              ? `
            <textarea readonly rows="3" class="w-full rounded-xl border border-slate-200 bg-slate-50 p-2.5 font-mono text-[11px] text-slate-700">${escapeHtml(details.magnet)}</textarea>
            <div class="flex flex-wrap items-center justify-end gap-2 pt-1">
              <a href="${escapeHtml(details.magnet)}" class="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                <i class="fa-solid fa-magnet mr-1 text-amber-600"></i> Open in Torrent App
              </a>
              <button type="button" id="tmodal-dl-btn" class="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500">
                <i class="fa-solid fa-download mr-1"></i> Download via Engine
              </button>
            </div>
          `
              : '<p class="text-rose-600">No magnet URI found on this page.</p>'
          }
        `;

        document.getElementById("tmodal-dl-btn")?.addEventListener("click", async () => {
          await triggerTorrentDownload({
            title,
            mediaType,
            torrentPageUrl: url,
            magnet: details.magnet,
          });
          closeModal();
        });
      } catch (err) {
        modalBody.innerHTML = `<p class="rounded-xl bg-rose-50 p-3 text-rose-700">${escapeHtml(err.message)}</p>`;
      }
    });
  });

  refreshQueue().then(() => {
    if (queueList && queueList.querySelector("[data-tcancel]")) {
      startPolling();
    }
  });
}
