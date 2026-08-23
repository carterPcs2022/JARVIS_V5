(() => {
  'use strict';

  const HOST   = location.hostname;
  const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsPort     = location.protocol === 'https:' ? '' : ':8000';
  const API    = `${location.protocol}//${HOST}${wsPort}`;
  const WS_URL = `${wsProtocol}//${HOST}${wsPort}/ws/chat`;
  const DEV_MODE = location.hostname === 'localhost' || location.hostname === '127.0.0.1';

  function getToken() { return localStorage.getItem('jarvis_token') || ''; }

  // Plain DOM overlay instead of window.prompt() — confirmed the real
  // cause of a real lockout: prompt()/alert()/confirm() are unreliable
  // or silently no-op in iOS Safari's "Add to Home Screen" standalone
  // PWA mode, which is exactly how this HUD gets used on a phone. A
  // silently-failing prompt() left getToken() permanently empty, the
  // WebSocket kept sending token="" forever, and there was no way back
  // in short of manually clearing browser site data. A bare DOM element
  // always renders, standalone or not.
  function askForToken(message) {
    return new Promise((resolve) => {
      const backdrop = document.createElement('div');
      backdrop.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;padding:20px;';
      backdrop.innerHTML = `
        <div style="background:#0a0f12;border:1px solid #2f5866;border-radius:6px;padding:20px;width:100%;max-width:340px;font-family:monospace;">
          <div style="font-size:12px;letter-spacing:1px;color:#7fb0c4;margin-bottom:12px;">${message}</div>
          <input type="text" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false"
                 style="width:100%;background:rgba(255,255,255,0.05);border:1px solid #2f5866;color:#5fd8ff;padding:10px;font-family:inherit;font-size:14px;border-radius:4px;box-sizing:border-box;" />
          <div style="display:flex;gap:8px;margin-top:14px;justify-content:flex-end;">
            <button class="tok-skip" style="padding:8px 16px;border:1px solid #2f5866;background:transparent;color:#7fb0c4;border-radius:4px;font-family:inherit;font-size:12px;">SKIP</button>
            <button class="tok-ok" style="padding:8px 16px;border:1px solid #5fd8ff;background:rgba(95,216,255,0.1);color:#5fd8ff;border-radius:4px;font-family:inherit;font-size:12px;">CONNECT</button>
          </div>
        </div>`;
      document.body.appendChild(backdrop);
      const input = backdrop.querySelector('input');
      const finish = (val) => { backdrop.remove(); resolve(val); };
      backdrop.querySelector('.tok-skip').onclick = () => finish(null);
      backdrop.querySelector('.tok-ok').onclick = () => finish(input.value.trim());
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') finish(input.value.trim()); });
      setTimeout(() => input.focus(), 50);
    });
  }

  // Mirrors hud_mobile/desktop.html's ensureToken() — bootstraps a token
  // from ?token=... in the URL (e.g. from a saved home-screen shortcut
  // link) if present, else prompts if nothing is saved yet.
  async function ensureToken() {
    const urlParams = new URLSearchParams(location.search);
    const urlToken = urlParams.get('token');
    if (urlToken) {
      localStorage.setItem('jarvis_token', urlToken);
      window.history.replaceState({}, '', location.pathname);
    }
    if (!getToken() && !DEV_MODE) {
      const t = await askForToken('Enter your JARVIS API token:\n(leave blank if not set)');
      if (t) localStorage.setItem('jarvis_token', t);
    }
  }
  ensureToken();

  // ── Suit assembly boot tones (Web Audio, no audio files needed) ─────────────
  let _assemblyIndex = 0;
  function playAssemblyTone(index) {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 220 * Math.pow(1.2, index);
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.5);
    } catch (e) { /* Web Audio unsupported/blocked — silent no-op */ }
  }

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
  const valRetinal  = document.getElementById('val-retinal');

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
    // No playLatestVoice() call here — matches desktop.html's rule: the
    // streaming path (server/websocket.py's _try_stream()) already kicks
    // off background voice generation before sending stream_end, and a
    // real audio_ready event (with the exact filename(s)) always follows
    // once it's ready. This used to call playLatestVoice() unconditionally
    // on every stream_end/response — a "guess the latest file" fallback
    // that predates last night's chunked-speech fix, and would only ever
    // fetch the LAST chunk of a multi-chunk response, silently dropping
    // everything before it. See playAudioQueue() below, which is what
    // audio_ready now drives instead.
  }

  // iOS WebKit (and in particular in-app browsers embedding it, e.g. an
  // app's own WebView) only allows audio.play() to succeed when it's called
  // synchronously inside a real user gesture (tap/click/keydown) — a
  // .play() triggered later from an async WebSocket 'audio_ready' message,
  // even one that followed a message the user just sent, no longer counts.
  // WebKit rejects it with NotAllowedError, which every .catch(() => {})
  // below used to swallow completely — audio silently never played, with
  // no error anywhere the user could see. unlockAudio() plays+pauses a
  // silent clip synchronously inside the gesture handlers that call send()
  // and toggleVoice() (see their call sites below), which "unlocks" the
  // page for the rest of the session per the same trick every JS audio
  // library uses for this exact WebKit restriction — after that, later
  // async .play() calls succeed normally.
  let _audioUnlocked = false;
  function unlockAudio() {
    if (_audioUnlocked) return;
    _audioUnlocked = true;
    try {
      const a = new Audio('data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=');
      a.play().then(() => a.pause()).catch(() => { _audioUnlocked = false; });
    } catch { _audioUnlocked = false; }
  }

  // Fallback ONLY for the non-streaming 'response' path (brain.process_dict(),
  // which doesn't consistently emit audio_ready the way the streaming path
  // does) — same "guess and fetch latest" approach as before, same
  // limitation (only correct for a single-chunk response), kept only where
  // there's no better signal available. Mirrors desktop.html's
  // playLatestVoiceFallback() exactly.
  let lastVoicePlay = 0;
  function playLatestVoice() {
    if (localStorage.getItem('jarvis_voice_muted') === 'true') return;
    const now = Date.now();
    if (now - lastVoicePlay < 1000) return;
    lastVoicePlay = now;
    setTimeout(() => {
      const audio = new Audio(`${API}/stark/voice/audio?t=${Date.now()}`);
      audio.play().catch(e => console.warn('[JARVIS] voice playback blocked:', e.name, e.message));
    }, 400);
  }

  // Plays one or more audio_ready filenames back-to-back, in order — the
  // real fix for #3 (regular chat responses never played audio on mobile
  // at all, even though the voice-conversation path's playback machinery
  // already existed). Mirrors desktop.html's playAudioQueue(), minus the
  // wake-word-specific hooks (openConversationWindow, onJarvisSpeak/Done)
  // that don't apply here since mobile intentionally has no always-
  // listening mode (see Stage 1 audit, item #5 — left as-is on purpose).
  function playAudioQueue(filenames) {
    if (localStorage.getItem('jarvis_voice_muted') === 'true') return;
    if (!filenames || !filenames.length) return;
    let idx = 0;
    function playNext() {
      if (idx >= filenames.length) return;
      const filename = filenames[idx++];
      const audio = new Audio(`${API}/stark/voice/audio?file=${encodeURIComponent(filename)}&t=${Date.now()}`);
      audio.addEventListener('ended', playNext);
      audio.addEventListener('error', playNext);
      audio.play().catch(e => { console.warn('[JARVIS] voice playback blocked:', e.name, e.message); playNext(); });
    }
    playNext();
  }

  // Renders JARVIS's ask_user_choice pending questions as clickable
  // buttons under the bubble that asked them (see core/ask_user_choice.py,
  // server/websocket.py's pending_choice field) — mirrors desktop.html's
  // renderChoicePrompt() exactly, adapted to this file's addBubble()/send()
  // instead of desktop.html's addMessage()/sendMessage(). One shared
  // click-to-select + Submit flow covers both single questions
  // (allow_multiple=false, one selection auto-clears any other) and
  // multiple questions/multi-select — Submit sends every selected option
  // across all questions as one comma-joined message, which
  // core.ask_user_choice.resolve_reply() parses back apart server-side.
  function renderChoicePrompt(bubbleEl, pendingChoice) {
    if (!pendingChoice || !Array.isArray(pendingChoice.questions) || !pendingChoice.questions.length) return;

    const wrap = document.createElement('div');
    wrap.className = 'choice-prompt';
    const selections = pendingChoice.questions.map(() => new Set());
    let submitBtn;

    pendingChoice.questions.forEach((q, qi) => {
      const label = document.createElement('div');
      label.className = 'choice-question-text';
      label.textContent = q.question + (q.allow_multiple ? ' (pick one or more)' : '');
      wrap.appendChild(label);

      const optsDiv = document.createElement('div');
      optsDiv.className = 'choice-options';
      (q.options || []).forEach((opt) => {
        const btn = document.createElement('button');
        btn.className = 'choice-btn';
        btn.type = 'button';
        btn.textContent = opt;
        btn.addEventListener('click', () => {
          const sel = selections[qi];
          if (sel.has(opt)) {
            sel.delete(opt);
            btn.classList.remove('choice-btn-selected');
          } else {
            if (!q.allow_multiple) {
              sel.clear();
              optsDiv.querySelectorAll('.choice-btn-selected').forEach((b) => b.classList.remove('choice-btn-selected'));
            }
            sel.add(opt);
            btn.classList.add('choice-btn-selected');
          }
          if (submitBtn) submitBtn.disabled = !selections.some((s) => s.size > 0);
        });
        optsDiv.appendChild(btn);
      });
      wrap.appendChild(optsDiv);
    });

    submitBtn = document.createElement('button');
    submitBtn.className = 'choice-btn choice-submit';
    submitBtn.type = 'button';
    submitBtn.textContent = 'SUBMIT';
    submitBtn.disabled = true;
    submitBtn.addEventListener('click', () => {
      const chosen = selections.flatMap((s) => Array.from(s));
      if (!chosen.length) return;
      wrap.remove();
      send(chosen.join(', '));
    });
    wrap.appendChild(submitBtn);

    bubbleEl.appendChild(wrap);
    chatLog.scrollTop = chatLog.scrollHeight;
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
    ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(getToken())}`);

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
        case 'stream_end': {
          const bubble = streamBubble;
          endStream(msg);
          addEvent('ok', `Done · ${msg.latency_ms||0} ms`);
          if (msg.pending_choice && bubble) renderChoicePrompt(bubble, msg.pending_choice);
          break;
        }
        case 'response': {
          endStream(null);
          const bubble = addBubble('assistant', msg.response || '');
          updatePanels(msg);
          sendBtn.disabled = false; input.focus();
          addEvent('ok', `Response · ${msg.latency_ms||0} ms`);
          // Only the non-streaming fallback path lacks a reliable
          // audio_ready event — see playLatestVoice()'s comment.
          if (msg.has_audio !== false) playLatestVoice();
          if (msg.pending_choice) renderChoicePrompt(bubble, msg.pending_choice);
          break;
        }
        case 'audio_ready':
          // Exact filename(s) from the background TTS generation — no
          // guessing, and (unlike playLatestVoice()) correctly plays every
          // chunk of a long response in order, not just the last one.
          playAudioQueue(msg.audio_files || [msg.audio_file]);
          break;
        case 'protocol':
          addBubble('protocol', `🛡 ${msg.data?.protocol}: ${msg.data?.detail || msg.data?.message || ''}`);
          addEvent('protocol', msg.data?.protocol || 'Protocol event');
          break;
        case 'alert':
          addEvent('alert', msg.data?.message || JSON.stringify(msg.data));
          break;
        case 'suit_assembly': {
          // core.event_bus.publish("suit_assembly", event) wraps every event
          // from the sequence — including the final "suit_complete" one —
          // under the same outer type, so the real per-event type lives at
          // msg.data.type, not msg.type.
          const d = msg.data || {};
          if (d.type === 'suit_complete') {
            addBubble('system', d.message || 'All systems nominal.');
            addEvent('ok', d.message || 'Suit assembly complete');
          } else {
            addEvent('system', `${d.icon || ''} ${d.system || ''}: ${d.status || ''}`);
            playAssemblyTone(_assemblyIndex++);
          }
          break;
        }
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
      //
      // 1008 specifically means server/websocket.py's _ws_token_ok()
      // rejected the token (server/websocket.py:79-83) — not a network
      // problem, the saved token is just wrong. The old behavior blindly
      // retried with that same rejected token every 5s forever: confirmed
      // live, a bad token got stuck in localStorage with literally no way
      // back short of manually clearing browser site data, since
      // ensureToken() only ever prompts when getToken() is empty — a
      // wrong-but-non-empty cached token silently short-circuits that
      // check permanently. Clear it and re-prompt instead of repeating
      // the same failure forever.
      if (e.code === 1008) {
        addEvent('error', 'Token rejected — clearing it and asking for a new one.');
        localStorage.removeItem('jarvis_token');
        ensureToken().then(connect);
        return;
      }
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
    unlockAudio();
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
    voiceWs = new WebSocket(`${wsProtocol}//${HOST}${wsPort}/stark/voice/ws?token=${encodeURIComponent(getToken())}`);
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
      a.play().catch(e => console.warn('[JARVIS] voice playback blocked:', e.name, e.message));
      a.onended = () => URL.revokeObjectURL(url);
    } catch (e) { addEvent('error', `Audio: ${e.message}`); }
  }

  // Fix #4 (Stage 1 audit): the 🔇 button used to call quickSend('mute'),
  // which just sent the literal text "mute" as a chat message — it never
  // touched the jarvis_voice_muted flag playLatestVoice()/playAudioQueue()
  // both already check. Mirrors desktop.html's toggleMute(): a real
  // client-side toggle, no round trip to the server needed.
  window.toggleMute = () => {
    const muted = localStorage.getItem('jarvis_voice_muted') === 'true';
    const next = !muted;
    localStorage.setItem('jarvis_voice_muted', next);
    _applyMuteButtonState(next);
  };

  function _applyMuteButtonState(muted) {
    const btn = document.getElementById('mute-btn');
    if (!btn) return;
    btn.textContent = muted ? '🔈' : '🔇';
    btn.style.opacity = muted ? '0.5' : '1';
    btn.title = muted ? 'Unmute JARVIS voice' : 'Mute JARVIS voice';
  }
  _applyMuteButtonState(localStorage.getItem('jarvis_voice_muted') === 'true');

  // Stage 1 audit item #11 — the only one of the five desktop-only info
  // panels the user wants mirrored on mobile. Same one-time fetch as
  // desktop.html's pollRetinal() (enrollment status doesn't change during
  // a session, so no polling interval needed) — just rendered as a text
  // value here instead of a footer dot, to match mobile's existing
  // info-row style.
  async function pollRetinal() {
    if (!valRetinal) return;
    try {
      const r = await fetch(`${API}/stark/auth/retinal/status`, {
        headers: getToken() ? {Authorization: `Bearer ${getToken()}`} : {}
      });
      const d = await r.json();
      valRetinal.textContent = d.enrolled ? 'ENROLLED' : 'NOT ENROLLED';
      valRetinal.className = `info-val ${d.enrolled ? 'ok' : ''}`;
    } catch (e) { /* leave as — */ }
  }

  async function toggleVoice() {
    unlockAudio();
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
        headers: getToken() ? {Authorization: `Bearer ${getToken()}`} : {}
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
      // Missing Authorization header used to make this a guaranteed 401
      // every 30s (server/routes/telemetry.py requires verify_token same
      // as every other route) -- five of those trips sentinel's brute-
      // force threshold (services/sentinel.py's 15-minute IP block),
      // which then 403s EVERY request from this IP, including an
      // otherwise-correct WebSocket token. Confirmed live: this is what
      // was actually behind "the token stopped working" on production.
      const r = await fetch(`${API}/stark/telemetry`, {
        headers: getToken() ? {Authorization: `Bearer ${getToken()}`} : {}
      });
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
  setInterval(pollMetrics, 30000);
  pollRetinal(); // one-time — retinal enrollment status doesn't change during a session

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

  // ── Stark Protocol 2FA — approve from phone ────────────────────────────────
  // Lockdown/Coldfire/Scatter require passphrase + two-step confirm + iris
  // (server/routes/protocols.py, server/routes/scatter.py). The iris leg
  // previously only worked from desktop.html's camera capture — this file
  // had no iris code at all, so completing the flow required being
  // physically at the Mac. The actual biometric processing happens
  // server-side on the Mac Bridge, not in the browser, so capturing from a
  // phone's camera works identically — this closes that gap.

  const PROTOCOL_ENDPOINTS = {
    lockdown: '/stark/lockdown',
    coldfire: '/stark/coldfire',
    scatter:  '/stark/scatter',
  };

  async function captureIrisFrame() {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
    const backdrop = document.createElement('div');
    backdrop.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(2,4,5,0.9);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;';
    const video = document.createElement('video');
    video.autoplay = true; video.playsInline = true; video.muted = true;
    video.style.cssText = 'width:min(440px,85vw);border:1px solid #5fd8ff;border-radius:4px;transform:scaleX(-1);';
    video.srcObject = stream;
    const label = document.createElement('div');
    label.style.cssText = 'color:#5fd8ff;font-family:monospace;font-size:12px;letter-spacing:2px;text-align:center;';
    backdrop.appendChild(video); backdrop.appendChild(label);
    document.body.appendChild(backdrop);

    try {
      await new Promise((resolve, reject) => {
        video.onloadedmetadata = resolve;
        setTimeout(() => reject(new Error('camera_timeout')), 8000);
      });
      for (let i = 3; i >= 1; i--) {
        label.textContent = `FRAME YOUR EYE — CAPTURING IN ${i}...`;
        await new Promise((r) => setTimeout(r, 1000));
      }
      label.textContent = 'CAPTURING...';
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth; canvas.height = video.videoHeight;
      canvas.getContext('2d').drawImage(video, 0, 0);
      return await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
    } finally {
      stream.getTracks().forEach((t) => t.stop());
      backdrop.remove();
    }
  }

  async function verifyIrisForConfirmation() {
    let blob;
    try {
      blob = await captureIrisFrame();
    } catch (e) {
      addBubble('system', 'Iris capture failed — camera access denied or timed out.');
      return null;
    }
    const form = new FormData();
    form.append('image', blob, 'verify.jpg');
    form.append('profile', 'default');
    try {
      const r = await fetch(`${API}/stark/iris/verify`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${getToken()}` },
        body: form,
      });
      const data = await r.json();
      if (!data.verified) {
        addBubble('system', `Iris verification failed: ${data.error || 'no match'}.`);
        return null;
      }
      return data.iris_confirm_token || null;
    } catch (e) {
      addBubble('system', 'Iris verification failed — request error.');
      return null;
    }
  }

  function openProtocolApprovalPanel() {
    const backdrop = document.createElement('div');
    backdrop.style.cssText = 'position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;padding:20px;';
    backdrop.innerHTML = `
      <div style="background:#0a0f12;border:1px solid #2f5866;border-radius:6px;padding:20px;width:100%;max-width:360px;font-family:monospace;">
        <div style="font-size:12px;letter-spacing:1px;color:#7fb0c4;margin-bottom:12px;">APPROVE STARK PROTOCOL REQUEST</div>
        <select class="pa-protocol" style="width:100%;background:rgba(255,255,255,0.05);border:1px solid #2f5866;color:#5fd8ff;padding:8px;font-family:inherit;font-size:13px;border-radius:4px;box-sizing:border-box;margin-bottom:8px;">
          <option value="lockdown">Suit Lockdown</option>
          <option value="coldfire">Coldfire</option>
          <option value="scatter">Scatter</option>
        </select>
        <input class="pa-passphrase" type="password" placeholder="Passphrase" autocomplete="off"
               style="width:100%;background:rgba(255,255,255,0.05);border:1px solid #2f5866;color:#5fd8ff;padding:10px;font-family:inherit;font-size:14px;border-radius:4px;box-sizing:border-box;margin-bottom:8px;" />
        <input class="pa-token" type="text" placeholder="confirm_token (from the Pushover alert)" autocomplete="off"
               style="width:100%;background:rgba(255,255,255,0.05);border:1px solid #2f5866;color:#5fd8ff;padding:10px;font-family:inherit;font-size:14px;border-radius:4px;box-sizing:border-box;margin-bottom:8px;" />
        <div class="pa-status" style="font-size:11px;color:#7fb0c4;margin-bottom:8px;min-height:14px;"></div>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button class="pa-cancel" style="padding:8px 16px;border:1px solid #2f5866;background:transparent;color:#7fb0c4;border-radius:4px;font-family:inherit;font-size:12px;">CANCEL</button>
          <button class="pa-submit" style="padding:8px 16px;border:1px solid #5fd8ff;background:rgba(95,216,255,0.1);color:#5fd8ff;border-radius:4px;font-family:inherit;font-size:12px;">SCAN IRIS &amp; APPROVE</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);

    const statusEl = backdrop.querySelector('.pa-status');
    backdrop.querySelector('.pa-cancel').onclick = () => backdrop.remove();
    backdrop.querySelector('.pa-submit').onclick = async () => {
      const protocol   = backdrop.querySelector('.pa-protocol').value;
      const passphrase = backdrop.querySelector('.pa-passphrase').value;
      const confirmTok = backdrop.querySelector('.pa-token').value.trim();
      if (!passphrase || !confirmTok) {
        statusEl.textContent = 'Passphrase and confirm_token are both required.';
        return;
      }
      statusEl.textContent = 'Scanning iris...';
      const irisToken = await verifyIrisForConfirmation();
      if (!irisToken) {
        statusEl.textContent = 'Iris verification failed — not submitted.';
        return;
      }
      statusEl.textContent = 'Iris verified — submitting...';
      try {
        const r = await fetch(`${API}${PROTOCOL_ENDPOINTS[protocol]}`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ passphrase, confirm_token: confirmTok, iris_token: irisToken }),
        });
        const data = await r.json();
        if (!r.ok) {
          statusEl.textContent = `Rejected: ${data.detail || data.error || r.status}`;
          return;
        }
        backdrop.remove();
        addBubble('system', `${protocol} approved and executed.`);
      } catch (e) {
        statusEl.textContent = 'Request failed — network error.';
      }
    };
  }

  // Floating approve button — always available, independent of chat state.
  (function addProtocolApprovalButton() {
    const btn = document.createElement('button');
    btn.textContent = '🔐';
    btn.title = 'Approve a pending Stark Protocol request';
    // bottom:80px collided almost exactly with the existing voice mic
    // button in the input row — confirmed live via a real click test that
    // hit the wrong element. 170px clears the whole toolbar+input area,
    // sitting just above it instead.
    btn.style.cssText = 'position:fixed;bottom:170px;right:16px;z-index:500;width:44px;height:44px;border-radius:50%;border:1px solid #2f5866;background:#0a0f12;color:#5fd8ff;font-size:18px;box-shadow:0 2px 8px rgba(0,0,0,0.4);';
    btn.onclick = openProtocolApprovalPanel;
    document.body.appendChild(btn);
  })();

  // ── Boot ───────────────────────────────────────────────────────────────────
  connect();
})();
