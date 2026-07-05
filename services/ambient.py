"""services/ambient.py — Tony's workshop ambient sound, generated purely
with the Web Audio API (no audio files). Injected into hud_mobile/desktop.
html; this module just holds the script as a constant so it isn't inline
noise in the HTML file."""

AMBIENT_HUD_SCRIPT = """
class AmbientAudio {
    constructor() {
        this.ctx = null;
        this.nodes = [];
        this.active = false;
    }

    start(mode = 'workshop') {
        if (this.active) return;
        this.ctx = new (window.AudioContext || window.webkitAudioContext)();
        this.active = true;

        const modes = {
            workshop: () => {
                this._addOsc(60, 0.04, 'sine');
                this._addOsc(120, 0.02, 'sine');
                this._addNoise(0.01);
                this._addPulse(0.005, 4000, 8000);
            },
            focus: () => {
                this._addBrownNoise(0.05);
            },
            night: () => {
                this._addOsc(40, 0.02, 'sine');
                this._addNoise(0.005);
            },
        };

        (modes[mode] || modes.workshop)();
    }

    stop() {
        this.nodes.forEach(n => {
            try { n.stop(); } catch(e) {}
            try { n.disconnect(); } catch(e) {}
        });
        this.nodes = [];
        this.active = false;
    }

    _addOsc(freq, gain, type) {
        const osc = this.ctx.createOscillator();
        const g = this.ctx.createGain();
        osc.frequency.value = freq;
        osc.type = type;
        g.gain.value = gain;
        osc.connect(g);
        g.connect(this.ctx.destination);
        osc.start();
        this.nodes.push(osc, g);
    }

    _addNoise(gain) {
        const bufLen = this.ctx.sampleRate * 2;
        const buffer = this.ctx.createBuffer(1, bufLen, this.ctx.sampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < bufLen; i++) {
            data[i] = Math.random() * 2 - 1;
        }
        const source = this.ctx.createBufferSource();
        const g = this.ctx.createGain();
        source.buffer = buffer;
        source.loop = true;
        g.gain.value = gain;
        source.connect(g);
        g.connect(this.ctx.destination);
        source.start();
        this.nodes.push(source, g);
    }

    _addBrownNoise(gain) {
        const bufLen = this.ctx.sampleRate * 4;
        const buffer = this.ctx.createBuffer(1, bufLen, this.ctx.sampleRate);
        const data = buffer.getChannelData(0);
        let last = 0;
        for (let i = 0; i < bufLen; i++) {
            const white = Math.random() * 2 - 1;
            data[i] = last = (last + 0.02 * white) / 1.02;
        }
        const source = this.ctx.createBufferSource();
        const g = this.ctx.createGain();
        source.buffer = buffer;
        source.loop = true;
        g.gain.value = gain * 3;
        source.connect(g);
        g.connect(this.ctx.destination);
        source.start();
        this.nodes.push(source, g);
    }

    _addPulse(gain, minFreq, maxFreq) {
        const pulse = () => {
            if (!this.active) return;
            const osc = this.ctx.createOscillator();
            const g = this.ctx.createGain();
            osc.frequency.value = minFreq + Math.random() * (maxFreq - minFreq);
            g.gain.setValueAtTime(gain, this.ctx.currentTime);
            g.gain.exponentialRampToValueAtTime(0.0001, this.ctx.currentTime + 0.05);
            osc.connect(g);
            g.connect(this.ctx.destination);
            osc.start();
            osc.stop(this.ctx.currentTime + 0.05);
            setTimeout(pulse, 3000 + Math.random() * 8000);
        };
        pulse();
    }
}

const ambient = new AmbientAudio();

function toggleAmbient(mode) {
    if (ambient.active) {
        ambient.stop();
        document.getElementById('ambient-btn').textContent = '🔇 AMBIENT';
    } else {
        ambient.start(mode || 'workshop');
        document.getElementById('ambient-btn').textContent = '🔊 AMBIENT';
    }
}
"""
