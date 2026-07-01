// content.js — runs on every page. Extracts page text and highlights trackers.

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "get_page_text") {
    sendResponse({ text: document.body.innerText, url: location.href, title: document.title });
    return true;
  }
  if (request.action === "get_selection") {
    sendResponse({ text: window.getSelection().toString() });
    return true;
  }
});

// Basic tracker highlight (privacy shield) — flags common third-party tracking domains
const TRACKER_DOMAINS = [
  "doubleclick.net", "google-analytics.com", "facebook.net", "scorecardresearch.com",
  "adsystem.com", "hotjar.com", "segment.com", "mixpanel.com",
];

function scanForTrackers() {
  const scripts = Array.from(document.querySelectorAll("script[src]"));
  const found = scripts
    .map(s => s.src)
    .filter(src => TRACKER_DOMAINS.some(domain => src.includes(domain)));
  if (found.length) {
    console.log(`[JARVIS Privacy Shield] ${found.length} known trackers detected on this page.`);
  }
  return found;
}

scanForTrackers();
