const $ = (id) => document.getElementById(id);
const usd = (s) => { const n = Number(s); return n === 0 ? "$0" : n < 0.01 ? "$" + n.toFixed(6) : "$" + n.toFixed(2); };
const pct = (v) => (v == null ? "–" : (v * 100).toFixed(1) + "%");
const ms = (v) => (v == null ? "–" : v + " ms");

// textContent only: API data is never parsed as HTML
function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function status(msg, isError) {
  $("status").textContent = msg;
  $("status").className = isError ? "error" : "";
}

function card(label, value, note) {
  const c = el("div", null, "card");
  c.append(el("div", label, "label"), el("div", value, "value"), el("div", note, "note"));
  return c;
}

function renderCards(t) {
  $("cards").replaceChildren(
    card("Requests", t.requests.toLocaleString(), "in this window"),
    card("Cost", usd(t.cost_usd), `${(t.prompt_tokens + t.completion_tokens).toLocaleString()} billable tokens`),
    card("Saved by cache", usd(t.saved_usd), "at list price"),
    card("Cache hit rate", pct(t.cache_hit_rate), `${t.cache_hits} hits, median ${ms(t.cached_latency_ms.p50)}`),
    card("p95 latency", ms(t.latency_ms.p95), `median ${ms(t.latency_ms.p50)}, provider calls only`),
    card("Error rate", pct(t.error_rate), `${t.errors} of ${t.requests} requests`),
  );
  $("cards").hidden = false;
}

function renderTable(groups, groupBy) {
  const head = el("tr");
  [groupBy, "Requests", "Cost", "Saved", "Hit rate", "p95", "Errors"].forEach((c) => head.append(el("th", c)));
  const maxCost = Math.max(...groups.map((g) => Number(g.cost_usd)), 0);
  const rows = groups.map((g) => {
    const cost = el("td", usd(g.cost_usd));
    const bar = el("span", null, "bar");
    bar.style.width = (maxCost ? (Number(g.cost_usd) / maxCost) * 100 : 0) + "%"; // CSSOM writes are allowed by our CSP
    cost.append(bar);
    const tr = el("tr");
    tr.append(el("td", g.label), el("td", g.requests.toLocaleString()), cost, el("td", usd(g.saved_usd)),
      el("td", pct(g.cache_hit_rate)), el("td", ms(g.latency_ms.p95)), el("td", g.errors));
    return tr;
  });
  const thead = el("thead"); thead.append(head);
  const tbody = el("tbody"); tbody.append(...rows);
  $("table").replaceChildren(thead, tbody);
  $("tablewrap").hidden = false;
}

async function load(event) {
  event.preventDefault();
  const days = $("days").value, group = $("group").value;
  status("Loading…");
  let res;
  try {
    res = await fetch(`/admin/v1/usage?days=${days}&group_by=${group}`, {
      headers: { Authorization: "Bearer " + $("key").value.trim() },
    });
  } catch {
    return status("Could not reach the gateway.", true);
  }
  if (res.status === 401) return status("Invalid admin key.", true);
  if (!res.ok) return status(`Request failed (HTTP ${res.status}).`, true);
  const data = await res.json();
  renderCards(data.totals);
  if (data.groups.length) renderTable(data.groups, group); else $("tablewrap").hidden = true;
  status(data.totals.requests ? `Last ${days} day(s), updated ${new Date().toLocaleTimeString()}` : "No requests in this window.");
}

$("controls").addEventListener("submit", load);
