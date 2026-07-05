"""services/phone.py — a real phone number for JARVIS via Twilio. Call him,
text him, or let him call you for critical alerts. Twilio is an optional
dependency — everything here degrades to a clear error if it isn't
installed/configured rather than crashing at import time."""
import os
import re

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_PHONE", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")


def _twilio_configured() -> bool:
    return bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM)


def _clean_for_speech(text: str) -> str:
    """Strip markdown and collapse newlines — phones don't render either,
    and TwiML <Say> reads them aloud literally otherwise."""
    clean = re.sub(r"[*_`#\[\]]", "", text)
    clean = re.sub(r"\n+", ". ", clean)
    return clean[:400]


class JarvisPhone:

    def handle_incoming_call(self) -> str:
        """Twilio webhook for an incoming call — greets, then records the
        caller's speech and posts it to /stark/phone/respond."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Matthew" rate="90%">
        Welcome. You have reached J.A.R.V.I.S. How can I assist you?
    </Say>
    <Record action="{PUBLIC_URL}/stark/phone/respond" method="POST"
            maxLength="30" playBeep="false" transcribe="true"
            transcribeCallback="{PUBLIC_URL}/stark/phone/transcribed" />
</Response>"""

    def handle_response(self, transcript: str) -> str:
        """Process what the caller said, run it through the brain, speak
        the response back, then keep listening."""
        from core.brain_v2 import brain
        result = brain.process_dict(transcript)
        clean = _clean_for_speech(result["response"])

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Matthew" rate="90%">{clean}</Say>
    <Record action="{PUBLIC_URL}/stark/phone/respond" method="POST"
            maxLength="30" playBeep="false" timeout="3" />
</Response>"""

    def handle_sms(self, from_number: str, message: str) -> str:
        """Someone texted JARVIS — process and text back."""
        if not _twilio_configured():
            return "Twilio not configured"

        from core.brain_v2 import brain
        result = brain.process_dict(message)
        response = result["response"][:1500]

        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=f"JARVIS: {response}", from_=TWILIO_FROM, to=from_number)
        return response

    def send_alert_call(self, message: str, to_number: str) -> dict:
        """JARVIS calls the user directly for a critical alert."""
        if not _twilio_configured():
            return {"error": "Twilio not configured (TWILIO_ACCOUNT_SID/AUTH_TOKEN/PHONE)"}
        if not to_number:
            return {"error": "No destination number provided (set MY_PHONE_NUMBER or pass 'to')"}

        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        clean_msg = _clean_for_speech(message)
        call = client.calls.create(
            twiml=f"""<Response>
                <Say voice="Polly.Matthew" rate="90%">
                    Sir. J.A.R.V.I.S. here. {clean_msg}
                    If you need to respond, please call back at your convenience.
                </Say>
            </Response>""",
            from_=TWILIO_FROM, to=to_number,
        )
        return {"call_sid": call.sid, "status": call.status}


phone = JarvisPhone()
