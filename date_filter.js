/* Shared date-filter toolbar.
 * Renders preset buttons (Today / 7d / 30d / 90d / 180d / 1y / All) into a host element.
 * Persists selection to localStorage. Calls onChange(rangeKey, startISO, endISO) when selection changes.
 *
 * Usage:
 *   <div id="dateFilter"></div>
 *   <script src="date_filter.js"></script>
 *   <script>
 *     DateFilter.mount("dateFilter", {
 *       onChange: (key, startISO, endISO) => { ... },
 *       defaultKey: "all",            // optional, falls back to localStorage
 *       storageKey: "ccusage.dateRange",  // optional, customize per page
 *     });
 *   </script>
 */
(function (root) {
  const PRESETS = [
    { key: "today", label: "Today",     days: 0 },
    { key: "7d",    label: "Last 7d",   days: 7 },
    { key: "30d",   label: "Last 30d",  days: 30 },
    { key: "90d",   label: "Last 90d",  days: 90 },
    { key: "180d",  label: "Last 180d", days: 180 },
    { key: "1y",    label: "Last year", days: 365 },
    { key: "all",   label: "All time",  days: null },
  ];

  function rangeFor(key, refDate) {
    const ref = refDate ? new Date(refDate) : new Date();
    const end = new Date(Date.UTC(ref.getUTCFullYear(), ref.getUTCMonth(), ref.getUTCDate(), 23, 59, 59));
    const preset = PRESETS.find(p => p.key === key) || PRESETS[6];
    if (preset.days === null) return { startISO: null, endISO: null, key };
    const start = new Date(end);
    start.setUTCDate(end.getUTCDate() - preset.days);
    start.setUTCHours(0, 0, 0, 0);
    return {
      startISO: start.toISOString().slice(0, 10),
      endISO:   end.toISOString().slice(0, 10),
      key,
    };
  }

  function inRange(dateStr, startISO, endISO) {
    if (!startISO && !endISO) return true;
    if (startISO && dateStr < startISO) return false;
    if (endISO   && dateStr > endISO)   return false;
    return true;
  }

  function injectStyles() {
    if (document.getElementById("date-filter-styles")) return;
    const s = document.createElement("style");
    s.id = "date-filter-styles";
    s.textContent = `
      .df-bar {
        display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
        background: rgba(26, 32, 40, 0.92); border: 1px solid var(--border, #2a3441);
        border-radius: 10px; padding: 12px 16px; margin-bottom: 20px;
        position: sticky; top: 0; z-index: 50;
        backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
      }
      .df-label { color: var(--muted, #8a93a3); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-right: 8px; }
      .df-extras { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-left: 16px; }
      .df-extras select {
        background: var(--bg, #0f1419); color: var(--text, #e6e9ef);
        border: 1px solid var(--border, #2a3441); border-radius: 6px;
        padding: 5px 8px; font-family: inherit; font-size: 12px; max-width: 220px;
      }
      .df-btn {
        background: var(--bg, #0f1419); color: var(--muted, #8a93a3);
        border: 1px solid var(--border, #2a3441); border-radius: 6px;
        padding: 6px 12px; font-family: inherit; font-size: 12px; cursor: pointer;
      }
      .df-btn:hover { color: var(--text, #e6e9ef); border-color: var(--accent, #d97757); }
      .df-btn.active { background: var(--accent, #d97757); color: white; border-color: var(--accent, #d97757); }
      .df-info {
        color: var(--muted, #8a93a3); font-size: 12px;
        margin-left: 8px; padding: 0 10px;
        border-left: 1px solid var(--border, #2a3441);
        white-space: nowrap;
      }
    `;
    document.head.appendChild(s);
  }

  function mount(hostId, opts = {}) {
    injectStyles();
    const host = document.getElementById(hostId);
    if (!host) return;
    // Let .df-bar's sticky positioning anchor to the body, not just the host wrapper.
    host.style.display = "contents";
    const storageKey = opts.storageKey || "ccusage.dateRange";
    const stored = localStorage.getItem(storageKey);
    const initialKey = stored || opts.defaultKey || "all";

    host.innerHTML = `
      <div class="df-bar">
        <span class="df-label">Date range</span>
        ${PRESETS.map(p => `<button class="df-btn" data-key="${p.key}">${p.label}</button>`).join("")}
        <span class="df-info" id="${hostId}-info"></span>
        <span class="df-extras" id="${hostId}-extras">${opts.extras || ""}</span>
      </div>
    `;

    function setActive(key) {
      host.querySelectorAll(".df-btn").forEach(b => b.classList.toggle("active", b.dataset.key === key));
      const r = rangeFor(key, opts.referenceDate);
      const info = document.getElementById(hostId + "-info");
      if (info) {
        info.textContent = (r.startISO && r.endISO)
          ? `${r.startISO} → ${r.endISO}`
          : "no filter";
      }
      localStorage.setItem(storageKey, key);
      if (typeof opts.onChange === "function") opts.onChange(key, r.startISO, r.endISO);
    }

    host.querySelectorAll(".df-btn").forEach(b => {
      b.addEventListener("click", () => setActive(b.dataset.key));
    });
    setActive(initialKey);
  }

  root.DateFilter = { mount, rangeFor, inRange, PRESETS };
})(window);
