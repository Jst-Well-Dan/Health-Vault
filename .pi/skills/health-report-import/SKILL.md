---
name: health-report-import
description: 把报告导入家庭健康档案。当用户说"导入报告""处理 incoming""录入这份体检报告""新报告入库""归档这批扫描件"时使用。覆盖：incoming/ 扫描件与 PDF → MinerU 转换 → 归档到 data/reports → 整理 payload JSON → dry-run 校验 → 用户确认后写入 SQLite → 报告 visit_id 与备份路径。
---

# 导入报告到健康档案

批量报告导入（visits + labs + attachments 成套写库）只走这条路径：**本机 pi + 本 skill + `backend/scripts/import_visit_json.py`**。前端白名单小写入（成员、记事/提醒、体重、用药单条维护）由用户在界面确认后直接调 REST，不走本 skill。

## 四条铁律

1. **先 dry-run，把字段给用户看，得到明确确认后才 `--write`。**
2. 成员、日期、单位、异常判定不确定就停下来问用户，**不要猜**。
3. 不删、不重建、不批量覆盖真实库；写入只用 `backend/scripts/import_visit_json.py`（它自带备份与校验）。
4. 不要把整库内容或报告的敏感细节倒进聊天，只展示本次要写入的字段摘要。

## 步骤

### 1. 找出待处理文件

```bash
python backend/scripts/check_incoming.py
```

它会按内容 md5 把 `incoming/` 里的文件分成 `[已归档]`（`data/reports/` 里已有相同内容）和 `[待导入]`。已归档的跳过，不要重复导入；只处理 `[待导入]` 的。

如果报告已在别处归档、只是原件还留在 `incoming/`，可以一次性清掉：

```bash
python backend/scripts/check_incoming.py --delete-archived   # 只删确认已归档的原件
```

这个脚本按 md5 比对，**未归档的文件绝不会被删除**。

### 2. 确认成员

应用在跑时优先用只读接口（无需登录）：

```bash
curl -s http://127.0.0.1:8000/api/members
```

应用没跑时直接查库：

```bash
python -c "import sys;sys.path.insert(0,'backend');from database import get_conn;print([dict(r) for r in get_conn().execute('SELECT key,name,full_name FROM members')])"
```

报告上写了受检者姓名时，必须核对是否与要写入的成员一致；不一致就停下来问用户。看原图确认姓名是允许的（这是导入必需）。

### 3. 转成 Markdown

按 `mineru` skill 转换（CLI 已装在 `~/.mineru/bin/mineru-open-api`）：

```bash
mineru-open-api flash-extract "<pdf或图片>" -o outgoing/mineru/
```

表格多的报告（体检、生化）用带 token 的 `extract`，`flash-extract` 不识别表格。转换失败或表格缺失时，直接看原图人工核对，不要编造数值。

### 4. 归档原件与转换结果

命名规范 `YYYYMMDD_机构_项目_姓名.ext`，放进：

| 内容 | 位置 |
|---|---|
| 原始 PDF | `data/reports/<member>/pdf/` |
| 多图扫描件原图 | `data/reports/<member>/images/`（`_原图01.jpg`、`_原图02.jpg`…） |
| 人工校对的摘要 md | `data/reports/<member>/md/` |
| MinerU 原始输出 | `data/reports/<member>/mineru/` |

归档完成后，用 `python backend/scripts/check_incoming.py --delete-archived` 清理 `incoming/` 里已归档的原件（脚本会先比对 md5，未归档的不会删）。**删之前先确认归档文件存在且内容一致。**

### 5. 写 payload JSON

存到 `data/imports/<member>/<date>_<项目>.json`，形状见 `.pi/skills/health-db-writer/assets/visit_import.example.json`，字段规则见 `.pi/skills/health-db-writer/references/database-write.md`。

要点：
- `visit.notes`（一句话高信号摘要）和 `visit.note_full`（`### 医生诊断 / ### 诊疗意见 / ### 治疗方案说明`）**必填**。
- `visit.diagnosis` 是数组；`severity` 只能是 `严重/一般/轻微` 或 null。
- 每条 lab 保留报告的参考范围 `ref_low/ref_high` 与原判读 `status`（`normal/high/low/abnormal/unknown`）。
- `attachments[].file_path` 用项目相对路径，指向第 4 步归档的文件。
- **用药必抽**：报告里出现 `用药/R:/处方/口服/每日/每次/片/盒` 任一字样就建 `meds[]`，逐味填 `name/dose/freq/route/start_date/end_date`；起止日期缺失时用就诊日期，`ongoing` 不确定就填 false 并写进 notes。处方明确写“未开药/无需用药”才允许 `meds: []`。
- **核对化验条数**：payload 里 labs 的数量应与 Markdown 表格行数大致吻合；差距大说明表格漏读了，回第 3 步。
- **核对用药味数**：payload 里 meds 的味数应与处方/病历的处理意见里药味数一致；报告有药但 `meds: []` 必须停下来，不准直接 dry-run。

### 6. dry-run 并展示给用户

```bash
python backend/scripts/import_visit_json.py --file data/imports/<member>/<payload>.json --dry-run
```

把输出（成员、日期、机构、诊断、将写入的条数、重复就诊提醒）**原样**给用户看，并等一句明确的"确认/写入"。同一天已有就诊记录时脚本会提示，先问用户是不是重复录入。

展示时必须单列一行 `用药 N 味：药名×剂量×用法`（N=0 时写 `用药 0 味（报告未提用药）`），让用户一眼看出漏药。

### 7. 写入

```bash
python backend/scripts/import_visit_json.py --file data/imports/<member>/<payload>.json --write
```

### 8. 报告结果

回报：`visit_id`、影响行数、数据库实际路径、备份路径。校验不一致或写入失败时不要重试覆盖，把错误原文给用户。

## 常见失败

| 现象 | 处理 |
|---|---|
| `成员不存在` | 第 2 步选错了 key，或用户还没建这个成员 |
| `附件文件不存在` | 第 4 步没归档到位，先归档再写 |
| `同一天已有就诊记录` | 先确认是否重复；确实是新记录才加 `--allow-duplicate` |
| `visit.notes 和 visit.note_full 必填` | 报告里没写治疗/用药就说"报告未提供"，不要留空 |
| 处方有药但 payload `meds: []` | 回第 5 步按“用药必抽”补齐，不准绕过；已入库的旧 visit 漏药走单条 REST 补（先贴 before/after 并确认），不要用导入脚本重建 visit |
| MinerU 超时或 429 | 换 `extract`（带 token）或人工按原图整理 |
