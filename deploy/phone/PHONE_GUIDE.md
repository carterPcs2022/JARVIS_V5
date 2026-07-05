# Giving JARVIS a Phone Number (Twilio)

## Setup
1. Sign up at [twilio.com](https://twilio.com) — new accounts get ~$15 free trial credit.
2. Buy a phone number (Console → Phone Numbers → Buy a number, ~$1/month).
3. In the number's configuration:
   - **Voice webhook**: `https://YOUR_DOMAIN/stark/phone/call` (HTTP POST)
   - **SMS webhook**: `https://YOUR_DOMAIN/stark/phone/sms` (HTTP POST)
4. Add to `.env`:
   ```
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=your_auth_token
   TWILIO_PHONE=+1XXXXXXXXXX
   MY_PHONE_NUMBER=+1YYYYYYYYYY   # your number, for JARVIS-initiated alert calls
   PUBLIC_URL=https://YOUR_DOMAIN
   ```
5. Restart JARVIS. Call your new number — JARVIS answers.

## What this gets you
- **Call JARVIS** from any phone, no app required. He transcribes, thinks, and speaks back.
- **Text JARVIS** — reply comes back as SMS.
- **JARVIS calls you** for critical alerts — wired into `core/event_bus.py`'s
  `bus.alert(..., severity="critical")`, which now also places a real phone
  call when Twilio is configured (in addition to the existing Telegram push
  and HUD toast).

## Cost note
Twilio charges per minute/SMS after the trial credit runs out (a phone
number is ~$1/month, calls are typically ~$0.01-0.02/min in the US). This
is entirely opt-in — nothing in this feature runs unless `TWILIO_ACCOUNT_SID`
etc. are set.
