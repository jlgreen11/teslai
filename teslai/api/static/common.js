const $ = (id) => document.getElementById(id);

async function authFetch(url) {
  try {
    const r = await fetch(url);
    if (r.status === 401) { location.href = "/login"; return null; }
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    return r;
  } catch (e) {
    const msg = $("msg") || $("list");
    if (msg) msg.innerHTML = `<p class="error">Could not load: ${e.message}</p>`;
    return null;
  }
}

async function initVehiclePage(load) {
  const r = await authFetch("/api/v1/vehicles");
  if (!r) return;
  const vs = await r.json();
  if (!vs.length) {
    const msg = $("msg") || $("list");
    msg.innerHTML = '<p class="empty">No vehicles yet. Import history with <code>teslai import teslafi --write</code>.</p>';
    return;
  }
  $("vehicle").innerHTML = vs.map((v) => `<option value="${v.id}">${v.display_name || "Car"} ···${v.vin_last4}</option>`).join("");
  $("vehicle").onchange = load;
  load();
}
