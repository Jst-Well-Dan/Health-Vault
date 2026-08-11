import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database  # noqa: E402
from database import get_conn, init_db  # noqa: E402
from models import AttachmentRecordCreate, LabRecordCreate, VisitCreate, VisitUpdate  # noqa: E402
from routers.agent import ChangeCreate, MessageCreate, clear_messages, create_message, get_record, list_messages, log_change, undo_last_change  # noqa: E402
from routers.attachments import create_attachment  # noqa: E402
from routers.labs import create_lab  # noqa: E402
from routers.visits import create_visit, update_visit  # noqa: E402


class AgentWriteFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp.name) / "health.db"
        init_db()
        with get_conn() as conn:
            conn.execute("INSERT INTO members (key, name) VALUES ('self', '本人')")

    def tearDown(self):
        self.temp.cleanup()

    def test_write_log_and_undo(self):
        visit = create_visit(VisitCreate(member_key="self", date="2026-08-03", diagnosis=["年度体检"]))
        before = get_record("visits", str(visit["id"]))
        updated = update_visit(visit["id"], VisitUpdate(notes="状态良好"))
        log_change(ChangeCreate(
            tool="update_visit", table_name="visits", row_id=visit["id"], action="update",
            before=before, after=updated,
        ))
        self.assertEqual(get_record("visits", str(visit["id"]))["notes"], "状态良好")
        undo_last_change()
        self.assertIsNone(get_record("visits", str(visit["id"]))["notes"])

        lab = create_lab(LabRecordCreate(
            member_key="self", visit_id=visit["id"], date="2026-08-03",
            panel="血常规", test_name="血红蛋白", value="145", unit="g/L",
        ))
        self.assertEqual(lab["member_key"], "self")
        attachment = create_attachment(AttachmentRecordCreate(
            member_key="self", visit_id=visit["id"], date="2026-08-03", title="体检报告",
        ))
        self.assertEqual(attachment["visit_id"], visit["id"])

    def test_clear_messages_only_affects_target_session(self):
        create_message(MessageCreate(session_id="default", role="user", content="爸爸最近在吃什么药？"))
        create_message(MessageCreate(session_id="default", role="assistant", content="正在查询…"))
        create_message(MessageCreate(session_id="other", role="user", content="不应被清空"))

        clear_messages("default")

        self.assertEqual(list_messages("default"), [])
        self.assertEqual(len(list_messages("other")), 1)


if __name__ == "__main__":
    unittest.main()
