/* Shared Settings modal — gear button + slide-in panel.
 * Every page mounts the same one so the user has a single, consistent
 * place to change theme / plan / timezone / currency. State lives in
 * localStorage (theme.js, plan.js, tzmode.js, currency.js) so changes
 * propagate automatically; this is just the UI shell.
 *
 * Usage:
 *   <span id="settingsHost"></span>
 *   <script>Settings.mount("settingsHost")</script>
 */
(function (root) {
  const GEAR_SVG = `
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>`;

  let modalEl = null;

  function ensureModal() {
    if (modalEl) return modalEl;
    modalEl = document.createElement("div");
    modalEl.className = "settings-overlay";
    modalEl.setAttribute("role", "dialog");
    modalEl.setAttribute("aria-modal", "true");
    modalEl.setAttribute("aria-labelledby", "settingsModalTitle");
    modalEl.innerHTML = `
      <div class="settings-panel" role="document">
        <header>
          <h3 id="settingsModalTitle">Settings</h3>
          <button class="close" data-role="close" aria-label="Close settings">×</button>
        </header>
        <div class="settings-row">
          <div class="label">Theme</div>
          <div data-role="theme"></div>
        </div>
        <div class="settings-row">
          <div class="label">Subscription plan</div>
          <div class="row-controls" data-role="plan"></div>
        </div>
        <div class="settings-row">
          <div class="label">Display timezone</div>
          <div class="row-controls" data-role="tz"></div>
        </div>
        <div class="settings-row">
          <div class="label">Currency</div>
          <div class="row-controls" data-role="currency"></div>
        </div>
      </div>
    `;
    document.body.appendChild(modalEl);

    // Mount each control into the modal slots — gracefully skip if a module
    // wasn't loaded on this page.
    const slot = (role) => modalEl.querySelector(`[data-role="${role}"]`);
    if (root.ThemeToggle) {
      const el = slot("theme"); el.id = el.id || ("settings-theme-" + Math.random().toString(36).slice(2, 7));
      ThemeToggle.mountPicker(el.id);
    }
    if (root.Plan) {
      const el = slot("plan"); el.id = el.id || ("settings-plan-" + Math.random().toString(36).slice(2, 7));
      Plan.mountSelector(el.id);
    }
    if (root.Tz) {
      const el = slot("tz"); el.id = el.id || ("settings-tz-" + Math.random().toString(36).slice(2, 7));
      Tz.mountSelector(el.id);
    }
    if (root.Currency) {
      const el = slot("currency"); el.id = el.id || ("settings-currency-" + Math.random().toString(36).slice(2, 7));
      Currency.mountRateInput(el.id);
    }

    modalEl.querySelector('[data-role="close"]').addEventListener("click", close);
    modalEl.addEventListener("click", e => { if (e.target === modalEl) close(); });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && modalEl.classList.contains("open")) close();
    });
    return modalEl;
  }

  function open()  { ensureModal().classList.add("open"); }
  function close() { if (modalEl) modalEl.classList.remove("open"); }

  function mount(hostId) {
    const host = document.getElementById(hostId);
    if (!host) return;
    host.innerHTML = `
      <button class="settings-btn" type="button" title="Settings" aria-label="Open settings">${GEAR_SVG}</button>
    `;
    host.querySelector("button").addEventListener("click", open);
  }

  // Convenience: subscribe to ALL settings changes with one call. Useful for
  // pages that just need to re-render on any of theme/currency/tz/plan
  // change. Returns an unsubscribe function.
  function onChange(cb) {
    if (typeof cb !== "function") return () => {};
    const events = ["themechange", "currencychange", "tzchange", "planchange"];
    const wrap = (e) => cb(e);
    events.forEach(name => document.addEventListener(name, wrap));
    return () => events.forEach(name => document.removeEventListener(name, wrap));
  }

  root.Settings = { mount, open, close, onChange };
})(window);
