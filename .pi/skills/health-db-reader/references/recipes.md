# 问法→命令

- "XX吃过哪些药" → `read_db.py meds --member <key>`
- "XX最近一次白细胞" → `read_db.py labs --member <key> --test 白细胞 --latest`
- "XX某指标变化趋势" → `read_db.py labs --member <key> --test <指标>`（默认10条）
- "XX最近看了什么病" → `read_db.py visits --member <key>`
- "XX有没有XX记录" → `read_db.py search <关键词>`
- "9月22日那次就诊什么情况" → `visits` 定位 visit_id → `attachments --visit <id>` → 读 md/看原图再答
- 搜不到时说"库里没这条"，不编。指标名模糊匹配，多条时列出候选让人选。
