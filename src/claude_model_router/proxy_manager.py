"""
Proxy process management for the protocol translation proxy.
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Tuple


def parse_proxy_url(proxy_url: str) -> Tuple[str, int, str]:
    """Parse a proxy URL into host, port, and scheme."""
    parsed = urllib.parse.urlparse(proxy_url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if scheme == "https" else 80)
    return host, port, scheme


def is_local_host(host: str) -> bool:
    """Check if a host is localhost."""
    return host in {"127.0.0.1", "localhost", "::1"}


def proxy_health_url(proxy_url: str) -> str:
    """Get the health check URL for a proxy."""
    return f"{proxy_url.rstrip('/')}/health"


def check_proxy_health(proxy_url: str, timeout: float = 0.5) -> Optional[dict]:
    """Check if the proxy is running and healthy."""
    try:
        request = urllib.request.Request(
            proxy_health_url(proxy_url),
            headers={"User-Agent": "claude-model-router/1.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8", "ignore") or "{}")
        if payload.get("status") != "ok":
            return None
        return payload
    except Exception:
        return None


def is_proxy_compatible(payload: dict) -> bool:
    """Check if the proxy supports required capabilities."""
    if not isinstance(payload, dict):
        return False
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    return bool(capabilities.get("supports_responses")) and bool(
        capabilities.get("retry_on_not_chat_model")
    )


def build_proxy_url(host: str, port: int, scheme: str) -> str:
    """Build a proxy URL from components."""
    host_part = host
    if ":" in host and not host.startswith("["):
        host_part = f"[{host}]"
    return f"{scheme}://{host_part}:{port}"


def candidate_proxy_urls(host: str, port: int, scheme: str, count: int = 5):
    """Generate candidate proxy URLs with incremental ports."""
    yield build_proxy_url(host, port, scheme)
    for offset in range(1, count + 1):
        yield build_proxy_url(host, port + offset, scheme)


def powershell_json(command: str) -> Optional[dict]:
    """Execute a PowerShell command and parse JSON output."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def list_proxy_processes() -> List[Tuple[int, str]]:
    """List running proxy processes."""
    script_name = "proxy.py"
    current_pid = os.getpid()
    processes = []
    if os.name == "nt":
        payload = powershell_json(
            "Get-CimInstance Win32_Process "
            '-Filter "CommandLine like \'%proxy.py%\'" '
            "| Select-Object ProcessId,CommandLine "
            "| ConvertTo-Json -Compress"
        )
        if payload is None:
            return processes
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            try:
                pid = int(item.get("ProcessId"))
            except (TypeError, ValueError):
                continue
            if pid == current_pid:
                continue
            cmdline = str(item.get("CommandLine") or "")
            if script_name.lower() not in cmdline.lower():
                continue
            processes.append((pid, cmdline))
        return processes
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError:
        return processes
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_str, cmdline = parts
        if script_name not in cmdline:
            continue
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if pid == current_pid:
            continue
        processes.append((pid, cmdline))
    return processes


def list_listening_pids(port: int) -> List[int]:
    """List PIDs listening on a specific port."""
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError:
        return []
    pids = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        state = parts[3]
        pid_str = parts[4]
        if state.upper() != "LISTENING":
            continue
        if not local_addr.endswith(f":{port}"):
            continue
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        pids.append(pid)
    return pids


def terminate_proxy_processes(proxy_url: str) -> List[int]:
    """Terminate running proxy processes."""
    killed = []
    for pid, _ in list_proxy_processes():
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except Exception:
            continue
    host, port, _ = parse_proxy_url(proxy_url)
    health = check_proxy_health(proxy_url, timeout=0.2)
    if is_local_host(host) and health is not None:
        for pid in list_listening_pids(port):
            if pid in killed or pid == os.getpid():
                continue
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    os.kill(pid, signal.SIGTERM)
                killed.append(pid)
            except Exception:
                continue
    return killed


def start_proxy_process(proxy_url: str, upstream_url: str) -> Tuple[bool, Optional[str]]:
    """Start the proxy process."""
    host, port, _ = parse_proxy_url(proxy_url)
    script_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "proxy.py",
    )
    if not os.path.exists(script_path):
        return False, "Missing proxy.py"
    cmd = [
        sys.executable,
        script_path,
        "--host",
        host,
        "--port",
        str(port),
        "--upstream",
        upstream_url,
    ]
    env = os.environ.copy()
    env["MODEL_ROUTER_PROXY_URL"] = proxy_url
    env["MODEL_ROUTER_OPENAI_BASE_URL"] = upstream_url
    try:
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags |= subprocess.CREATE_NO_WINDOW
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
            )
        else:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
        return True, None
    except OSError as exc:
        return False, str(exc)


def start_proxy_and_wait(proxy_url: str, upstream_url: str) -> Tuple[bool, Optional[str]]:
    """Start proxy and wait for it to be ready."""
    ok, error = start_proxy_process(proxy_url, upstream_url)
    if not ok:
        return False, f"Proxy startup failed: {error}"
    for _ in range(10):
        health = check_proxy_health(proxy_url, timeout=0.5)
        if health and is_proxy_compatible(health):
            return True, None
        time.sleep(0.2)
    return False, f"Proxy startup failed: cannot connect to {proxy_url}"


def ensure_proxy_running(
    proxy_url: str, upstream_url: str, force_restart: bool = False
) -> Tuple[str, Optional[str], str]:
    """Ensure the proxy is running, start or restart if needed."""
    host, port, scheme = parse_proxy_url(proxy_url)
    if not is_local_host(host):
        return "skip", f"Proxy URL {proxy_url} is not local, skipping auto-start.", proxy_url

    if force_restart:
        killed = terminate_proxy_processes(proxy_url)
        if killed:
            time.sleep(0.2)
        ok, error = start_proxy_and_wait(proxy_url, upstream_url)
        if ok:
            return "restarted", f"Proxy restarted: {proxy_url}", proxy_url
        prefix = "Stopped old proxy, trying to start new one."
        for candidate_url in candidate_proxy_urls(host, port, scheme):
            if candidate_url == proxy_url:
                continue
            ok, _ = start_proxy_and_wait(candidate_url, upstream_url)
            if ok:
                return "started", f"{prefix} Proxy started: {candidate_url}", candidate_url
        return "failed", error, proxy_url

    health = check_proxy_health(proxy_url)
    if health and is_proxy_compatible(health):
        return "running", f"Proxy already running: {proxy_url}", proxy_url

    if health and not is_proxy_compatible(health):
        prefix = f"Detected old proxy: {proxy_url}, trying to start new one."
        for candidate_url in candidate_proxy_urls(host, port, scheme):
            if candidate_url == proxy_url:
                continue
            candidate_health = check_proxy_health(candidate_url)
            if candidate_health and is_proxy_compatible(candidate_health):
                return "running", f"{prefix} Found available proxy: {candidate_url}", candidate_url
            if candidate_health and not is_proxy_compatible(candidate_health):
                continue
            ok, _ = start_proxy_and_wait(candidate_url, upstream_url)
            if ok:
                return "started", f"{prefix} Proxy started: {candidate_url}", candidate_url
        return "failed", f"{prefix} Startup failed, please manually stop old proxy and retry.", proxy_url

    ok, error = start_proxy_and_wait(proxy_url, upstream_url)
    if ok:
        return "started", f"Proxy started: {proxy_url}", proxy_url
    return "failed", error, proxy_url
