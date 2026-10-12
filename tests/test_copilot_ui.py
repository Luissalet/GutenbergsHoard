"""Assistant-context helpers: node tests for the shipping app.js, and the static wiring."""
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from gutenberg_hoard.app import app as api

ROOT = Path(__file__).resolve().parents[1]


def test_copilot_context_node_tests_pass():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for the UI context tests")
    result = subprocess.run([node, "--test", "tests/copilot-context.test.mjs"], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_context_script_is_served_and_loaded_before_the_app():
    client = TestClient(api, base_url='http://127.0.0.1')
    script = client.get("/static/copilot-context.js")
    assert script.status_code == 200 and "gutenbergCopilotContext" in script.text
    page = client.get("/").text
    assert page.index("/static/copilot-context.js") < page.index("/static/app.js")
