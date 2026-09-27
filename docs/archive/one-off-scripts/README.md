# 一次性脚本归档（2026-09-23）

从 `backend/scripts/` 移出，任务已完成、仓库内零引用（skill/docs/tests 均未引用）。
用 `git log --follow` 可找回历史。需要重跑时拷回 `backend/scripts/` 即可。

| 脚本 | 原用途 | 归档原因 |
|---|---|---|
| `build_tijian_payloads.py` | 组装2026年两份体检（dan/chun）的入库 payload | 写死特定报告，活已干完 |
| `parse_tijian_md.py` | 美兆/瑞慈 MinerU 表格转 lab 行（只读那两份 .md） | 同上，活已干完 |
| `extract_report_payloads.py` | HTML 表格批量提取旧工具 | 被 MinerU + 手工 payload 流程取代 |
| `migrate_meds_category.py` | 药品 category 回填 + 药名规范化（自述一次性） | 迁移跑过即失效 |

仍在用的写入入口：`backend/scripts/import_visit_json.py` + `backend/services/writes.py`，不要动。
