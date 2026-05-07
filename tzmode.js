/* Display-time timezone conversion.
 *
 * Core principle: data on disk and in JSON files is ALWAYS UTC. Conversion
 * happens only at render time so multi-machine merges (which key by UTC hour
 * buckets) stay consistent regardless of who is viewing the page.
 *
 * State (localStorage):
 *   ccusage.tz = "UTC" | "browser" | <IANA zone name>
 *
 * API:
 *   Tz.zone()                 — resolved zone name (browser-default expanded)
 *   Tz.mode()                 — raw mode ("UTC" | "browser" | "<iana>")
 *   Tz.set(value)             — set mode and broadcast tzchange
 *   Tz.label()                — short label for the badge ("UTC", "Madrid time", …)
 *
 *   Tz.formatHour(utcHourStr) — "2026-04-25T08" -> "2026-04-25 09:00" in zone
 *   Tz.formatStamp(isoStr)    — "2026-04-25T08:14:33Z" -> "2026-04-25 09:14:33"
 *   Tz.formatDate(isoStr)     — "2026-04-25T08:14:33Z" -> "2026-04-25" in zone
 *
 *   Tz.mountSelector(hostId)  — full picker (UTC / Browser / curated list)
 *   Tz.mountBadge(hostId)     — small clickable badge that opens picker
 *
 * Pages should listen for the "tzchange" event on document and re-render
 * any timestamp-bearing widgets.
 */
(function (root) {
  const STORAGE_KEY = "ccusage.tz";
  // Curated list of common IANA zones. The browser's Intl handles DST for any
  // valid IANA name — these are just convenient picks.
  const PRESETS = [
    { value: "UTC",     label: "UTC" },
    { value: "browser", label: "Browser local (auto)" },
    { value: "Europe/London",      label: "London"        },
    { value: "Europe/Madrid",      label: "Madrid"        },
    { value: "Europe/Berlin",      label: "Berlin"        },
    { value: "Europe/Paris",       label: "Paris"         },
    { value: "America/New_York",   label: "New York"      },
    { value: "America/Chicago",    label: "Chicago"       },
    { value: "America/Denver",     label: "Denver"        },
    { value: "America/Los_Angeles",label: "Los Angeles"   },
    { value: "Asia/Kolkata",       label: "India (Kolkata)" },
    { value: "Asia/Singapore",     label: "Singapore"     },
    { value: "Asia/Tokyo",         label: "Tokyo"         },
    { value: "Australia/Sydney",   label: "Sydney"        },
  ];

  function browserZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; }
    catch (_) { return "UTC"; }
  }
  function mode() {
    return localStorage.getItem(STORAGE_KEY) || "UTC";
  }
  function zone() {
    const m = mode();
    return m === "browser" ? browserZone() : m;
  }
  function set(value) {
    if (!value) return;
    localStorage.setItem(STORAGE_KEY, value);
    document.dispatchEvent(new CustomEvent("tzchange", { detail: { mode: value, zone: zone() } }));
  }
  function label() {
    const m = mode();
    if (m === "UTC") return "UTC";
    if (m === "browser") {
      // Show the resolved zone abbreviated to the city portion.
      const z = browserZone();
      return (z.split("/").pop() || z).replace(/_/g, " ");
    }
    return (m.split("/").pop() || m).replace(/_/g, " ");
  }

  // --- Formatters ----------------------------------------------------------
  // "2026-04-25T08" — bare hour bucket — into a real Date by treating the
  // bucket as the start of that UTC hour (T08:00:00Z).
  function parseHourBucket(s) {
    if (!s) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2})$/.exec(s);
    if (!m) return new Date(s);  // fall back to native parse
    return new Date(Date.UTC(+m[1], +m[2]-1, +m[3], +m[4], 0, 0));
  }
  function pad2(n) { return String(n).padStart(2, "0"); }

  // Use Intl.DateTimeFormat to get individual parts for a given timeZone, then
  // assemble into the "YYYY-MM-DD HH:MM" / "YYYY-MM-DD HH:MM:SS" forms we use.
  function partsIn(date, tz) {
    const fmt = new Intl.DateTimeFormat("en-CA", {
      timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
    const out = {};
    for (const p of fmt.formatToParts(date)) {
      if (p.type !== "literal") out[p.type] = p.value;
    }
    // Hour comes back as "24" in some locales for midnight — normalize.
    if (out.hour === "24") out.hour = "00";
    return out;
  }

  function formatHour(utcHourStr) {
    const d = parseHourBucket(utcHourStr);
    if (!d || isNaN(d)) return utcHourStr;
    const p = partsIn(d, zone());
    return `${p.year}-${p.month}-${p.day} ${p.hour}:00`;
  }
  function formatStamp(isoStr) {
    const d = isoStr ? new Date(isoStr) : null;
    if (!d || isNaN(d)) return isoStr || "";
    const p = partsIn(d, zone());
    return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
  }
  function formatDate(isoStr) {
    const d = isoStr ? new Date(isoStr) : null;
    if (!d || isNaN(d)) return isoStr || "";
    const p = partsIn(d, zone());
    return `${p.year}-${p.month}-${p.day}`;
  }

  // Convert a bare UTC hour-of-day (0-23) to a local-zone "HH:00" string.
  // Uses today's date as the DST reference, so a single integer can carry
  // tz info (with the caveat that a single number cannot fully represent
  // a year of data spanning DST transitions — close enough for the story).
  function formatHourOfDay(hourUTC) {
    const hr = parseInt(hourUTC, 10);
    if (!Number.isFinite(hr) || hr < 0 || hr > 23) return String(hourUTC);
    const today = new Date();
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate(), hr, 0, 0));
    const p = partsIn(d, zone());
    return `${p.hour}:00`;
  }

  // --- UI mounts -----------------------------------------------------------
  function mountSelector(hostId) {
    const host = document.getElementById(hostId);
    if (!host) return;
    function render() {
      const cur = mode();
      const opts = PRESETS.map(p =>
        `<option value="${p.value}"${p.value === cur ? " selected" : ""}>${p.label}${p.value === "browser" ? ` — ${browserZone()}` : ""}</option>`
      ).join("");
      host.innerHTML = `
        <span style="display:inline-flex; align-items:center; gap:8px; flex-wrap:wrap;">
          <span style="color:var(--muted); font-size:12px;">Show times in</span>
          <select class="currency-rate-input" style="width:auto; min-width:160px;" aria-label="Display timezone">
            ${opts}
          </select>
        </span>
      `;
      host.querySelector("select").addEventListener("change", e => set(e.target.value));
    }
    render();
    document.addEventListener("tzchange", render);
  }

  function mountBadge(hostId) {
    const host = document.getElementById(hostId);
    if (!host) return;
    function render() {
      host.innerHTML = `<button class="theme-toggle" type="button" title="Display timezone (${zone()})">${label()}</button>`;
      host.querySelector("button").addEventListener("click", () => {
        // Quick cycle: UTC -> browser -> UTC. Story page has the full picker.
        set(mode() === "UTC" ? "browser" : "UTC");
      });
    }
    render();
    document.addEventListener("tzchange", render);
  }

  root.Tz = { mode, zone, label, set, formatHour, formatStamp, formatDate, formatHourOfDay, mountSelector, mountBadge, PRESETS };
})(window);
