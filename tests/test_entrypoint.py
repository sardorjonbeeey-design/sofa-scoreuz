"""Startup correctness: the documented commands start the real app."""

import ast
import importlib
import os
import subprocess
import sys
from pathlib import Path

import aiohttp
import pytest

ROOT = Path(__file__).resolve().parent.parent

# Starting the real application means importing aiogram, whose Telegram
# models take ~3 s to build on an idle machine but 25-45+ s on a heavily
# loaded one or with cold bytecode caches (measured). The application
# itself fails fast: after the imports it exits in milliseconds. The
# limit therefore only has to separate "slow machine" from "hung".
START_TIMEOUT_SECONDS = int(
    os.getenv("START_COMMAND_TEST_TIMEOUT", "300")
)


def test_root_main_is_valid_python_with_a_main_guard():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)  # raises on invalid syntax

    # Regression: the file used to contain only the bare word "main",
    # which crashed with NameError.
    assert source.strip() != "main"
    assert any(isinstance(node, ast.If) for node in tree.body)


def test_importing_the_entry_point_has_no_side_effects():
    module = importlib.import_module("main")
    app_main = importlib.import_module("app.main")

    assert module.run is app_main.run
    assert callable(module.run)


def test_package_is_executable_with_dash_m():
    assert (ROOT / "app" / "__main__.py").exists()
    assert (ROOT / "app" / "__init__.py").exists()


def _run(*command: str) -> subprocess.CompletedProcess:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("BOT_", "API_FOOTBALL", "DATABASE", "REQUIRE_")
        )
    }
    # No token: the real application must start, bind its port,
    # initialise storage and then stop with a clear message.
    env.update(BOT_TOKEN="", PORT="0", DATABASE_URL="", LOG_LEVEL="INFO")

    try:
        return subprocess.run(
            [sys.executable, *command],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=START_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        # A real hang must be distinguishable from a slow machine.
        tail = (exc.stderr or b"")
        tail = tail.decode(errors="replace") if isinstance(tail, bytes) else tail
        pytest.fail(
            f"'python {' '.join(command)}' did not exit within "
            f"{START_TIMEOUT_SECONDS}s. Last output:\n{tail[-1500:]}"
        )


@pytest.mark.parametrize(
    "command",
    [("main.py",), ("-m", "app.main"), ("-m", "app")],
    ids=["python main.py", "python -m app.main", "python -m app"],
)
def test_every_documented_start_command_reaches_the_real_application(
    command,
):
    result = _run(*command)

    # The real app ran: it got as far as validating configuration.
    assert "BOT_TOKEN is not configured" in result.stderr
    assert "NameError" not in result.stderr
    assert result.returncode != 0
    # And it announced the non-persistent mode (no DATABASE_URL).
    assert "DATABASE_URL is not set" in result.stderr


async def test_health_endpoints_respond():
    from app.main import start_web_server

    runner = await start_web_server(port=0)

    try:
        port = runner.addresses[0][1]

        async with aiohttp.ClientSession() as client:
            for path in ("/", "/health"):
                async with client.get(
                    f"http://127.0.0.1:{port}{path}"
                ) as response:
                    assert response.status == 200
                    assert "running" in await response.text()
    finally:
        await runner.cleanup()


def test_a_hung_start_command_is_reported_as_a_clear_failure(monkeypatch):
    # Slow machines get a generous limit, but a command that never exits
    # must still fail loudly and say why, not hang the suite.
    monkeypatch.setattr(
        sys.modules[__name__], "START_TIMEOUT_SECONDS", 1
    )

    with pytest.raises(pytest.fail.Exception, match="did not exit within 1s"):
        _run("-c", "import time; time.sleep(30)")
