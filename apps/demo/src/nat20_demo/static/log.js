// Persist the canonical fight log the server returns after every action.
function persistLog() {
  const el = document.getElementById("fight-log");
  const seed = document.getElementById("fight-seed");
  if (!el || !el.value) return;
  const scenario = document.querySelector("main.board")?.dataset.scenario;
  if (!scenario) return;
  localStorage.setItem("nat20:" + scenario, el.value);
  const h = "#s=" + scenario + "&seed=" + seed.value + "&log=" + el.value;
  history.replaceState(null, "", h);
}
document.addEventListener("htmx:afterSwap", persistLog);
document.addEventListener("DOMContentLoaded", persistLog);
document.addEventListener("click", (e) => {
  if (e.target.id !== "copy-permalink") return;
  const u = new URL(window.location);
  u.searchParams.set("log", document.getElementById("fight-log").value);
  u.hash = "";
  navigator.clipboard.writeText(u.toString());
});
