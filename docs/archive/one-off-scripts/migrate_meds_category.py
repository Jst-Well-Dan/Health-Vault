"""
一次性迁移脚本：
1. 根据药名正则推断 category 并回填到 DB（category IS NULL 的记录）
2. 对药名做基础规范化（去首尾空格、合并连续空格）
3. 打印处理摘要；可用 --dry-run 预览而不写库

用法：
  python backend/scripts/migrate_meds_category.py
  python backend/scripts/migrate_meds_category.py --dry-run
"""

import argparse
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from database import get_conn, init_db  # noqa: E402

# 药名正则 → 分类标签（与 DB category 字段值一一对应）
RULES: list[tuple[str, re.Pattern]] = [
    ('免疫治疗',   re.compile(r'变应|脱敏|免疫治疗')),
    ('抗组胺',     re.compile(r'西替利嗪|氯雷他定|苯海拉明|奥洛他定|依巴斯汀|非索非那定')),
    ('白三烯拮抗', re.compile(r'孟鲁司特')),
    ('糖皮质激素', re.compile(r'布地奈德|地塞米松|泼尼松|倍氯米松|曲安奈德|氟替卡松')),
    ('支气管扩张', re.compile(r'福莫特罗|沙丁胺醇|特布他林|噻托溴铵|格隆溴铵|芘达格莫|茚达特罗|维兰特罗')),
    ('心血管',     re.compile(r'氨氯地平|厄贝沙坦|缬沙坦|卡托普利|贝那普利|美托洛尔|比索洛尔|硝苯地平')),
    ('降糖药',     re.compile(r'二甲双胍|格列|利格列汀|西格列汀|达格列净|恩格列净')),
    ('调脂药',     re.compile(r'阿托伐他汀|瑞舒伐他汀|辛伐他汀|洛伐他汀')),
    ('抗菌药',     re.compile(r'青霉素|头孢|阿莫西林|阿奇霉素|左氧氟沙星|甲硝唑')),
    ('止痛退烧',   re.compile(r'布洛芬|对乙酰氨基酚|阿司匹林|双氯芬酸|洛索洛芬|萘普生|吲哚美辛')),
]

# 复合成分药的精确映射（多成分药正则会命中第一个，需要手动指定）
EXACT: dict[str, str] = {
    '布地奈德福莫特罗吸入套剂': '糖皮质激素+支气管扩张',
    '布地奈德福莫特罗吸入气雾剂': '糖皮质激素+支气管扩张',
    '丙酸氟替卡松沙美特罗吸入粉雾剂': '糖皮质激素+支气管扩张',
}


def normalize_name(name: str) -> str:
    return ' '.join(name.strip().split())


def infer_category(name: str) -> str | None:
    stripped = normalize_name(name)
    if stripped in EXACT:
        return EXACT[stripped]
    for label, pattern in RULES:
        if pattern.search(stripped):
            return label
    return None


def migrate(dry_run: bool = False) -> None:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, category FROM meds ORDER BY id"
        ).fetchall()

        cat_updates: list[tuple[str, int]] = []
        name_updates: list[tuple[str, int]] = []
        unresolved: list[str] = []

        for row in rows:
            old_name = row["name"]
            new_name = normalize_name(old_name)
            if new_name != old_name:
                name_updates.append((new_name, row["id"]))

            if row["category"] is None:
                cat = infer_category(new_name)
                if cat:
                    cat_updates.append((cat, row["id"]))
                else:
                    unresolved.append(f'  id={row["id"]}  {new_name}')

        print(f"共 {len(rows)} 条用药记录")
        print(f"药名规范化：{len(name_updates)} 条需更新")
        print(f"category 回填：{len(cat_updates)} 条（已有值的跳过）")
        print(f"未能识别分类：{len(unresolved)} 条（将保持 NULL，可手动设置）")
        if unresolved:
            print('\n'.join(unresolved))

        if dry_run:
            print("\n[dry-run] 未写入数据库。")
            return

        for new_name, med_id in name_updates:
            conn.execute("UPDATE meds SET name = ? WHERE id = ?", (new_name, med_id))
        for cat, med_id in cat_updates:
            conn.execute("UPDATE meds SET category = ? WHERE id = ?", (cat, med_id))

        print(f"\n已写入 {len(name_updates)} 条药名更新，{len(cat_updates)} 条分类更新。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="预览变更，不写库")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
