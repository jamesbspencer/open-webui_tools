#!/usr/bin/env python3
"""
Unit tests for install.py and skills repository parity.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import install

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestInstall(unittest.TestCase):

    def test_metadata_files_exist(self):
        """Verify all declared tools and skills exist on disk."""
        for tool in install.TOOLS_METADATA:
            path = REPO_ROOT / tool["file"]
            self.assertTrue(path.is_file(), f"Missing tool file: {path}")

        for skill in install.SKILLS_METADATA:
            path = REPO_ROOT / skill["file"]
            self.assertTrue(path.is_file(), f"Missing skill file: {path}")

    def test_skills_parity(self):
        """Verify that .agents/skills/ mirrors skills/ with exact content parity."""
        skills_dir = REPO_ROOT / "skills"
        agents_dir = REPO_ROOT / ".agents" / "skills"
        self.assertTrue(agents_dir.is_dir(), ".agents/skills directory missing")

        skills_files = list(skills_dir.glob("*/SKILL.md"))
        agents_files = list(agents_dir.glob("*/SKILL.md"))
        self.assertEqual(
            len(skills_files),
            len(agents_files),
            f"Mismatched skill count: {len(skills_files)} in skills/ vs {len(agents_files)} in .agents/skills/",
        )

        for skill_file in skills_files:
            rel_path = skill_file.relative_to(skills_dir)
            mirror_file = agents_dir / rel_path
            self.assertTrue(mirror_file.is_file(), f"Missing mirror in .agents/skills: {mirror_file}")
            self.assertEqual(
                skill_file.read_text(encoding="utf-8"),
                mirror_file.read_text(encoding="utf-8"),
                f"Content drift detected between {skill_file} and {mirror_file}",
            )

    def test_skills_frontmatter(self):
        """Verify all SKILL.md files have valid YAML frontmatter containing 'name' and 'description'."""
        for skill in install.SKILLS_METADATA:
            path = REPO_ROOT / skill["file"]
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("---\n"), f"{path} must start with YAML frontmatter '---'")
            parts = content.split("---", 2)
            self.assertGreaterEqual(len(parts), 3, f"{path} missing closing YAML frontmatter delimiter '---'")
            frontmatter = parts[1]
            self.assertIn("name:", frontmatter, f"{path} frontmatter missing 'name:'")
            self.assertIn("description:", frontmatter, f"{path} frontmatter missing 'description:'")

    @patch("urllib.request.urlopen")
    def test_deploy_item_create_flow(self, mock_urlopen):
        """Verify deployment creates a new item when GET /id/{id} returns 404."""
        # 1. Existence check returns 404
        check_err = urllib.error.HTTPError(
            url="http://test/api/v1/tools/id/openbao_client",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=io.BytesIO(b"Not Found"),
        )
        # 2. Create returns 200
        create_resp = MagicMock()
        create_resp.status = 200
        create_resp.read.return_value = b'{"success": true}'
        create_resp.__enter__.return_value = create_resp

        mock_urlopen.side_effect = [check_err, create_resp]

        tool_info = install.TOOLS_METADATA[0]
        ok = install.install_tool("http://test", "sk-fake-key", tool_info)
        self.assertTrue(ok)
        self.assertEqual(mock_urlopen.call_count, 2)
        # Verify second call was to /create
        called_req = mock_urlopen.call_args_list[1][0][0]
        self.assertIn("/api/v1/tools/create", called_req.full_url)
        payload = json.loads(called_req.data.decode("utf-8"))
        self.assertEqual(payload["id"], tool_info["id"])
        self.assertIn("description", payload)
        self.assertIn("description", payload["meta"])

    @patch("urllib.request.urlopen")
    def test_deploy_item_update_flow(self, mock_urlopen):
        """Verify deployment updates an existing item when GET /id/{id} returns 200."""
        # 1. Existence check returns 200
        check_resp = MagicMock()
        check_resp.status = 200
        check_resp.__enter__.return_value = check_resp
        # 2. Update returns 200
        update_resp = MagicMock()
        update_resp.status = 200
        update_resp.read.return_value = b'{"success": true}'
        update_resp.__enter__.return_value = update_resp

        mock_urlopen.side_effect = [check_resp, update_resp]

        skill_info = install.SKILLS_METADATA[0]
        ok = install.install_skill("http://test", "sk-fake-key", skill_info)
        self.assertTrue(ok)
        self.assertEqual(mock_urlopen.call_count, 2)
        called_req = mock_urlopen.call_args_list[1][0][0]
        self.assertIn(f"/api/v1/skills/id/{skill_info['id']}/update", called_req.full_url)

    @patch("urllib.request.urlopen")
    def test_deploy_item_auth_failure(self, mock_urlopen):
        """Verify HTTP 401/403 aborts without creating."""
        auth_err = urllib.error.HTTPError(
            url="http://test/api/v1/tools/id/openbao_client",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(b"Unauthorized"),
        )
        mock_urlopen.side_effect = auth_err

        tool_info = install.TOOLS_METADATA[0]
        ok = install.install_tool("http://test", "sk-invalid", tool_info)
        self.assertFalse(ok)
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("urllib.request.urlopen")
    def test_deploy_item_server_error_aborts(self, mock_urlopen):
        """Verify non-404 HTTP errors (e.g. 502) fail fast rather than trying create."""
        server_err = urllib.error.HTTPError(
            url="http://test/api/v1/tools/id/openbao_client",
            code=502,
            msg="Bad Gateway",
            hdrs={},
            fp=io.BytesIO(b"Bad Gateway"),
        )
        mock_urlopen.side_effect = server_err

        tool_info = install.TOOLS_METADATA[0]
        ok = install.install_tool("http://test", "sk-fake", tool_info)
        self.assertFalse(ok)
        self.assertEqual(mock_urlopen.call_count, 1)

    def test_cli_parser_mutually_exclusive(self):
        """Verify that passing --tools-only and --skills-only together raises SystemExit."""
        parser = install.build_parser()
        with self.assertRaises(SystemExit):
            with patch("sys.stderr", io.StringIO()):
                parser.parse_args(["--tools-only", "--skills-only"])

    def test_load_dotenv(self):
        """Verify load_dotenv extracts API key and URL."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_env = Path(tmp_dir) / ".env"
            tmp_env.write_text(
                "# Sample comment\n"
                "open_webui_api=\"sk-env-test-key\"\n"
                "open_webui_url='https://ai.example.internal'\n"
            )
            with patch.object(install, "REPO_ROOT", Path(tmp_dir)):
                with patch.dict(os.environ, {}, clear=True):
                    install.load_dotenv()
                    self.assertEqual(os.environ.get("OPENWEBUI_API_KEY"), "sk-env-test-key")
                    self.assertEqual(os.environ.get("OPENWEBUI_URL"), "https://ai.example.internal")


if __name__ == "__main__":
    unittest.main()
