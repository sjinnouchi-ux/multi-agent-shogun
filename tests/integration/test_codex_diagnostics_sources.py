from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.unit.test_codex_diagnostics import load_module


class CanonicalInboxGeometryTests(unittest.TestCase):
    def test_isolated_canonical_link_reports_all_inboxes_present(self) -> None:
        m = load_module()
        with (
            tempfile.TemporaryDirectory() as repo_raw,
            tempfile.TemporaryDirectory() as target_raw,
        ):
            repo = Path(repo_raw)
            anchor = Path(target_raw)
            os.chmod(anchor, 0o700)
            (repo / "queue").mkdir(mode=0o700)
            (anchor / "fixed" / "inbox").mkdir(parents=True, mode=0o700)
            os.chmod(anchor / "fixed", 0o700)
            os.chmod(anchor / "fixed" / "inbox", 0o700)
            (repo / "queue" / "inbox").symlink_to(m.INBOX_LINK_TARGET)
            for agent in m.AGENT_IDS:
                (anchor / "fixed" / "inbox" / f"{agent}.yaml").write_text(
                    "messages:\n", encoding="utf-8"
                )

            repo_fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
            anchor_fd = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY)
            try:
                opener = lambda root_fd: m.open_inbox_root(
                    root_fd,
                    traversal_root_fd=anchor_fd,
                    target_parts=("fixed", "inbox"),
                )
                collection = m.collect_runtime_sources(
                    repo_fd,
                    frozenset(m.AGENT_IDS),
                    inbox_opener=opener,
                )
            finally:
                os.close(anchor_fd)
                os.close(repo_fd)

        for agent in m.AGENT_IDS:
            with self.subTest(agent=agent):
                value = collection.agent_sources[agent]["inbox"]
                self.assertEqual(
                    tuple(value),
                    ("applicability", "state", "modified_at", "size_class"),
                )
                self.assertEqual(value["state"], "present")
        inbox_rejections = [
            issue
            for issue in collection.errors + collection.warnings
            if issue.code == "source_rejected" and issue.component == "source"
        ]
        self.assertEqual(inbox_rejections, [])


if __name__ == "__main__":
    unittest.main()
