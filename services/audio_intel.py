"""
services/audio_intel.py — AudioIntelligence: music mood, ambient sound, visualizer, song ID.
"""
import os
import random
from datetime import datetime

try:
    import pygame
    import pygame.sndarray
except ImportError:
    pygame = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    from scipy.fft import fft as scipy_fft
except ImportError:
    scipy_fft = None

from core.llm.router import think

AMBIENT_URLS = {
    "rain":        "https://mynoise.net/NoiseMachines/rainNoise.php",
    "white_noise": "https://mynoise.net/NoiseMachines/whiteNoiseGenerator.php",
    "brown_noise": "https://mynoise.net/NoiseMachines/brownNoiseGenerator.php",
    "coffee_shop": "https://coffitivity.com/",
    "ocean":       "https://mynoise.net/NoiseMachines/oceanNoise.php",
}


class AudioIntelligence:

    # ------------------------------------------------------------------ #
    # Music mood                                                           #
    # ------------------------------------------------------------------ #

    def music_mood_match(self, context: str = "") -> dict:
        """LLM recommends genres/playlist based on time of day and context."""
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 9:
            time_ctx = "early morning, waking up"
        elif 9 <= hour < 12:
            time_ctx = "morning, starting the work day"
        elif 12 <= hour < 14:
            time_ctx = "midday, lunch break"
        elif 14 <= hour < 18:
            time_ctx = "afternoon, deep work"
        elif 18 <= hour < 21:
            time_ctx = "evening, winding down"
        else:
            time_ctx = "night, late hours"

        prompt = (
            f"Recommend music for JARVIS's user. Time context: {time_ctx}. "
            f"Additional context: {context if context else 'none'}.\n"
            "Return a JSON object with keys: "
            '"recommendation" (string), "genres" (list of 3-5 genres), '
            '"mood" (one word), "time_context" (string). '
            "Return only valid JSON."
        )
        raw = think(prompt)

        try:
            import re, json
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            parsed = json.loads(m.group(0)) if m else {}
        except Exception:
            parsed = {}

        return {
            "recommendation": parsed.get("recommendation", raw),
            "genres":         parsed.get("genres", []),
            "mood":           parsed.get("mood", "focused"),
            "time_context":   time_ctx,
        }

    # ------------------------------------------------------------------ #
    # Ambient sound                                                        #
    # ------------------------------------------------------------------ #

    def ambient_sound(self, sound_type: str = "rain") -> dict:
        """Play or provide ambient sound. Generates noise tones via pygame when possible."""
        url = AMBIENT_URLS.get(sound_type)

        # Try pygame generation for noise types
        if pygame is not None and np is not None and sound_type in ("white_noise", "brown_noise"):
            try:
                pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=2048)
                sample_rate = 44100
                duration    = 5  # seconds of buffer
                samples     = sample_rate * duration

                if sound_type == "white_noise":
                    audio = (np.random.uniform(-1, 1, samples) * 32767).astype(np.int16)
                else:  # brown_noise
                    white  = np.random.randn(samples)
                    brown  = np.cumsum(white)
                    brown /= np.max(np.abs(brown))
                    audio  = (brown * 32767).astype(np.int16)

                sound = pygame.sndarray.make_sound(audio)
                sound.play(loops=-1)

                return {
                    "type":    sound_type,
                    "source":  "generated",
                    "status":  "playing",
                    "url":     url,
                }
            except Exception:
                pass

        # Fall back to providing the URL
        return {
            "type":   sound_type,
            "source": "url_provided",
            "status": "url_provided",
            "url":    url or "No URL available for this sound type.",
        }

    # ------------------------------------------------------------------ #
    # Visualizer                                                           #
    # ------------------------------------------------------------------ #

    def audio_visualizer_data(self) -> dict:
        """Record 0.1s of audio, compute FFT, return 8 frequency bins."""
        band_names = ["bass", "low_mid", "mid", "high_mid",
                      "presence", "brilliance", "air", "ultra"]

        if sd is None or scipy_fft is None or np is None:
            # Return simulated data
            return {
                "bands":     {band: round(random.random(), 3) for band in band_names},
                "simulated": True,
            }

        try:
            sample_rate = 44100
            duration    = 0.1
            recording   = sd.rec(
                int(sample_rate * duration),
                samplerate=sample_rate,
                channels=1,
                dtype="float64",
            )
            sd.wait()

            signal   = recording[:, 0]
            spectrum = np.abs(scipy_fft(signal))[: len(signal) // 2]
            n_bins   = len(spectrum)
            # Divide into 8 equal-ish bands
            bin_size = n_bins // 8
            bands_raw = [
                float(np.mean(spectrum[i * bin_size: (i + 1) * bin_size]))
                for i in range(8)
            ]
            max_val = max(bands_raw) or 1.0
            normalized = [round(v / max_val, 3) for v in bands_raw]

            return {
                "bands":     dict(zip(band_names, normalized)),
                "simulated": False,
            }
        except Exception:
            return {
                "bands":     {band: round(random.random(), 3) for band in band_names},
                "simulated": True,
            }

    # ------------------------------------------------------------------ #
    # Song identification                                                  #
    # ------------------------------------------------------------------ #

    def identify_song(self, audio_path: str) -> dict:
        """Identify a song using ACRCloud if configured."""
        acrcloud_key    = os.environ.get("ACRCLOUD_KEY")
        acrcloud_host   = os.environ.get("ACRCLOUD_HOST")
        acrcloud_secret = os.environ.get("ACRCLOUD_SECRET")

        if not (acrcloud_key and acrcloud_host and acrcloud_secret):
            return {
                "status":  "not_configured",
                "message": (
                    "Set ACRCLOUD_KEY, ACRCLOUD_HOST, ACRCLOUD_SECRET env vars "
                    "to enable song identification"
                ),
            }

        try:
            import base64, hashlib, hmac, time as _time
            import requests as _requests

            http_method  = "POST"
            http_uri     = "/v1/identify"
            access_key   = acrcloud_key
            data_type    = "audio"
            signature_version = "1"
            timestamp    = str(int(_time.time()))

            string_to_sign = "\n".join([
                http_method, http_uri, access_key,
                data_type, signature_version, timestamp,
            ])
            sign = base64.b64encode(
                hmac.new(
                    acrcloud_secret.encode("utf-8"),
                    string_to_sign.encode("utf-8"),
                    digestmod=hashlib.sha1,
                ).digest()
            ).decode("utf-8")

            with open(audio_path, "rb") as f:
                audio_data = f.read()

            files = {"sample": audio_data}
            data  = {
                "access_key":        access_key,
                "sample_bytes":      len(audio_data),
                "timestamp":         timestamp,
                "signature":         sign,
                "data_type":         data_type,
                "signature_version": signature_version,
            }
            resp = _requests.post(
                f"https://{acrcloud_host}{http_uri}",
                files=files,
                data=data,
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()

            metadata = result.get("metadata", {})
            music    = metadata.get("music", [{}])[0]

            return {
                "status":  "identified" if result.get("status", {}).get("code") == 0 else "not_found",
                "title":   music.get("title", "Unknown"),
                "artist":  ", ".join(a["name"] for a in music.get("artists", [])),
                "album":   music.get("album", {}).get("name", ""),
                "raw":     result,
            }

        except Exception as e:
            return {"status": "error", "error": str(e)}


# Module-level singleton
audio = AudioIntelligence()
