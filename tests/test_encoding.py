"""Regression coverage for builds and exports under non-UTF-8 locales.

Run with -X warn_default_encoding -W error::EncodingWarning to also detect
implicit text encodings on machines whose default encoding is UTF-8.
"""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from sooc_vs_edited.cli import _load_project, main


class EncodingTests(unittest.TestCase):
    def test_build_and_load_unicode_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sooc = root / "直出"
            edited = root / "修图"
            out = root / "对比"
            export = root / "精选"
            for directory in (sooc, edited):
                directory.mkdir()
                Image.new("RGB", (32, 24), "red").save(directory / "P1000001.jpg")
            title = "旅行 📷 <精选>"

            with contextlib.redirect_stdout(io.StringIO()):
                result = main([
                    "build", "--sooc", str(sooc), "--edited", str(edited),
                    "--out", str(out), "--export-to", str(export),
                    "--title", title, "--no-align", "--no-serve",
                ])

            self.assertEqual(result, 0)
            project = _load_project(out)
            self.assertEqual(project["title"], title)
            self.assertEqual(project["sooc_dir"], str(sooc))
            self.assertEqual(project["export_dir"], str(export))
            self.assertEqual(project["pairs"], ["P1000001"])
            html = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("旅行 📷 &lt;精选&gt;", html)
            self.assertIn(json.dumps(title, ensure_ascii=False), html)
            self.assertTrue((out / "img" / "sooc" / "P1000001.jpg").is_file())

    def test_export_reads_utf8_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = {"title": "旅行 📷", "export_dir": str(root / "精选")}
            (root / "project.json").write_text(
                json.dumps(project, ensure_ascii=False), encoding="utf-8"
            )
            choices = {"照片📷": "sooc"}
            choices_file = root / "choices.json"
            choices_file.write_text(
                json.dumps({"choices": choices}, ensure_ascii=False), encoding="utf-8"
            )
            with patch("sooc_vs_edited.server.do_export", return_value={}) as export:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = main(["export", str(root), str(choices_file)])

            self.assertEqual(result, 0)
            export.assert_called_once_with(
                project, choices, mirror=True, with_raw=False, match_geometry=True
            )


if __name__ == "__main__":
    unittest.main()
