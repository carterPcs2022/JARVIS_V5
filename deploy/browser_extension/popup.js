const JARVIS_BASE = "http://localhost:8000";

function getToken() {
  return new Promise(resolve => {
    chrome.storage.local.get(["jarvis_token"], (result) => {
      if (result.jarvis_token) {
        resolve(result.jarvis_token);
      } else {
        const t = prompt("Enter your JARVIS API token:");
        if (t) chrome.storage.local.set({ jarvis_token: t });
        resolve(t || "");
      }
    });
  });
}

async function jarvisPost(path, body) {
  const token = await getToken();
  const res = await fetch(`${JARVIS_BASE}${path}`, {
    method: "POST",
    headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

function appendMsg(role, text) {
  const log = document.getElementById("chat-log");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

async function checkStatus() {
  try {
    const token = await getToken();
    const res = await fetch(`${JARVIS_BASE}/health`);
    document.getElementById("status").textContent = res.ok ? "ONLINE" : "OFFLINE";
  } catch (e) {
    document.getElementById("status").textContent = "UNREACHABLE";
  }
}

document.getElementById("send-btn").addEventListener("click", async () => {
  const input = document.getElementById("msg-input");
  const text = input.value.trim();
  if (!text) return;
  appendMsg("user", text);
  input.value = "";
  const result = await jarvisPost("/stark/chat", { message: text });
  appendMsg("ai", result.response || "(no response)");
});

document.getElementById("summarize-btn").addEventListener("click", () => {
  chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
    chrome.tabs.sendMessage(tabs[0].id, { action: "get_page_text" }, async (response) => {
      const text = (response && response.text) || "";
      appendMsg("user", "Summarize this page");
      const result = await jarvisPost("/stark/content/summarize", { content: text.slice(0, 4000), style: "bullets" });
      appendMsg("ai", result.summary || result.response || "(no summary)");
    });
  });
});

document.getElementById("analyze-btn").addEventListener("click", () => {
  chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
    const url = tabs[0].url;
    appendMsg("user", `Analyze: ${url}`);
    const result = await jarvisPost("/stark/chat", { message: `Analyze this page: ${url}` });
    appendMsg("ai", result.response || "(no response)");
  });
});

document.getElementById("msg-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("send-btn").click();
});

checkStatus();
