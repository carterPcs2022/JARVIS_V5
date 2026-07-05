"""services/remote_control.py — control your Mac remotely through JARVIS.
When JARVIS is running on Render (no display, no osascript), this reaches
your actual Mac over Tailscale via SSH instead. When running locally, it
executes directly. Distinct from server/routes/mac.py, which controls
whatever machine the server process itself is running on."""
import os
import subprocess

from config.settings import TAILSCALE_IP, IS_RAILWAY

MAC_USERNAME = os.getenv("MAC_USERNAME", "")


class RemoteMacControl:

    SAFE_COMMANDS = {
        "lock_screen":  "pmset displaysleepnow",
        "screenshot":   "screencapture -x /tmp/jarvis_screen.png",
        "volume_up":    "osascript -e 'set volume output volume ((output volume of (get volume settings)) + 10)'",
        "volume_down":  "osascript -e 'set volume output volume ((output volume of (get volume settings)) - 10)'",
        "mute":         "osascript -e 'set volume with output muted'",
        "unmute":       "osascript -e 'set volume without output muted'",
        "sleep":        "pmset sleepnow",
        "battery":      "pmset -g batt",
        "wifi_status":  "networksetup -getairportnetwork en0",
        "running_apps": 'osascript -e \'tell app "System Events" to get name of processes where background only is false\'',
    }

    def execute(self, command_name: str) -> dict:
        """Execute a named safe command on your Mac."""
        if command_name not in self.SAFE_COMMANDS:
            return {"error": f"Command '{command_name}' not in safe list"}

        cmd = self.SAFE_COMMANDS[command_name]

        # Running on a hosted server with no local Mac access → SSH over Tailscale
        if IS_RAILWAY and TAILSCALE_IP and MAC_USERNAME:
            ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no",
                      f"{MAC_USERNAME}@{TAILSCALE_IP}", cmd]
            try:
                result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
                return {"command": command_name, "stdout": result.stdout.strip(),
                        "success": result.returncode == 0}
            except Exception as e:
                return {"error": str(e)}

        if IS_RAILWAY:
            return {"error": "Remote control unavailable — TAILSCALE_IP/MAC_USERNAME not configured"}

        # Running locally → direct execution
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return {"command": command_name, "stdout": result.stdout.strip(),
                    "success": result.returncode == 0}
        except Exception as e:
            return {"error": str(e)}

    def get_screenshot(self) -> str | None:
        """Take a screenshot and return it as base64 (local execution only —
        a remote SSH round-trip can't retrieve the file without scp)."""
        result = self.execute("screenshot")
        if result.get("success") and not IS_RAILWAY:
            try:
                import base64
                with open("/tmp/jarvis_screen.png", "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                pass
        return None


mac = RemoteMacControl()
