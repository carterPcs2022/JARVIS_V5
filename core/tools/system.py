"""core/tools/system.py — System telemetry and safe shell."""
import psutil, datetime, socket, subprocess, platform


ALLOWED_CMDS = ("ls","pwd","df","du","uptime","uname","whoami","date",
                "echo","cat /proc","ping","ip addr","ifconfig","netstat","free","ps")


def _safe_cpu() -> float:
    try:
        return psutil.cpu_percent(interval=0.5)
    except Exception:
        try:
            # Fallback: parse macOS sysctl
            import subprocess, re
            out = subprocess.check_output(["top","-l","1","-n","0"], timeout=3, text=True)
            m = re.search(r"(\d+\.\d+)%\s+idle", out)
            return round(100 - float(m.group(1)), 1) if m else 0.0
        except Exception:
            return 0.0


def _safe_mem():
    try:
        return psutil.virtual_memory()
    except Exception:
        # Return a namespace-like object with safe defaults
        import subprocess, re
        total, used, pct = 0, 0, 0.0
        try:
            out = subprocess.check_output(["vm_stat"], timeout=3, text=True)
            page_size = 16384
            pages_free  = int(re.search(r"Pages free:\s+(\d+)", out).group(1))
            pages_total = 0
            for label in ("Pages free","Pages active","Pages inactive",
                          "Pages speculative","Pages wired down"):
                m = re.search(rf"{label}:\s+(\d+)", out)
                if m: pages_total += int(m.group(1))
            total = pages_total * page_size
            used  = (pages_total - pages_free) * page_size
            pct   = round(used / total * 100, 1) if total else 0.0
        except Exception:
            pass

        class _Mem:
            def __init__(self):
                self.total   = total
                self.percent = pct
        return _Mem()


def _safe_disk():
    try:
        return psutil.disk_usage("/")
    except Exception:
        class _Disk:
            total = 0
            percent = 0.0
        return _Disk()


def _safe_cpu_cores() -> int:
    try:
        return psutil.cpu_count(logical=True) or 0
    except Exception:
        return 0


def _safe_uptime_hours() -> float:
    try:
        return round(
            (datetime.datetime.now() -
             datetime.datetime.fromtimestamp(psutil.boot_time())).total_seconds() / 3600, 2)
    except Exception:
        return 0.0


def snapshot() -> dict:
    """Every field is independently guarded — Render's sandboxed
    filesystem/cgroups can make individual psutil calls fail (e.g.
    disk_usage on a restricted mount), and previously an unguarded call
    here would blow up the whole snapshot(), leaving /hud/status and
    /stark/telemetry with empty data instead of the other fields that
    would have worked fine."""
    mem  = _safe_mem()
    disk = _safe_disk()
    cpu  = _safe_cpu()
    return {
        "timestamp":      datetime.datetime.now().isoformat(),
        "os":             platform.system(),
        "hostname":       socket.gethostname(),
        "cpu_percent":    cpu,
        "cpu_cores":      _safe_cpu_cores(),
        "ram_total_gb":   round(mem.total / 1e9, 2),
        "ram_used_pct":   mem.percent,
        "disk_total_gb":  round(disk.total / 1e9, 2),
        "disk_used_pct":  disk.percent,
        "uptime_hours":   _safe_uptime_hours(),
    }


def run_shell(command: str, timeout: int = 10) -> dict:
    cmd = command.strip().lower()
    if not any(cmd.startswith(p) for p in ALLOWED_CMDS):
        return {"error": f"Command not in allowlist: '{command}'"}
    try:
        r = subprocess.run(command, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return {"stdout": r.stdout.strip(), "stderr": r.stderr.strip(),
                "returncode": r.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "Timed out"}
    except Exception as e:
        return {"error": str(e)}


def disk_warning(threshold: float = 85.0) -> str | None:
    pct = _safe_disk().percent
    return f"⚠️ Disk at {pct}%" if pct >= threshold else None


def run_calculation(expression: str) -> dict:
    """"JARVIS run the numbers." Safe math evaluation — no arbitrary code
    execution. Falls back to the LLM only for expressions that aren't
    valid pure-math (e.g. word problems)."""
    import math
    import re as _re

    safe_names = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
    safe_names["abs"] = abs
    safe_names["round"] = round

    clean = _re.sub(r"[^0-9+\-*/.()%^ ]", "", expression)
    clean = clean.replace("^", "**")

    try:
        result = eval(clean, {"__builtins__": {}}, safe_names)
        return {
            "expression": expression, "result": result,
            "formatted": f"{result:,}" if isinstance(result, (int, float)) else str(result),
        }
    except Exception:
        from core.llm.router import think
        answer = think(f"Calculate: {expression}\nReply with just the numeric answer.",
                       force_model="instant")
        return {"expression": expression, "result": answer, "method": "llm"}
