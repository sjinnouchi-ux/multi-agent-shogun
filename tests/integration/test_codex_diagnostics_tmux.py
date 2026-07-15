from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "codex_diagnostics.py"


def load_module():
    spec = importlib.util.spec_from_file_location("codex_diagnostics_integration", SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError("diagnostics module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SocketRunner:
    def __init__(self, module, socket_name: str) -> None:
        self.module = module
        self.socket_name = socket_name
        self.runner = module.CommandRunner()

    def __call__(self, argv):
        if argv[0] == "/usr/bin/tmux":
            argv = (argv[0], "-L", self.socket_name, *argv[1:])
        return self.runner(argv)


class UniqueTmuxSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.socket_name = os.environ["SHOGUN_DIAGNOSTIC_TEST_SOCKET"]
        self.fixture_dir = tempfile.TemporaryDirectory()
        self.fixture = Path(self.fixture_dir.name) / "bounded-pane-fixture"
        self.fixture.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' harmless-pane-sentinel\n"
            "exec /usr/bin/sleep 5\n",
            encoding="utf-8",
        )
        self.fixture.chmod(0o700)

    def tmux(self, *args: str) -> None:
        subprocess.run(
            ("/usr/bin/tmux", "-L", self.socket_name, *args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=2,
        )

    def tearDown(self) -> None:
        deadline = time.monotonic() + 7.0
        try:
            while time.monotonic() < deadline:
                result = subprocess.run(
                    ("/usr/bin/tmux", "-L", self.socket_name, "has-session"),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=1,
                )
                if result.returncode != 0:
                    return
                time.sleep(0.05)
            self.fail("isolated tmux server did not exit after bounded fixtures")
        finally:
            self.fixture_dir.cleanup()

    def test_fixed_sessions_counts_and_pane_secrecy(self) -> None:
        self.tmux("new-session", "-d", "-s", "shogun", str(self.fixture))
        self.tmux("set-option", "-g", "exit-empty", "on")
        self.tmux("set-option", "-p", "-t", "shogun:0.0", "@agent_id", "shogun")
        self.tmux("set-option", "-p", "-t", "shogun:0.0", "@agent_cli", "claude")
        self.tmux("new-session", "-d", "-s", "multiagent", str(self.fixture))
        self.tmux("set-option", "-p", "-t", "multiagent:0.0", "@agent_id", "ashigaru1")
        self.tmux("set-option", "-p", "-t", "multiagent:0.0", "@agent_cli", "codex")

        value = self.module.collect_tmux(SocketRunner(self.module, self.socket_name))
        self.assertEqual([item["state"] for item in value.sessions], ["present", "present"])
        self.assertEqual([item["pane_count"] for item in value.sessions], [1, 1])
        self.assertEqual(value.observations["shogun"].pane_state, "alive")
        self.assertEqual(value.observations["ashigaru1"].cli, "codex")
        self.assertNotIn("harmless-pane-sentinel", repr(value))


if __name__ == "__main__":
    unittest.main()
