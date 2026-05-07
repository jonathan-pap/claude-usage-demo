/* Shared USD/EUR display module.
 *
 * State (localStorage):
 *   ccusage.currency.code = "USD" | "EUR"
 *   ccusage.currency.rate = USD->EUR multiplier (default 0.92)
 *
 * API:
 *   Currency.format(usd, opts?) — returns "$305.94" or "€281.47"
 *     opts: { decimals = 2, sign = false }
 *   Currency.symbol() — "$" or "€"
 *   Currency.code()   — "USD" or "EUR"
 *   Currency.rate()   — current USD->EUR multiplier
 *   Currency.set(code) / Currency.setRate(rate)
 *   Currency.mountToggle(hostId)   — small "USD/EUR" toggle button
 *   Currency.mountRateInput(hostId) — full rate editor (for the story page)
 *
 * Pages should listen for the "currencychange" event on document and
 * re-render any cost-bearing widgets.
 */
(function (root) {
  const KEY_CODE = "ccusage.currency.code";
  const KEY_RATE = "ccusage.currency.rate";
  const SYMBOLS = { USD: "$", EUR: "€" };
  const DEFAULT_RATE = 0.92;

  function code() {
    const v = (localStorage.getItem(KEY_CODE) || "USD").toUpperCase();
    return SYMBOLS[v] ? v : "USD";
  }
  function rate() {
    const v = parseFloat(localStorage.getItem(KEY_RATE));
    return Number.isFinite(v) && v > 0 ? v : DEFAULT_RATE;
  }
  function symbol() { return SYMBOLS[code()]; }

  function set(newCode) {
    const c = (newCode || "USD").toUpperCase();
    if (!SYMBOLS[c]) return;
    localStorage.setItem(KEY_CODE, c);
    document.dispatchEvent(new CustomEvent("currencychange", { detail: { code: c, rate: rate() } }));
  }
  function setRate(newRate) {
    const r = parseFloat(newRate);
    if (!Number.isFinite(r) || r <= 0) return;
    localStorage.setItem(KEY_RATE, String(r));
    document.dispatchEvent(new CustomEvent("currencychange", { detail: { code: code(), rate: r } }));
  }

  function format(usd, opts = {}) {
    const decimals = opts.decimals ?? 2;
    const sign     = opts.sign ?? false;
    const v = (usd || 0) * (code() === "EUR" ? rate() : 1);
    const sgn = sign && v > 0 ? "+" : "";
    const fixed = v.toFixed(decimals);
    const [intPart, decPart] = fixed.split(".");
    const intFmt = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return sgn + symbol() + (decPart !== undefined ? intFmt + "." + decPart : intFmt);
  }

  function mountToggle(hostId) {
    const host = document.getElementById(hostId);
    if (!host) return;
    function render() {
      host.innerHTML = `<button class="currency-toggle" type="button" title="Switch currency (rate: 1 USD = ${rate()} EUR)">${code()}</button>`;
      host.querySelector("button").addEventListener("click", () => {
        set(code() === "USD" ? "EUR" : "USD");
      });
    }
    render();
    document.addEventListener("currencychange", render);
  }

  function mountRateInput(hostId) {
    const host = document.getElementById(hostId);
    if (!host) return;
    function render() {
      host.innerHTML = `
        <div class="currency-rate" style="display:inline-flex; align-items:center; gap:8px; flex-wrap:wrap;">
          <span style="color:var(--muted); font-size:12px;">1 USD =</span>
          <input class="currency-rate-input" type="number" step="0.0001" min="0.0001"
                 value="${rate()}" aria-label="USD to EUR rate" />
          <span style="color:var(--muted); font-size:12px;">EUR</span>
          <button class="currency-toggle" type="button" data-role="toggle">Show ${code() === "USD" ? "EUR" : "USD"}</button>
        </div>
      `;
      host.querySelector(".currency-rate-input").addEventListener("change", e => {
        setRate(e.target.value);
      });
      host.querySelector('[data-role="toggle"]').addEventListener("click", () => {
        set(code() === "USD" ? "EUR" : "USD");
      });
    }
    render();
    document.addEventListener("currencychange", render);
  }

  root.Currency = { format, symbol, code, rate, set, setRate, mountToggle, mountRateInput };
})(window);
