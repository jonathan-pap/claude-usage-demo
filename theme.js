/* Three-mode theme cycler: dark -> blupulse -> light -> dark.
 * Reads/writes localStorage key "ccusage.theme".
 * Apply the persisted theme as early as possible (before paint) by including
 * this script in <head>; the IIFE at the bottom runs immediately.
 *
 * Mount a small toggle button into a host element:
 *   <span id="themeToggle"></span>
 *   <script>ThemeToggle.mount("themeToggle")</script>
 */
(function (root) {
  const STORAGE_KEY = "ccusage.theme";
  const ORDER = ["dark", "blupulse", "light"];
  const LABELS = { dark: "Dark", blupulse: "BluPulse", light: "Light" };

  // Inline SVG so the icons inherit currentColor and need no asset pipeline.
  const ICONS = {
    dark: `<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/></svg>`,
    light: `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>`,
    blupulse: `<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="M12 2l2.09 6.26L20 9.27l-4.5 4.39L16.18 20 12 16.77 7.82 20l.68-6.34L4 9.27l5.91-1.01L12 2z"/></svg>`,
  };

  function current() {
    const stored = safeGet(STORAGE_KEY);
    return ORDER.includes(stored) ? stored : "dark";
  }
  // Safe localStorage wrappers — Safari private mode and aggressive privacy
  // settings can throw on read OR write. Failing closed (no persistence)
  // is preferable to crashing the page.
  function safeGet(k) {
    try { return localStorage.getItem(k); } catch (_) { return null; }
  }
  function safeSet(k, v) {
    try { localStorage.setItem(k, v); } catch (_) { /* ignore */ }
  }

  // Internal: apply theme to the DOM without writing to storage. Used on
  // initial page load so a non-interactive view doesn't pollute storage.
  function paint(name) {
    document.documentElement.setAttribute("data-theme", name);
    document.dispatchEvent(new CustomEvent("themechange", { detail: { theme: name } }));
  }
  // Public: user-initiated apply — paints AND persists.
  function apply(name) {
    paint(name);
    safeSet(STORAGE_KEY, name);
  }
  function next() {
    const i = ORDER.indexOf(current());
    return ORDER[(i + 1) % ORDER.length];
  }
  function cycle() { apply(next()); }

  // Apply persisted theme immediately so there's no flash of wrong theme.
  // Use paint() (no storage write) — only user actions should write.
  paint(current());

  // Single cycling icon button — used in nav of every page.
  function mount(hostId) {
    const host = document.getElementById(hostId);
    if (!host) return;
    function render() {
      const c = current();
      host.innerHTML = `<button class="theme-toggle" type="button" title="Theme: ${LABELS[c]} (click to cycle)" aria-label="Switch theme, currently ${LABELS[c]}" style="display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px; padding:0;">${ICONS[c]}</button>`;
      host.querySelector("button").addEventListener("click", cycle);
    }
    render();
    document.addEventListener("themechange", render);
  }

  // Three-icon picker row — used inside the Settings modal on the story page.
  function mountPicker(hostId) {
    const host = document.getElementById(hostId);
    if (!host) return;
    function render() {
      const c = current();
      host.innerHTML = `
        <div class="theme-picker" role="group" aria-label="Theme">
          ${ORDER.map(name => `
            <button class="theme-pill ${name === c ? 'active' : ''}" data-theme="${name}"
                    type="button" aria-label="${LABELS[name]} theme" title="${LABELS[name]}">
              ${ICONS[name]}
            </button>
          `).join("")}
        </div>
      `;
      host.querySelectorAll(".theme-pill").forEach(btn => {
        btn.addEventListener("click", () => apply(btn.dataset.theme));
      });
    }
    render();
    document.addEventListener("themechange", render);
  }

  root.ThemeToggle = { mount, mountPicker, cycle, current, apply, ORDER, ICONS };
})(window);
