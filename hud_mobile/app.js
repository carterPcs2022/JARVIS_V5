(() => {
  'use strict';

  const HOST   = location.hostname;
  const API    = `http://${HOST}:8000`;
  const WS_URL = `ws://${HOST}:8000/ws/chat`;
  const TOKEN  = localStorage.getItem('jarvis_token') || '';

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const chatLog    = document.getElementById('chat-log');
  const input      = document.getElementById('msg-input');
  const sendBtn    = document.getElementById('send-btn');
  const voiceBtn   = document.getElementById('voice-btn-inline');
  const statusDot  = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');
  const eventItems = document.getElementById('event-items');
  const protoPanel = document.getElementById('proto-panel');
  const protoList  = document.getElementById('proto-list');

  const valModel    = document.getElementById('val-model');
  const valProvider = document.getElementById('val-provider');
  const valLatency  = document.getElementById('val-latency');
  const valMode     = document.getElementById('val-mode');
  const valUptime   = document.getElementById('val-uptime');

  const arcCpu  = document.getElementById('arc-cpu');
  const arcRam  = document.getElementById('arc-ram');
  const arcDisk = document.getElementById('arc-disk');
  const valCpu  = document.getElementById('val-cpu');
  const valRam  = document.getElementById('val-ram');
  const valDisk = document.getElementById('val-disk');

  // ── State ──────────────────────────────────────────────────────────────────
  let ws, reconnectTimer, streamBubble = null;
  let mediaRec = null, audioChunks = [], voiceWs = null;

  // ── Helpers ────────────────────────────────────────────────────────────────
  function setStatus(s) {
    statusDot.className = `status-dot ${s}`;
    statusText.textContent = {online:'SYSTEMS ONLINE', offline:'OFFLINE', degraded:'DEGRADED'}[s] || s.toUpperCase();
  }

  function addEvent(cls, text) {
    const el = document.createElement('div');
    el.className = `event-item ${cls}`;
    const ts = new Date().toLocaleTimeString('en', {hour12: false});
    el.textContent = `[${ts}] ${text}`;
    eventItems.prepend(el);
    while (eventItems.children.length > 50) eventItems.lastChild.remove();
  }

  function setArc(fill, label, pct) {
    const deg = -180 + (pct / 100) * 180;
    fill.style.transform = `rotate(${deg}deg)`;
    label.textContent = `${Math.round(pct)}%`;
    fill.className = 'arc-fill' + (pct >= 90 ? ' danger' : pct >= 75 ? ' warn' : '');
  }

  // ── Bubbles ────────────────────────────────────────────────────────────────
  function addBubble(cls, text) {
    const el = document.createElement('div');
    el.className = `bubble ${cls}`;
    if (cls === 'assistant') {
      const span = document.createElement('span');
      span.className = 'prefix'; span.textContent = 'JARVIS ›';
      el.appendChild(span);
      const body = document.createElement('span');
      body.className = 'body'; body.textContent = ' ' + (text || '');
      el.appendChild(body);
    } else {
      el.textContent = text || '';
    }
    chatLog.appendChild(el);
    chatLog.scrollTop = chatLog.scrollHeight;
    return el;
  }

  function startStream() {
    streamBubble = addBubble('assistant', '');
    const cur = document.createElement('span');
    cur.className = 'cursor'; cur.id = 'sc';
    streamBubble.appendChild(cur);
  }

  function appendToken(t) {
    if (!streamBubble) startStream();
    streamBubble.querySelector('.body').textContent += t;
    const cur = streamBubble.querySelector('.cursor');
    if (cur) streamBubble.appendChild(cur);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function endStream(meta) {
    if (streamBubble) {
      const c = streamBubble.querySelector('.cursor');
      if (c) c.remove();
      streamBubble = null;
    }
    if (meta) updatePanels(meta);
    sendBtn.disabled = false;
    input.focus();
    playLatestVoice();
  }

  let lastVoicePlay = 0;
  function playLatestVoice() {
    if (localStorage.getItem('jarvis_voice_muted') === 'true') return;
    const now = Date.now();
    if (now - lastVoicePlay < 1000) return;
    lastVoicePlay = now;
    setTimeout(() => {
      const audio = new Audio(`${API}/stark/voice/audio?t=${Date.now()}`);
      audio.play().catch(() => {});
    }, 400);
  }

  function updatePanels(d) {
    if (d.model)             valModel.textContent    = d.model;
    if (d.provider)          valProvider.textContent = d.provider.toUpperCase();
    if (d.latency_ms != null)valLatency.textContent  = `${d.latency_ms} ms`;
    if (d.meta?.mode)        valMode.textContent     = d.meta.mode.toUpperCase();
  }

  // ── WebSocket ──────────────────────────────────────────────────────────────
  function connect() {
    clearTimeout(reconnectTimer);
    setStatus('offline');
    addEvent('system', 'Connecting…');
    ws = new WebSocket(WS_URL);

    ws.onopen = () => { setStatus('online'); addEvent('ok', 'WebSocket connected'); };

    ws.onmessage = ({data}) => {
      let msg; try { msg = JSON.parse(data); } catch { return; }
      switch (msg.type) {
        case 'system':
          addBubble('system', msg.message || msg.data?.message || '');
          addEvent('system', msg.message || '');
          break;
        case 'stream_start': startStream(); addEvent('system', 'Streaming…'); break;
        case 'token':        appendToken(msg.token); break;
        case 'stream_end':   endStream(msg); addEvent('ok', `Done · ${msg.latency_ms||0} ms`); break;
        case 'response':
          endStream(null);
          addBubble('assistant', msg.response || '');
          updatePanels(msg);
          sendBtn.disabled = false; input.focus();
          addEvent('ok', `Response · ${msg.latency_ms||0} ms`);
          break;
        case 'protocol':
          addBubble('protocol', `🛡 ${msg.data?.protocol}: ${msg.data?.detail || msg.data?.message || ''}`);
          addEvent('protocol', msg.data?.protocol || 'Protocol event');
          break;
        case 'alert':
          addEvent('alert', msg.data?.message || JSON.stringify(msg.data));
          break;
        case 'error':
          endStream(null);
          addBubble('error', msg.message || 'Error');
          addEvent('error', msg.message || 'Error');
          sendBtn.disabled = false;
          break;
      }
    };

    ws.onclose = (e) => {
      setStatus('offline');
      // Close codes actually distinguish the failure mode — 1006 (abnormal)
      // is what a network/proxy block looks like (never even handshakes),
      // vs. a clean 1000/1001 which means the server or client closed it
      // intentionally. Surfacing this beats a generic "error" message when
      // debugging phone-specific connectivity (Private Relay, Low Data Mode,
      // captive portals, etc. all tend to produce 1006 with no reason).
      addEvent('error', `Disconnected (code ${e.code}${e.reason ? ': ' + e.reason : ''}) — retrying in 5s…`);
      reconnectTimer = setTimeout(connect, 5000);
    };

    ws.onerror = (e) => {
      addEvent('error', `WebSocket error — readyState ${ws.readyState}, target ${WS_URL}`);
      console.error('[JARVIS] WebSocket error', { readyState: ws.readyState, url: WS_URL, event: e });
    };
  }

  // ── Send ───────────────────────────────────────────────────────────────────
  function send(text) {
    text = (text || input.value).trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    addBubble('user', text);
    ws.send(JSON.stringify({message: text}));
    input.value = '';
    sendBtn.disabled = true;
    addEvent('system', `→ ${text.slice(0, 80)}`);
  }

  window.quickSend = (t) => send(t);

  sendBtn.addEventListener('click', () => send());
  input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });

  // Prevent double-zoom on iOS by keeping font large enough
  input.style.fontSize = '16px';

  // ── Voice ──────────────────────────────────────────────────────────────────
  function connectVoiceWs() {
    if (voiceWs && voiceWs.readyState === WebSocket.OPEN) return;
    voiceWs = new WebSocket(`ws://${HOST}:8000/stark/voice/ws`);
    voiceWs.onmessage = ({data}) => {
      let msg; try { msg = JSON.parse(data); } catch { return; }
      if (msg.type === 'transcript') { addBubble('transcript', `🎙 "${msg.text}"`); addEvent('system', `Heard: ${msg.text}`); }
      else if (msg.type === 'stream_start') startStream();
      else if (msg.type === 'token') appendToken(msg.token);
      else if (msg.type === 'stream_end') { endStream(msg); if (msg.audio) playB64(msg.audio); }
      else if (msg.type === 'audio') playB64(msg.data);
      else if (msg.type === 'error') { addBubble('error', msg.message); addEvent('error', msg.message); }
    };
    voiceWs.onerror = () => addEvent('error', 'Voice WS error');
  }

  function playB64(b64) {
    try {
      const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
      const blob  = new Blob([bytes], {type: 'audio/mpeg'});
      const url   = URL.createObjectURL(blob);
      const a     = new Audio(url);
      a.play().catch(() => {});
      a.onended = () => URL.revokeObjectURL(url);
    } catch (e) { addEvent('error', `Audio: ${e.message}`); }
  }

  async function toggleVoice() {
    if (mediaRec && mediaRec.state === 'recording') {
      mediaRec.stop();
      voiceBtn.classList.remove('recording');
      voiceBtn.textContent = '🎙';
      addEvent('system', 'Processing voice…');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      audioChunks = [];
      mediaRec = new MediaRecorder(stream);
      mediaRec.ondataavailable = e => audioChunks.push(e.data);
      mediaRec.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(audioChunks, {type: 'audio/webm'});
        const buf  = await blob.arrayBuffer();
        const b64  = btoa(String.fromCharCode(...new Uint8Array(buf)));
        connectVoiceWs();
        const payload = JSON.stringify({type: 'audio', data: b64});
        if (voiceWs.readyState === WebSocket.OPEN) voiceWs.send(payload);
        else voiceWs.onopen = () => voiceWs.send(payload);
      };
      mediaRec.start();
      voiceBtn.classList.add('recording');
      voiceBtn.textContent = '⏹';
      addEvent('system', 'Recording… tap ⏹ to stop');
    } catch (e) {
      addBubble('error', `Mic: ${e.message}`);
      addEvent('error', `Mic: ${e.message}`);
    }
  }

  voiceBtn.addEventListener('click', toggleVoice);
  // Header voice button mirrors inline one
  const hdrVoice = document.getElementById('voice-btn');
  if (hdrVoice) hdrVoice.addEventListener('click', toggleVoice);

  // ── Protocol panel ─────────────────────────────────────────────────────────
  window.toggleProtocols = async () => {
    if (!protoPanel.classList.contains('hidden')) {
      protoPanel.classList.add('hidden'); return;
    }
    protoPanel.classList.remove('hidden');
    protoList.innerHTML = '<div class="proto-item"><span class="proto-name">Loading…</span></div>';
    try {
      const r = await fetch(`${API}/stark/protocols`, {
        headers: TOKEN ? {Authorization: `Bearer ${TOKEN}`} : {}
      });
      const d = await r.json();
      const ap = d.active_protocols || {};
      protoList.innerHTML = '';
      Object.entries(ap).forEach(([k, v]) => {
        const row = document.createElement('div');
        row.className = 'proto-item';
        const cls = v.includes('ACTIVE') || v.includes('LOCKED') ? 'danger'
                  : v.includes('always') || v.includes('ALWAYS') ? 'always'
                  : v === 'standby' || v === 'inactive' ? ''
                  : v.includes('unconfigured') ? 'warn'
                  : 'ok';
        row.innerHTML = `<span class="proto-name">${k.replace('_',' ')}</span><span class="proto-val ${cls}">${v}</span>`;
        protoList.appendChild(row);
      });
    } catch (e) {
      protoList.innerHTML = `<div class="proto-item"><span class="proto-name">Error</span><span class="proto-val danger">${e.message}</span></div>`;
    }
  };

  // ── Live metrics polling ───────────────────────────────────────────────────
  async function pollMetrics() {
    try {
      const r = await fetch(`${API}/stark/telemetry`);
      const d = await r.json();
      if (d.cpu  != null) setArc(arcCpu,  valCpu,  d.cpu);
      if (d.ram  != null) setArc(arcRam,  valRam,  d.ram);
      if (d.disk != null) setArc(arcDisk, valDisk, d.disk);
      if (d.uptime_hours != null) {
        const h = Math.floor(d.uptime_hours);
        const m = Math.round((d.uptime_hours - h) * 60);
        valUptime.textContent = `${h}h ${m}m`;
      }
    } catch { /* server unreachable */ }

    try {
      const r = await fetch(`${API}/health`);
      const d = await r.json();
      const s = d.state || {};
      if (s.active_model && s.active_model !== 'none') valModel.textContent = s.active_model;
      if (s.groq_available || s.ollama_available)
        valProvider.textContent = s.groq_available ? 'GROQ' : 'OLLAMA';
      if (s.status === 'degraded') setStatus('degraded');
      else if (ws?.readyState === WebSocket.OPEN) setStatus('online');
    } catch { /* ignore */ }
  }

  pollMetrics();
  setInterval(pollMetrics, 5000);

  // ── URL shortcut handling (manifest shortcuts) ─────────────────────────────
  const urlParams = new URLSearchParams(location.search);
  const cmdParam  = urlParams.get('cmd');
  if (cmdParam) {
    const cmdMap = { status: 'status', playing: "what's playing" };
    const resolved = cmdMap[cmdParam] || cmdParam;
    // Delay until WS is ready
    setTimeout(() => send(resolved), 2000);
  }

  // ── PWA service worker ─────────────────────────────────────────────────────
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/hud/sw.js').catch(() => {});
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  connect();
})();
