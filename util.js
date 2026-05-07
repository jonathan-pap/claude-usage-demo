/* Shared utility helpers — keep tiny and side-effect free.
 * Loaded by every page before page-specific scripts.
 */
(function (root) {
  // HTML-escape a value for safe interpolation into innerHTML / template
  // strings. Project names, tool names, model strings, cwd paths and other
  // free-text fields come from JSONL on disk (which Claude Code writes from
  // user input) — never trust them in HTML.
  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Convenience: escape a value used inside an HTML attribute.
  // Same rules as esc() — kept as a separate name so call sites read clearly.
  const escAttr = esc;

  // Shared palette — used by chart `backgroundColor` arrays across pages so
  // a slice 0 always maps to the same colour. Pages can extend by index;
  // first 8 entries cover the typical category cardinality.
  const PALETTE = ["#d97757", "#60a5fa", "#a78bfa", "#fbbf24", "#f472b6", "#4ade80", "#ef4444", "#8a93a3"];

  // Shared no-cache cost approximation. Cache-read tokens cost ~10% of input
  // price; without caching they would have been input tokens at full price.
  // saved = cacheRead × inputRate × 0.9. Used by both build_insights.py
  // (Python side) and dashboard.html so the two never disagree by formula.
  // Caller passes a per-model record { cacheRead, inputRatePerToken } —
  // input rate must already be USD per token.
  function noCacheSaved(cacheReadTokens, inputRatePerToken) {
    return (cacheReadTokens || 0) * (inputRatePerToken || 0) * 0.9;
  }

  root.U = Object.assign(root.U || {}, { esc, escAttr, PALETTE, noCacheSaved });
})(window);
