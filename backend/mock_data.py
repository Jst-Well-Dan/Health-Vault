import json
from pathlib import Path
from typing import Any

from database import REPO_ROOT, get_conn, init_db


MOCK_ATTACHMENT_DIR = REPO_ROOT / "tests" / "fixtures" / "attachments"

MEMBERS = [
    {
        "key": "demo-self",
        "name": "大咪",
        "full_name": "大咪",
        "initial": "大",
        "birth_date": "1992-06-18",
        "sex": "女",
        "blood_type": "O",
        "role": "本人",
        "species": "human",
        "sort_order": 10,
        "breed": None,
        "home_date": None,
        "chip_id": None,
        "doctor": "社区卫生服务中心",
        "allergies": ["青霉素"],
        "chronic": ["过敏性鼻炎"],
        "notes": "模拟成员，用于公开演示；所有记录均为虚构。",
    },
    {
        "key": "demo-parent",
        "name": "大咪爸",
        "full_name": "大咪爸",
        "initial": "爸",
        "birth_date": "1963-11-03",
        "sex": "男",
        "blood_type": "A",
        "role": "父亲",
        "species": "human",
        "sort_order": 20,
        "breed": None,
        "home_date": None,
        "chip_id": None,
        "doctor": "心内科随访",
        "allergies": [],
        "chronic": ["高血压", "血脂偏高"],
        "notes": "模拟慢病随访档案，用于展示用药、提醒和检验趋势。",
    },
    {
        "key": "demo-cat",
        "name": "哈基咪",
        "full_name": "哈基咪",
        "initial": "哈",
        "birth_date": "2021-04-12",
        "sex": "妹妹",
        "blood_type": None,
        "role": "猫咪",
        "species": "cat",
        "sort_order": 30,
        "breed": "英国短毛猫",
        "home_date": "2021-07-20",
        "chip_id": "156100000000001",
        "doctor": "城市动物医院",
        "allergies": [],
        "chronic": ["牙结石轻度"],
        "notes": "模拟宠物档案，用于展示体重曲线、疫苗和记事。",
    },
]

VISITS = [
    {
        "id": 101,
        "member_key": "demo-self",
        "date": "2026-03-18",
        "type": "体检",
        "hospital": "三甲A 体检中心",
        "department": "体检科",
        "doctor": "周医生",
        "chief_complaint": "年度体检",
        "severity": "一般",
        "diagnosis": ["低密度脂蛋白胆固醇偏高", "维生素D不足"],
        "notes": "建议低脂饮食、增加有氧运动，3个月后复查血脂。",
        "source_file": "mock_demo_self_checkup.md",
    },
    {
        "id": 102,
        "member_key": "demo-self",
        "date": "2026-01-09",
        "type": "就医",
        "hospital": "社区卫生服务中心",
        "department": "全科",
        "doctor": "李医生",
        "chief_complaint": "鼻炎复诊",
        "severity": "轻微",
        "diagnosis": ["过敏性鼻炎"],
        "notes": "花粉季前继续鼻喷激素，必要时加用抗组胺药。",
        "source_file": "mock_demo_self_rhinitis.md",
    },
    {
        "id": 201,
        "member_key": "demo-parent",
        "date": "2026-03-15",
        "type": "就医",
        "hospital": "社区卫生服务中心",
        "department": "慢病门诊",
        "doctor": "赵医生",
        "chief_complaint": "高血压随访",
        "severity": "一般",
        "diagnosis": ["原发性高血压", "血脂偏高"],
        "notes": "家庭血压多数在130/80 mmHg左右，维持现有方案。",
        "source_file": "mock_demo_parent_bp.md",
    },
    {
        "id": 301,
        "member_key": "demo-cat",
        "date": "2025-12-14",
        "type": "体检",
        "hospital": "城市动物医院",
        "department": "内科",
        "doctor": "陈兽医",
        "chief_complaint": "年度体检",
        "severity": "一般",
        "diagnosis": ["体检未见明显异常", "牙结石轻度"],
        "notes": "建议继续控制体重，半年内安排洁牙评估。",
        "source_file": "mock_demo_cat_checkup.md",
    },
    {
        "id": 302,
        "member_key": "demo-cat",
        "date": "2025-09-20",
        "type": "疫苗",
        "hospital": "城市动物医院",
        "department": "预防保健",
        "doctor": "陈兽医",
        "chief_complaint": "年度疫苗",
        "severity": "轻微",
        "diagnosis": ["完成猫三联加强免疫"],
        "notes": "接种后观察30分钟无异常。",
        "source_file": "mock_demo_cat_vaccine.md",
    },
]

LABS = [
    ("demo-self", 101, "2026-03-18", "血脂四项", "LDL-C", "3.8", "mmol/L", None, "3.4", "high"),
    ("demo-self", 101, "2026-03-18", "血脂四项", "HDL-C", "1.6", "mmol/L", "1.0", None, "normal"),
    ("demo-self", 101, "2026-03-18", "血脂四项", "TC", "5.4", "mmol/L", None, "5.2", "high"),
    ("demo-self", 101, "2026-03-18", "血常规", "WBC", "6.2", "10^9/L", "4", "10", "normal"),
    ("demo-self", 101, "2026-03-18", "营养", "25-OH维生素D", "18", "ng/mL", "30", None, "low"),
    ("demo-self", None, "2025-10-10", "血脂四项", "LDL-C", "3.5", "mmol/L", None, "3.4", "high"),
    ("demo-self", None, "2025-05-08", "血脂四项", "LDL-C", "3.2", "mmol/L", None, "3.4", "normal"),
    ("demo-self", None, "2025-05-08", "营养", "25-OH维生素D", "22", "ng/mL", "30", None, "low"),
    ("demo-parent", 201, "2026-03-15", "血压记录", "收缩压", "132", "mmHg", None, "140", "normal"),
    ("demo-parent", 201, "2026-03-15", "血压记录", "舒张压", "84", "mmHg", None, "90", "normal"),
    ("demo-parent", 201, "2026-03-15", "血脂四项", "LDL-C", "3.1", "mmol/L", None, "2.6", "high"),
    ("demo-parent", None, "2025-12-05", "血脂四项", "LDL-C", "3.4", "mmol/L", None, "2.6", "high"),
    ("demo-parent", None, "2025-08-02", "血脂四项", "LDL-C", "3.7", "mmol/L", None, "2.6", "high"),
    ("demo-cat", 301, "2025-12-14", "血常规", "WBC", "9.8", "10^9/L", "5", "19.5", "normal"),
    ("demo-cat", 301, "2025-12-14", "生化", "CREA", "85", "umol/L", "44", "159", "normal"),
    ("demo-cat", 301, "2025-12-14", "生化", "ALT", "31", "U/L", None, "100", "normal"),
    ("demo-cat", 302, "2025-09-20", "疫苗抗体", "猫瘟抗体", "S4", None, None, None, "normal"),
    ("demo-cat", 302, "2025-09-20", "疫苗抗体", "猫杯状抗体", "S3", None, None, None, "normal"),
]

MEDS = [
    ("demo-self", 102, "糠酸莫米松鼻喷剂", "每侧1喷", "每日1次", "鼻喷", "2026-01-09", None, 1, "过敏", "花粉季维持。"),
    ("demo-self", None, "维生素D3", "1000 IU", "每日1次", "口服", "2026-03-20", "2026-06-20", 1, "补充剂", "随餐。"),
    ("demo-parent", 201, "氨氯地平", "5mg", "每日1次", "口服", "2025-09-01", None, 1, "降压", "早晨固定时间服用。"),
    ("demo-parent", 201, "瑞舒伐他汀", "5mg", "每晚1次", "口服", "2026-03-15", None, 1, "调脂", "3个月后复查肝功能和血脂。"),
    ("demo-cat", 301, "化毛膏", "2cm", "每周2次", "口服", "2026-01-01", None, 1, "日常护理", "换毛季可增加频次。"),
]

WEIGHTS = [
    ("demo-self", "2025-10-01", 56.8, "晨起空腹"),
    ("demo-self", "2025-12-01", 56.2, "晨起空腹"),
    ("demo-self", "2026-02-01", 55.9, "晨起空腹"),
    ("demo-self", "2026-04-01", 55.6, "晨起空腹"),
    ("demo-parent", "2025-10-01", 73.5, "家庭记录"),
    ("demo-parent", "2026-01-01", 72.8, "家庭记录"),
    ("demo-parent", "2026-04-01", 72.1, "家庭记录"),
    ("demo-cat", "2025-07-01", 4.05, "夏季体重"),
    ("demo-cat", "2025-09-01", 4.12, "疫苗前"),
    ("demo-cat", "2025-12-14", 4.18, "年度体检"),
    ("demo-cat", "2026-02-15", 4.15, "家庭称重"),
    ("demo-cat", "2026-04-01", 4.10, "家庭称重"),
]

REMINDERS = [
    ("demo-self", "2026-05-18", "复查血脂和维生素D", "体检", "normal", 0, None, "年度体检后3个月复查。"),
    ("demo-self", "2026-04-05", "记录花粉季鼻炎症状", "记事", "normal", 1, "2026-04-05 20:00:00", "喷剂有效，无明显嗜睡。"),
    ("demo-parent", "2026-05-15", "慢病门诊随访", "就医", "high", 0, None, "携带家庭血压记录。"),
    ("demo-parent", "2026-06-15", "复查肝功能和血脂", "检验", "normal", 0, None, "他汀用药后复查。"),
    ("demo-cat", "2026-04-25", "体外驱虫", "驱虫", "normal", 0, None, "按月提醒。"),
    ("demo-cat", "2026-06-14", "洁牙评估", "就医", "normal", 0, None, "年度体检建议半年内评估。"),
    ("demo-cat", "2026-04-20", "体外驱虫", "驱虫", "normal", 1, "2026-04-20 20:00:00", "完成本月体外驱虫。"),
    ("demo-cat", "2026-04-18", "洗澡", "洗澡", "normal", 1, "2026-04-18 19:30:00", "洗澡后状态正常。"),
    ("demo-cat", "2026-03-28", "剪指甲", "护理", "normal", 1, "2026-03-28 21:00:00", "完成，状态稳定。"),
]

ATTACHMENTS = [
    ("demo-self", 101, "2026-03-18", "年度体检报告", "三甲A 体检中心", "体检", "mock_demo_self_checkup.md", "mock_demo_self_checkup.md", "模拟体检报告摘要。"),
    ("demo-self", 102, "2026-01-09", "鼻炎复诊记录", "社区卫生服务中心", "门诊", "mock_demo_self_rhinitis.md", "mock_demo_self_rhinitis.md", "模拟门诊记录。"),
    ("demo-parent", 201, "2026-03-15", "高血压随访记录", "社区卫生服务中心", "慢病", "mock_demo_parent_bp.md", "mock_demo_parent_bp.md", "模拟慢病随访。"),
    ("demo-cat", 301, "2025-12-14", "猫咪年度体检", "城市动物医院", "体检", "mock_demo_cat_checkup.md", "mock_demo_cat_checkup.md", "模拟宠物体检。"),
    ("demo-cat", 302, "2025-09-20", "猫三联加强免疫", "城市动物医院", "疫苗", "mock_demo_cat_vaccine.md", "mock_demo_cat_vaccine.md", "模拟疫苗记录。"),
]

ATTACHMENT_TEXT = {
    "mock_demo_self_checkup.md": "# 年度体检报告\n\n模拟数据。LDL-C 3.8 mmol/L，TC 5.4 mmol/L，25-OH维生素D 18 ng/mL。\n\n建议：低脂饮食、规律运动，3个月后复查。",
    "mock_demo_self_rhinitis.md": "# 鼻炎复诊记录\n\n模拟数据。主诉为花粉季鼻塞、喷嚏。继续鼻喷激素，必要时口服抗组胺药。",
    "mock_demo_parent_bp.md": "# 高血压随访记录\n\n模拟数据。诊室血压132/84 mmHg，家庭记录稳定。维持氨氯地平，新增低剂量他汀。",
    "mock_demo_cat_checkup.md": "# 猫咪年度体检\n\n模拟数据。血常规、生化未见明显异常。牙结石轻度，建议半年内洁牙评估。",
    "mock_demo_cat_vaccine.md": "# 猫三联加强免疫\n\n模拟数据。完成猫三联加强免疫，抗体水平达标，接种后观察无异常。",
}


def _insert_member(conn: Any, item: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO members
          (key, name, full_name, initial, birth_date, sex, blood_type, role,
           species, sort_order, breed, home_date, chip_id, doctor, allergies, chronic, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item["key"], item["name"], item["full_name"], item["initial"], item["birth_date"],
            item["sex"], item["blood_type"], item["role"], item["species"], item["sort_order"],
            item["breed"], item["home_date"], item["chip_id"], item["doctor"],
            json.dumps(item["allergies"], ensure_ascii=False),
            json.dumps(item["chronic"], ensure_ascii=False),
            item["notes"],
        ),
    )


def _sync_member_sort_order(conn: Any) -> None:
    for item in MEMBERS:
        conn.execute(
            "UPDATE members SET sort_order = ? WHERE key = ?",
            (item["sort_order"], item["key"]),
        )


def write_mock_files() -> None:
    MOCK_ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, text in ATTACHMENT_TEXT.items():
        (MOCK_ATTACHMENT_DIR / filename).write_text(text + "\n", encoding="utf-8")


def has_mock_data() -> bool:
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM members WHERE key LIKE 'demo-%'").fetchone()
        return bool(row and row["c"])


def seed_mock_data(reset: bool = False) -> None:
    init_db()
    write_mock_files()
    with get_conn() as conn:
        if reset:
            for table in ["attachments", "reminders", "weight_log", "meds", "lab_results", "visits", "members"]:
                conn.execute("DELETE FROM " + table)
        else:
            row = conn.execute("SELECT COUNT(*) AS c FROM members WHERE key LIKE 'demo-%'").fetchone()
            if row and row["c"]:
                _sync_member_sort_order(conn)
                return

        for item in MEMBERS:
            _insert_member(conn, item)

        for item in VISITS:
            conn.execute(
                """
                INSERT INTO visits
                  (id, member_key, date, type, hospital, department, doctor, chief_complaint, severity, diagnosis, notes, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"], item["member_key"], item["date"], item["type"], item["hospital"], item["department"],
                    item["doctor"], item["chief_complaint"], item["severity"],
                    json.dumps(item["diagnosis"], ensure_ascii=False), item["notes"], item["source_file"],
                ),
            )

        conn.executemany(
            """
            INSERT INTO lab_results
              (member_key, visit_id, date, panel, test_name, value, unit, ref_low, ref_high, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            LABS,
        )
        conn.executemany(
            """
            INSERT INTO meds
              (member_key, visit_id, name, dose, freq, route, start_date, end_date, ongoing, category, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            MEDS,
        )
        conn.executemany(
            "INSERT INTO weight_log (member_key, date, weight_kg, notes) VALUES (?, ?, ?, ?)",
            WEIGHTS,
        )
        conn.executemany(
            """
            INSERT INTO reminders
              (member_key, date, title, kind, priority, done, done_at, notes, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual')
            """,
            REMINDERS,
        )
        conn.executemany(
            """
            INSERT INTO attachments
              (member_key, visit_id, date, title, org, tag, filename, file_path, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (*item[:-2], (MOCK_ATTACHMENT_DIR / item[-2]).relative_to(MOCK_ATTACHMENT_DIR.parent).as_posix(), item[-1])
                for item in ATTACHMENTS
            ],
        )
