---
name: health-db-reader
description: 只读查家庭健康档案。当用户问"吃过哪些药""最近一次某指标""最近就诊""搜一下XX"时使用。只查不写，SQL写死在脚本里，不手拼。
---

# 查健康档案（只读）

唯一入口：`backend/scripts/read_db.py`。连接是 `mode=ro`，写操作直接报错。

```bash
python backend/scripts/read_db.py meds --member <key>                 # 吃过哪些药
python backend/scripts/read_db.py labs --member <key> --test <指标> --latest   # 某指标最近一次
python backend/scripts/read_db.py visits --member <key>               # 最近就诊
python backend/scripts/read_db.py search <关键词>                     # 跨表检索
python backend/scripts/read_db.py attachments --visit <visit_id>     # 某次就诊的附件清单
```

问到某次就诊/报告时，必须走附件链：`visits` 定位 visit_id → `attachments` 拿
file_path → 直接读 `.md` / 看原图（`.pdf` 先 `mineru-open-api flash-extract` 转一份）→
结合原文回答，不要只背 visits.notes 的一句话摘要。

## 铁律

1. 只读：不备份（读不产生备份）、不写库、不删改。写操作走 `health-db-writer` / `health-report-import`。
2. 成员 key 先用 `SELECT key,name FROM members` 对上号，别名对不上就问用户。
3. 只转述报告结论，不做诊断、不给用药建议。指标异常只说"报告标为 high/low"，不解释病情。
4. 回答≤10行：药名×剂量×用法、指标值+单位+参考范围+日期，贴完收。

## 下钻

- 表结构速查：`references/tables.md`
- 问法→命令：`references/recipes.md`
