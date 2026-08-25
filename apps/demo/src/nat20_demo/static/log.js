function currentScenario() {
  return document.querySelector("main.board")?.dataset.scenario ?? null;
}

// Persist the canonical fight log the server returns after every action,
// and mirror it into the URL fragment as a lightweight, non-networked
// "permalink" of the current turn.
function persistLog() {
  const el = document.getElementById("fight-log");
  const seed = document.getElementById("fight-seed");
  if (!el || !el.value) return;
  const scenario = currentScenario();
  if (!scenario) return;
  localStorage.setItem("nat20:" + scenario, el.value);
  const h = "#s=" + scenario + "&seed=" + seed.value + "&log=" + el.value;
  history.replaceState(null, "", h);
}

// On first load of a play page with no explicit ?log= in the URL, restore
// whichever fight state is available. A shared permalink's #fragment takes
// priority (it's what the visitor actually navigated to); failing that,
// fall back to this browser's own last-played state for the scenario
// (localStorage). "Restore" means re-navigating to the query-string form
// so the server renders that exact state -- the fragment/localStorage are
// client-only and the server never sees them otherwise. Returns true if a
// redirect was kicked off (the caller should skip persisting this load's
// state, since it's about to be replaced).
function restoreFromPermalink() {
  const scenario = currentScenario();
  if (!scenario) return false;
  if (new URLSearchParams(window.location.search).has("log")) return false;

  let seed = null;
  let log = null;
  const hash = window.location.hash.replace(/^#/, "");
  if (hash) {
    const fragParams = new URLSearchParams(hash);
    if (fragParams.get("s") === scenario && fragParams.get("log")) {
      seed = fragParams.get("seed");
      log = fragParams.get("log");
    }
  }
  if (!log) {
    const stored = localStorage.getItem("nat20:" + scenario);
    if (stored) {
      log = stored;
      seed = document.getElementById("fight-seed")?.value ?? null;
    }
  }
  if (!log) return false;

  const u = new URL(window.location);
  u.searchParams.set("log", log);
  if (seed) u.searchParams.set("seed", seed);
  u.hash = "";
  window.location.replace(u.toString());
  return true;
}

document.addEventListener("DOMContentLoaded", () => {
  if (restoreFromPermalink()) return; // navigating away -- skip this load's persist
  persistLog();
});
document.addEventListener("htmx:afterSwap", persistLog);
document.addEventListener("click", (e) => {
  if (e.target.id !== "copy-permalink") return;
  const u = new URL(window.location);
  u.searchParams.set("log", document.getElementById("fight-log").value);
  u.hash = "";
  navigator.clipboard.writeText(u.toString());
});
