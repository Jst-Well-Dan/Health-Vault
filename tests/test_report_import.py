import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import fitz  # noqa: E402
import database  # noqa: E402
from database import get_conn, init_db  # noqa: E402
from routers.imports import ReportImportCommit, ReportLab, ReportVisit, commit_report, dry_run_report, stage_report  # noqa: E402


class ReportImportFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name) / "data"
        database.DB_PATH = self.data_dir / "health.db"
        init_db()
        with get_conn() as conn:
            conn.execute("INSERT INTO members (key, name) VALUES ('yanghua', '杨桦')")

    def tearDown(self):
        self.temp.cleanup()

    def _synthetic_pdf(self):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Synthetic report fixture: no personal health data.")
        content = document.tobytes()
        document.close()
        return content

    @staticmethod
    def _run_mineru(_command, **_kwargs):
        class Result:
            returncode = 0
            stdout = "# Synthetic MinerU Markdown\n\nNo personal health data.\n"

        return Result()

    def test_synthetic_one_page_pdf_is_staged_archived_and_imported(self):
        mineru_env = {"MINERU_TOKEN": "synthetic-managed-token"}
        with patch("routers.imports.command_path", return_value="/test/mineru-open-api"), patch("routers.imports.extraction_env", return_value=mineru_env), patch("routers.imports.subprocess.run", side_effect=self._run_mineru) as run_mineru:
            staged = stage_report("synthetic-report.pdf", self._synthetic_pdf(), "application/pdf")
        command = run_mineru.call_args.args[0]
        self.assertIs(run_mineru.call_args.kwargs["env"], mineru_env)
        self.assertEqual(command[:2], ["/test/mineru-open-api", "flash-extract"])
        self.assertIn("--timeout", command)
        self.assertEqual(staged["page_count"], 1)
        self.assertEqual(staged["images"], [])
        self.assertIn("Synthetic MinerU Markdown", staged["text"])
        staging_dir = self.data_dir / "imports" / ".staging" / staged["id"]
        self.assertTrue((staging_dir / "mineru.md").is_file())

        # This proposal represents the reviewed result returned by a configured vision model.
        proposal = ReportImportCommit(
            source_id=staged["id"],
            member_key="yanghua",
            visit=ReportVisit(
                date="2026-06-16",
                type="体检",
                hospital="首都医科大学附属北京安贞医院",
                department="超声医学科",
                chief_complaint="甲状腺及颈部淋巴结超声",
                severity="一般",
                diagnosis=[],
                notes="测试导入：请以原始报告为准。",
                note_full="### 医生诊断\n报告未列出明确诊断。\n\n### 诊疗意见\n测试导入。\n\n### 治疗方案说明\n报告中未提供具体用药或治疗方案。",
            ),
            labs=[ReportLab(panel="超声检查", test_name="甲状腺超声结论", value="详见原始报告", status="unknown")],
            attachment_title="甲状腺及颈部淋巴结超声",
        )
        dry_run = dry_run_report(proposal)
        self.assertTrue(dry_run["ok"])
        self.assertEqual(dry_run["lab_count"], 1)
        result = commit_report(proposal)

        self.assertEqual(result["lab_count"], 1)
        self.assertTrue(Path(result["database_path"]).is_file())
        self.assertTrue(Path(result["backup_path"]).is_file())
        self.assertTrue((self.data_dir.parent / result["source_file"]).is_file())
        self.assertTrue((self.data_dir.parent / result["mineru_markdown_file"]).is_file())
        self.assertTrue((self.data_dir.parent / result["markdown_file"]).is_file())
        self.assertFalse((self.data_dir / "imports" / ".staging" / staged["id"]).exists())

        with get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM lab_results").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0], 1)

    def test_missing_mineru_cleans_private_staging_area(self):
        with patch("routers.imports.command_path", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                stage_report("synthetic-report.png", b"not a real image", "image/png")

        self.assertEqual(raised.exception.status_code, 503)
        staging_root = self.data_dir / "imports" / ".staging"
        self.assertFalse(staging_root.exists() and any(staging_root.iterdir()))


if __name__ == "__main__":
    unittest.main()
