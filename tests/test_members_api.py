import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database  # noqa: E402
from database import get_conn, init_db  # noqa: E402
from models import MemberCreate, MemberUpdate  # noqa: E402
from routers.members import create_member, get_member, list_members, update_member  # noqa: E402


class MembersApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp.name) / "health.db"
        init_db()

    def tearDown(self):
        self.temp.cleanup()

    def test_create_member_generates_safe_key_and_default_list_shows_active(self):
        member = create_member(MemberCreate(name="杨桦", species="human", role="本人"))
        self.assertRegex(member["key"], r"^member-[0-9a-f]{8}$")
        self.assertEqual(member["name"], "杨桦")
        self.assertIsNone(member.get("archived_at"))
        self.assertEqual([m["key"] for m in list_members()], [member["key"]])

    def test_create_other_pet_persists_custom_type_and_pet_sex(self):
        member = create_member(MemberCreate(
            name="团团",
            species="other",
            species_detail="兔",
            sex="妹妹",
        ))
        self.assertEqual(member["species_detail"], "兔")
        self.assertEqual(member["sex"], "妹妹")
        self.assertNotIn("chip_id", member)

    def test_member_avatar_is_served_from_private_avatar_directory(self):
        create_member(MemberCreate(key="avatar-user", name="头像用户", species="human"))
        avatar_dir = database.DB_PATH.parent / "avatars"
        avatar_dir.mkdir()
        (avatar_dir / "avatar-user.png").write_bytes(b"avatar")

        member = get_member("avatar-user")
        self.assertTrue(member["avatar_url"].startswith("/api/members/avatar-user/avatar?v="))

    def test_legacy_public_avatar_remains_available_through_authenticated_api(self):
        create_member(MemberCreate(key="legacy-user", name="旧头像用户", species="human"))
        legacy_dir = database.DB_PATH.parent / "public"
        legacy_dir.mkdir()
        (legacy_dir / "legacy-user.png").write_bytes(b"legacy avatar")

        member = get_member("legacy-user")
        self.assertTrue(member["avatar_url"].startswith("/api/members/legacy-user/avatar?v="))

    def test_duplicate_explicit_key_returns_409(self):
        create_member(MemberCreate(key="safe-key_1", name="小白", species="cat"))
        with self.assertRaises(HTTPException) as ctx:
            create_member(MemberCreate(key="safe-key_1", name="小黑", species="cat"))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("已存在", str(ctx.exception.detail))

    def test_invalid_key_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            create_member(MemberCreate(key="../bad", name="坏 key", species="human"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_archive_and_restore_filters_default_list(self):
        active = create_member(MemberCreate(key="active", name="仍在", species="human"))
        archived = create_member(MemberCreate(key="archived", name="归档", species="dog"))
        update_member(archived["key"], MemberUpdate(archived_at="2026-08-03 12:00:00"))

        self.assertEqual([m["key"] for m in list_members()], [active["key"]])
        all_keys = [m["key"] for m in list_members(include_archived=True)]
        self.assertEqual(all_keys, [active["key"], archived["key"]])

        restored = update_member(archived["key"], MemberUpdate(archived_at=None))
        self.assertIsNone(restored.get("archived_at"))
        self.assertEqual([m["key"] for m in list_members()], [active["key"], archived["key"]])

    def test_init_db_migrates_archived_at_for_existing_members_table(self):
        legacy_path = Path(self.temp.name) / "legacy.db"
        database.DB_PATH = legacy_path
        with get_conn(log_writes=False) as conn:
            conn.execute("""
                CREATE TABLE members (
                  key TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  full_name TEXT,
                  initial TEXT,
                  birth_date TEXT,
                  sex TEXT,
                  blood_type TEXT,
                  role TEXT,
                  species TEXT NOT NULL DEFAULT 'human',
                  sort_order INTEGER DEFAULT 0,
                  breed TEXT,
                  home_date TEXT,
                  chip_id TEXT,
                  doctor TEXT,
                  allergies TEXT DEFAULT '[]',
                  chronic TEXT DEFAULT '[]',
                  notes TEXT,
                  created_at TEXT DEFAULT (datetime('now','localtime')),
                  updated_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            conn.execute("INSERT INTO members (key, name) VALUES ('legacy', '旧成员')")
        init_db()
        with get_conn() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(members)").fetchall()}
            self.assertIn("archived_at", cols)
            self.assertIn("species_detail", cols)
            self.assertIsNone(conn.execute("SELECT archived_at FROM members WHERE key = 'legacy'").fetchone()["archived_at"])


if __name__ == "__main__":
    unittest.main()
