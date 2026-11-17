// API base URL comes from config.js: "" locally (nginx proxies /api), the
// Container App URL in the cloud. Nothing secret lives in the frontend.
const API = ((window.APP_CONFIG && window.APP_CONFIG.API_URL) || "").replace(/\/$/, "");

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`${options.method || "GET"} ${path} → ${res.status}`);
  return res.status === 204 ? null : res.json();
}

function showError(err) {
  $("error").textContent = err ? String(err.message || err) : "";
  $("error").hidden = !err;
}

function render(notes) {
  const list = $("notes");
  list.replaceChildren();
  if (notes.length === 0) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No notes yet.";
    list.append(li);
    return;
  }
  for (const note of notes) {
    const li = document.createElement("li");
    const text = document.createElement("span");
    text.textContent = note.text; // textContent: user input is never parsed as HTML
    const date = document.createElement("time");
    date.className = "muted";
    date.textContent = new Date(note.created_at).toLocaleString();
    const del = document.createElement("button");
    del.className = "link";
    del.textContent = "Delete";
    del.onclick = async () => {
      try { await api(`/api/notes/${note.id}`, { method: "DELETE" }); await load(); }
      catch (e) { showError(e); }
    };
    li.append(text, date, del);
    list.append(li);
  }
}

async function load() {
  render(await api("/api/notes"));
  showError(null);
}

$("note-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("note-text");
  try {
    await api("/api/notes", { method: "POST", body: JSON.stringify({ text: input.value }) });
    input.value = "";
    await load();
  } catch (err) { showError(err); }
});

(async () => {
  try {
    const m = await api("/api/message");
    $("message").textContent = m.message;
    $("version").textContent = m.version;
    await load();
  } catch (err) {
    $("message").textContent = "Could not reach the API (first call can be slow: scale from zero).";
    showError(err);
  }
})();
