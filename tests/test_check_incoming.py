"""incoming 清理脚本：只删已归档的冗余原件。"""

import hashlib
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

import check_incoming  # noqa: E402


class CheckIncomingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.incoming = self.root / "incoming"
        self.archive = self.root / "data" / "reports" / "dan" / "images"
        self.incoming.mkdir(parents=True)
        self.archive.mkdir(parents=True)
        check_incoming.PROJECT_DIR = self.root
        check_incoming.INCOMING_DIR = self.incoming
        check_incoming.ARCHIVE_DIR = self.root / "data" / "reports"

    def tearDown(self):
        check_incoming.PROJECT_DIR = ROOT
        check_incoming.INCOMING_DIR = ROOT / "incoming"
        check_incoming.ARCHIVE_DIR = ROOT / "data" / "reports"
        self.temp.cleanup()

    def make(self, path: Path, content: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def run_cli(self, *extra: str) -> str:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            check_incoming.main(list(extra))
        return stdout.getvalue()

    def test_archived_file_is_detected_and_deleted(self):
        self.make(self.archive / "20260920_机构_项目_东东_原图01.jpeg", b"same-bytes")
        self.make(self.incoming / "扫描件" / "原件(1).jpeg", b"same-bytes")
        output = self.run_cli("--delete-archived")
        self.assertIn("[已归档]", output)
        self.assertIn("已删除 1 个已归档原件", output)
        self.assertFalse((self.incoming / "扫描件").exists())
        self.assertTrue((self.archive / "20260920_机构_项目_东东_原图01.jpeg").exists())

    def test_unarchived_file_is_never_deleted(self):
        pending = self.make(self.incoming / "新报告.jpeg", b"not-archived-yet")
        output = self.run_cli("--delete-archived")
        self.assertIn("[待导入]", output)
        self.assertIn("合计 1 个文件：已归档 0、待导入 1", output)
        self.assertTrue(pending.exists())

    def test_same_size_but_different_content_is_not_a_match(self):
        self.make(self.archive / "other.jpeg", b"aaaa")
        self.make(self.incoming / "原件.jpeg", b"bbbb")
        output = self.run_cli()
        self.assertIn("[待导入]", output)

    def test_missing_incoming_dir_is_fine(self):
        self.incoming.rmdir()
        self.assertIn("没有待处理文件", self.run_cli())

    def test_md5_helper_matches_hashlib(self):
        path = self.make(self.incoming / "x.jpeg", b"hello")
        self.assertEqual(check_incoming.md5(path), hashlib.md5(b"hello").hexdigest())


if __name__ == "__main__":
    unittest.main()
