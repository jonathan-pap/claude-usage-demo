/* Subscription plan selector — what the user is actually billed for.
 *
 * State (localStorage):
 *   ccusage.plan = key ("api" | "pro" | "pro_annual" | "max5" | "max20" | "team" | "enterprise")
 *
 * API:
 *   Plan.current()  — { key, name, monthly, kind }
 *   Plan.set(key)
 *   Plan.list()     — array of all options
 *   Plan.mountSelector(hostId) — dropdown for the settings modal
 *
 * Pages should listen for 'planchange' on document and re-render.
 */
(function (root) {
  const KEY = "ccusage.plan";
  const PLANS = [
    { key: "api",        name: "API (pay-as-you-go)",  monthly: null, kind: "api"     },
    { key: "pro",        name: "Pro ($20/mo)",         monthly: 20,   kind: "subscription" },
    { key: "pro_annual", name: "Pro Annual ($16.67/mo)", monthly: 16.67, kind: "subscription" },
    { key: "max5",       name: "Max 5× ($100/mo)",     monthly: 100,  kind: "subscription" },
    { key: "max20",      name: "Max 20× ($200/mo)",    monthly: 200,  kind: "subscription" },
    { key: "team",       name: "Team ($30/seat × 5 min)", monthly: 150, kind: "subscription" },
    { key: "enterprise", name: "Enterprise (custom)",  monthly: null, kind: "negotiated" },
  ];
  const DEFAULT_KEY = "max5";

  function current() {
    const k = localStorage.getItem(KEY) || DEFAULT_KEY;
    return PLANS.find(p => p.key === k) || PLANS.find(p => p.key === DEFAULT_KEY);
  }
  function set(k) {
    if (!PLANS.some(p => p.key === k)) return;
    localStorage.setItem(KEY, k);
    document.dispatchEvent(new CustomEvent("planchange", { detail: { plan: current() } }));
  }
  function list() { return PLANS.slice(); }

  function mountSelector(hostId) {
    const host = document.getElementById(hostId);
    if (!host) return;
    function render() {
      const cur = current();
      const opts = PLANS.map(p =>
        `<option value="${p.key}"${p.key === cur.key ? " selected" : ""}>${p.name}</option>`
      ).join("");
      host.innerHTML = `
        <select class="currency-rate-input" style="width:auto; min-width:200px;" aria-label="Subscription plan">
          ${opts}
        </select>
      `;
      host.querySelector("select").addEventListener("change", e => set(e.target.value));
    }
    render();
    document.addEventListener("planchange", render);
  }

  root.Plan = { current, set, list, mountSelector };
})(window);
