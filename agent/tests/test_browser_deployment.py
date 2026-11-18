"""Regression checks for the browser containers' isolation configuration."""

from pathlib import Path
import json
import shutil
import subprocess

import pytest
import yaml


def test_compose_sets_32k_ollama_context_and_browser_input_budget() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())

    assert (
        compose["services"]["ollama"]["environment"]["OLLAMA_CONTEXT_LENGTH"]
        == "${OLLAMA_CONTEXT_LENGTH:-32768}"
    )
    assert (
        compose["services"]["browser-research"]["environment"]["BROWSER_AGENT_MAX_INPUT_TOKENS"]
        == "${BROWSER_AGENT_MAX_INPUT_TOKENS:-32000}"
    )
    assert (
        compose["services"]["agent"]["environment"]["BROWSER_AGENT_SERVICE_TIMEOUT_SECONDS"]
        == "${BROWSER_AGENT_SERVICE_TIMEOUT_SECONDS:-320}"
    )
    assert (
        compose["services"]["browser-research"]["environment"]["BROWSER_AGENT_TASK_TIMEOUT_SECONDS"]
        == "${BROWSER_AGENT_TASK_TIMEOUT_SECONDS:-300}"
    )
    assert (
        compose["services"]["browser-research"]["environment"]["BROWSER_AGENT_MODEL"]
        == "${BROWSER_AGENT_MODEL:-hf.co/Mungert/UI-TARS-1.5-7B-GGUF:Q4_K_M}"
    )
    assert (
        compose["services"]["browser-research"]["environment"]["BROWSER_AGENT_CONTEXT_LENGTH"]
        == "${BROWSER_AGENT_CONTEXT_LENGTH:-32768}"
    )
    assert (
        compose["services"]["browser-research"]["depends_on"]["ollama-models"]["condition"]
        == "service_completed_successfully"
    )
    assert "ollama pull" in compose["services"]["ollama-models"]["command"][0]
    assert (
        compose["services"]["browser-worker"]["environment"]["BROWSER_WORKER_MAX_TASK_SECONDS"]
        == "${BROWSER_WORKER_MAX_TASK_SECONDS:-300}"
    )
    assert (
        compose["services"]["browser-worker"]["environment"]["BROWSER_WORKER_ACTION_LIMIT"]
        == "${BROWSER_WORKER_ACTION_LIMIT:-80}"
    )


def test_browser_worker_has_no_docker_network_or_application_secrets() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    worker = compose["services"]["browser-worker"]
    assert worker["network_mode"] == "none"
    assert "ports" not in worker
    assert worker["read_only"] is True
    assert "ALL" in worker["cap_drop"]
    assert worker["pids_limit"] == 256
    assert not {"DATABASE_URL", "REDIS_URL", "BROWSER_AGENT_OLLAMA_URL"} & set(
        worker["environment"]
    )
    assert not any("docker.sock" in mount for mount in worker["volumes"])
    assert "no-new-privileges:true" in worker["security_opt"]
    assert "seccomp=./deploy/chromium-seccomp.json" in worker["security_opt"]
    assert "browser_profile:/browser-profile" in worker["volumes"]
    assert worker["environment"]["BROWSER_PROFILE_DIR"] == "/browser-profile"
    seccomp = json.loads((root / "deploy/chromium-seccomp.json").read_text())
    allowed = {
        name
        for rule in seccomp["syscalls"]
        if rule["action"] == "SCMP_ACT_ALLOW" and not rule.get("includes")
        for name in rule["names"]
    }
    assert {"clone", "chroot", "setns", "unshare"} <= allowed


def test_browser_research_serializes_tasks_for_the_shared_chrome_profile() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    research = compose["services"]["browser-research"]
    assert research["environment"]["BROWSER_AGENT_MAX_CONCURRENT_TASKS"] == (
        "${BROWSER_AGENT_MAX_CONCURRENT_TASKS:-1}"
    )
    assert (
        "timeout_seconds: float = 300"
        in (Path(__file__).resolve().parents[1] / "src/browser_agt/agent.py").read_text()
    )
    assert (
        "recursion_limit: int = 80"
        in (Path(__file__).resolve().parents[1] / "src/browser_agt/agent.py").read_text()
    )
    dockerfile = (root / "docker/browser-worker/Dockerfile").read_text()
    assert "google-chrome-stable" in dockerfile
    assert "xvfb-run" in dockerfile


def test_proxy_only_has_egress_network_and_no_public_listener() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    proxy = compose["services"]["browser-proxy"]
    assert proxy["networks"] == ["proxy_egress"]
    assert "ports" not in proxy
    assert proxy["read_only"] is True
    assert "ALL" in proxy["cap_drop"]
    assert "BROWSER_PROXY_DENY_HOSTS" in proxy["environment"]


@pytest.mark.integration
def test_running_browser_worker_has_no_network_and_proxy_blocks_loopback() -> None:
    """Inspect a user-started stack; the probe never contacts a public API."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is not installed")
    try:
        containers = subprocess.run(
            [
                docker,
                "ps",
                "--quiet",
                "--filter",
                "label=com.docker.compose.service=browser-worker",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.splitlines()
    except (subprocess.SubprocessError, OSError):
        pytest.skip("Docker is unavailable")
    if len(containers) != 1:
        pytest.skip("Start exactly one browser-worker container to run this check")
    worker = containers[0]
    network = subprocess.run(
        [docker, "inspect", "--format", "{{.HostConfig.NetworkMode}}", worker],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    assert network == "none"

    probe = (
        "import socket; s=socket.create_connection(('127.0.0.1',18882),timeout=3); "
        "s.sendall(b'CONNECT 127.0.0.1:443 HTTP/1.1\\r\\nHost: 127.0.0.1:443\\r\\n\\r\\n'); "
        "print(s.recv(256).decode('ascii', errors='replace'))"
    )
    response = subprocess.run(
        [docker, "exec", worker, "python", "-c", probe],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    assert response.startswith(("HTTP/1.1 400", "HTTP/1.1 403"))

    browser_probe = """\
import asyncio
from browser_agt.remote import RemoteBrowserRuntime

async def main():
    async with RemoteBrowserRuntime() as runtime:
        job = await runtime.create_job()
        page = await job.observe()
        assert page.url == 'about:blank'
        await job.close()

asyncio.run(main())
"""
    subprocess.run(
        [docker, "exec", worker, ".venv/bin/python", "-c", browser_probe],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
