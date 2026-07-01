// background.js — service worker: context menu integration

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "jarvis-ask", title: "Ask JARVIS about this", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "jarvis-summarize", title: "JARVIS summarize this", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "jarvis-factcheck", title: "JARVIS fact-check this", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "jarvis-explain", title: "JARVIS explain this", contexts: ["selection"] });
});

const JARVIS_BASE = "http://localhost:8000";

async function getToken() {
  const result = await chrome.storage.local.get(["jarvis_token"]);
  return result.jarvis_token || "";
}

async function askJarvis(prompt) {
  const token = await getToken();
  const res = await fetch(`${JARVIS_BASE}/stark/chat`, {
    method: "POST",
    headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ message: prompt }),
  });
  const data = await res.json();
  return data.response || "(no response)";
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const text = info.selectionText || "";
  let prompt = "";

  if (info.menuItemId === "jarvis-ask") prompt = `Tell me about: ${text}`;
  else if (info.menuItemId === "jarvis-summarize") prompt = `Summarize this: ${text}`;
  else if (info.menuItemId === "jarvis-factcheck") prompt = `Fact-check this claim: ${text}`;
  else if (info.menuItemId === "jarvis-explain") prompt = `Explain this: ${text}`;
  else return;

  const response = await askJarvis(prompt);

  chrome.notifications.create({
    type: "basic",
    iconUrl: "icon.png",
    title: "JARVIS",
    message: response.slice(0, 200),
  });
});
