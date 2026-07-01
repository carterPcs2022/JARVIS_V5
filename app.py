"""app.py — JARVIS V5 entry point."""
import os
import uvicorn
from config.settings import HOST, PORT

if __name__ == "__main__":
    # Railway sets PORT automatically
    port = int(os.environ.get("PORT", PORT))

    print("╔══════════════════════════════════════╗")
    print("║       J.A.R.V.I.S  V5.0             ║")
    print(f"║  Starting on port {port:<19}║")
    print("╚══════════════════════════════════════╝")
    uvicorn.run("server.api:app", host=HOST, port=port, reload=False, log_level="info")
