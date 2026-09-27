# 表速查（读哪个表、看哪几列）

| 问题 | 表 | 关键列 |
|---|---|---|
| 吃过哪些药 | `meds` | name, dose, freq, route, start_date, end_date, ongoing |
| 某指标历史 | `lab_results` | date, panel, test_name, value, unit, ref_low, ref_high, status |
| 最近就诊 | `visits` | date, type, hospital, department, chief_complaint, diagnosis, notes |
| 记事/提醒 | `pet_care_logs` | date, kind（驱虫/洗澡/换猫砂）, notes —— 无 title 列 |
| 体重 | `weight_log` | date, weight_kg |
| 附件原文 | `attachments` | title, file_path（相对路径，指向 data/reports/ 原件） |

成员 key：`members.key`（如 dan/chun），别名对不上先查 `SELECT key,name,full_name FROM members`。
`status` 含义：normal/high/low/abnormal/unknown，照抄不 reinterpret。
