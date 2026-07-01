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


def snapshot() -> dict:
    mem  = _safe_mem()
    disk = psutil.disk_usage("/")
    cpu  = _safe_cpu()
    return {
        "timestamp":      datetime.datetime.now().isoformat(),
        "os":             platform.system(),
        "hostname":       socket.gethostname(),
        "cpu_percent":    cpu,
        "cpu_cores":      psutil.cpu_count(logical=True),
        "ram_total_gb":   round(mem.total / 1e9, 2),
        "ram_used_pct":   mem.percent,
        "disk_total_gb":  round(disk.total / 1e9, 2),
        "disk_used_pct":  disk.percent,
        "uptime_hours":   round(
            (datetime.datetime.now() -
             datetime.datetime.fromtimestamp(psutil.boot_time())).total_seconds() / 3600, 2),
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
    pct = psutil.disk_usage("/").percent
    return f"⚠️ Disk at {pct}%" if pct >= threshold else None
