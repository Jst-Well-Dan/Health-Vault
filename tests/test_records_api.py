import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database  # noqa: E402
from database import get_conn, init_db  # noqa: E402
from models import LabRecordCreate, LabUpdate, VisitCreate, VisitUpdate  # noqa: E402
from routers.labs import create_lab, delete_lab, update_lab  # noqa: E402
from routers.visits import create_visit, delete_visit, update_visit  # noqa: E402


class RecordsApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp.name) / "health.db"
        init_db()
        with get_conn() as conn:
            conn.execute("INSERT INTO members (key, name, species) VALUES ('self', '本人', 'human')")
            conn.execute("INSERT INTO members (key, name, species) VALUES ('pet', '小猫', 'cat')")

    def tearDown(self):
        self.temp.cleanup()

    def test_create_visit_normal_path(self):
        visit = create_visit(VisitCreate(
            member_key="self",
            date="2026-08-03",
            type="就医",
            hospital="社区医院",
            department="内科",
            doctor="王医生",
            chief_complaint="咳嗽复诊",
            severity="轻微",
            diagnosis=["上呼吸道感染"],
            notes="遵医嘱复查",
            note_full="完整门诊记录",
        ))

        self.assertEqual(visit["member_key"], "self")
        self.assertEqual(visit["type"], "就医")
        self.assertEqual(visit["diagnosis"], ["上呼吸道感染"])
        self.assertIsInstance(visit["id"], int)

    def test_update_visit_normal_path(self):
        visit = create_visit(VisitCreate(member_key="self", date="2026-08-03", type="就医"))
        updated = update_visit(visit["id"], VisitUpdate(
            date="2026-08-04",
            type="体检",
            hospital="体检中心",
            department="全科",
            doctor="李医生",
            chief_complaint="年度体检",
            severity="一般",
            diagnosis=["未见明显异常"],
            notes="人工更正",
            note_full="完整体检记录",
        ))

        self.assertEqual(updated["id"], visit["id"])
        self.assertEqual(updated["date"], "2026-08-04")
        self.assertEqual(updated["type"], "体检")
        self.assertEqual(updated["diagnosis"], ["未见明显异常"])
        self.assertEqual(updated["note_full"], "完整体检记录")

    def test_create_visit_rejects_missing_member(self):
        with self.assertRaises(HTTPException) as ctx:
            create_visit(VisitCreate(member_key="missing", date="2026-08-03"))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("成员不存在", str(ctx.exception.detail))

    def test_create_lab_normal_path_with_visit(self):
        visit = create_visit(VisitCreate(member_key="self", date="2026-08-03", type="体检"))
        lab = create_lab(LabRecordCreate(
            member_key="self",
            visit_id=visit["id"],
            date="2026-08-03",
            panel="血常规",
            test_name="血红蛋白",
            value="145",
            unit="g/L",
            ref_low="130",
            ref_high="175",
            status="normal",
        ))

        self.assertEqual(lab["member_key"], "self")
        self.assertEqual(lab["visit_id"], visit["id"])
        self.assertEqual(lab["test_name"], "血红蛋白")

    def test_update_lab_normal_path(self):
        visit = create_visit(VisitCreate(member_key="self", date="2026-08-03", type="体检"))
        lab = create_lab(LabRecordCreate(
            member_key="self", visit_id=visit["id"], date="2026-08-03",
            panel="血常规", test_name="血红蛋白", value="145",
        ))
        updated = update_lab(lab["id"], LabUpdate(
            date="2026-08-04",
            panel="生化",
            test_name="总胆固醇",
            value="4.8",
            unit="mmol/L",
            ref_low="0",
            ref_high="5.2",
            status="normal",
            source_file="manual",
        ))

        self.assertEqual(updated["id"], lab["id"])
        self.assertEqual(updated["visit_id"], visit["id"])
        self.assertEqual(updated["date"], "2026-08-04")
        self.assertEqual(updated["test_name"], "总胆固醇")
        self.assertEqual(updated["source_file"], "manual")

    def test_update_lab_rejects_cross_member_visit_link(self):
        own_visit = create_visit(VisitCreate(member_key="self", date="2026-08-03", type="体检"))
        other_visit = create_visit(VisitCreate(member_key="pet", date="2026-08-03", type="就医"))
        lab = create_lab(LabRecordCreate(
            member_key="self", visit_id=own_visit["id"], date="2026-08-03",
            panel="血常规", test_name="血红蛋白", value="145",
        ))

        with self.assertRaises(HTTPException) as ctx:
            update_lab(lab["id"], LabUpdate(visit_id=other_visit["id"]))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("不属于当前成员", str(ctx.exception.detail))

    def test_delete_lab_success_only_removes_lab_row(self):
        visit = create_visit(VisitCreate(member_key="self", date="2026-08-03", type="体检"))
        lab = create_lab(LabRecordCreate(
            member_key="self", visit_id=visit["id"], date="2026-08-03",
            panel="血常规", test_name="血红蛋白", value="145",
        ))

        result = delete_lab(lab["id"])

        self.assertEqual(result, {"ok": True, "id": lab["id"]})
        with get_conn() as conn:
            self.assertIsNone(conn.execute("SELECT id FROM lab_results WHERE id = ?", (lab["id"],)).fetchone())
            self.assertIsNotNone(conn.execute("SELECT id FROM visits WHERE id = ?", (visit["id"],)).fetchone())

    def test_delete_visit_with_dependencies_returns_409_and_keeps_data(self):
        visit = create_visit(VisitCreate(member_key="self", date="2026-08-03", type="体检"))
        lab = create_lab(LabRecordCreate(
            member_key="self", visit_id=visit["id"], date="2026-08-03",
            panel="血常规", test_name="血红蛋白", value="145",
        ))
        with get_conn() as conn:
            med_cur = conn.execute(
                "INSERT INTO meds (member_key, visit_id, name) VALUES (?, ?, ?)",
                ("self", visit["id"], "测试用药"),
            )
            attachment_cur = conn.execute(
                """
                INSERT INTO attachments (member_key, visit_id, date, title)
                VALUES (?, ?, ?, ?)
                """,
                ("self", visit["id"], "2026-08-03", "附件"),
            )
            med_id = med_cur.lastrowid
            attachment_id = attachment_cur.lastrowid

        with self.assertRaises(HTTPException) as ctx:
            delete_visit(visit["id"])

        self.assertEqual(ctx.exception.status_code, 409)
        detail = str(ctx.exception.detail)
        self.assertIn("就诊记录仍关联", detail)
        self.assertIn("1 项化验", detail)
        self.assertIn("1 项用药", detail)
        self.assertIn("1 项附件", detail)
        self.assertIn("需先解除关联或分别处理", detail)
        with get_conn() as conn:
            self.assertIsNotNone(conn.execute("SELECT id FROM visits WHERE id = ?", (visit["id"],)).fetchone())
            self.assertIsNotNone(conn.execute("SELECT id FROM lab_results WHERE id = ?", (lab["id"],)).fetchone())
            self.assertIsNotNone(conn.execute("SELECT id FROM meds WHERE id = ?", (med_id,)).fetchone())
            self.assertIsNotNone(conn.execute("SELECT id FROM attachments WHERE id = ?", (attachment_id,)).fetchone())

    def test_delete_visit_without_dependencies_success(self):
        visit = create_visit(VisitCreate(member_key="self", date="2026-08-03", type="就医"))

        result = delete_visit(visit["id"])

        self.assertEqual(result, {"ok": True, "id": visit["id"]})
        with get_conn() as conn:
            self.assertIsNone(conn.execute("SELECT id FROM visits WHERE id = ?", (visit["id"],)).fetchone())

    def test_create_lab_rejects_missing_member_and_bad_visit_link(self):
        with self.assertRaises(HTTPException) as missing_member:
            create_lab(LabRecordCreate(member_key="missing", date="2026-08-03", panel="血常规", test_name="血红蛋白"))
        self.assertEqual(missing_member.exception.status_code, 404)

        with self.assertRaises(HTTPException) as missing_visit:
            create_lab(LabRecordCreate(member_key="self", visit_id=999, date="2026-08-03", panel="血常规", test_name="血红蛋白"))
        self.assertEqual(missing_visit.exception.status_code, 404)
        self.assertIn("关联就诊记录不存在", str(missing_visit.exception.detail))

        pet_visit = create_visit(VisitCreate(member_key="pet", date="2026-08-03", type="就医"))
        with self.assertRaises(HTTPException) as mismatch:
            create_lab(LabRecordCreate(member_key="self", visit_id=pet_visit["id"], date="2026-08-03", panel="血常规", test_name="血红蛋白"))
        self.assertEqual(mismatch.exception.status_code, 422)
        self.assertIn("不属于当前成员", str(mismatch.exception.detail))


if __name__ == "__main__":
    unittest.main()
