---
name: health-db-writer
description: 安全地校验、准备、导入并核对本项目的 SQLite 健康档案数据。包含文件归档与命名（YYYYMMDD_机构_项目_姓名）、报告转结构化 JSON 的规则。在本仓库用 pi 写入或更新就诊、化验、用药、附件、提醒、成员、体重数据时使用；日常导入报告优先用 health-report-import skill。
---

# Health DB Writer

## Core Rule

Treat `data/health.db` as user data. Do not write ad hoc SQL to the real database unless the user explicitly asks. Prefer project scripts, dry-runs, backups, and post-write verification.

## Workflow

1. Identify the project root. Expected layout includes `backend/database.py`, `backend/scripts/`, `data/health.db`, and the mock fixture `tests/fixtures/health_mock.db`.
2. Read `references/database-write.md` before shaping or writing data.
3. Archive raw source files first. If the user gave a root-level folder, loose images, or files under a temporary incoming path, move them into `data/reports/<member_key>/pdf/`, `data/reports/<member_key>/md/`, or `data/reports/<member_key>/images/` with standardized names before preparing the payload. Do not leave the original report only in the repo root after import.
4. Prepare a JSON payload from `assets/visit_import.example.json`, saved as `data/imports/<member_key>/<date>_<item>.json`.
5. For reports converted from Markdown/PDF tables, check table coverage before writing:

```powershell
python backend/scripts/import_visit_json.py --file <payload.json> --dry-run
```

Read `将写入：… 化验 N 条` and compare it with the result rows the report actually lists. A low `payload_labs` count usually means the extraction or manual JSON preparation missed tables; `import_visit_json.py` only writes the labs it is given.

6. Run a dry-run:

```powershell
python backend/scripts/import_visit_json.py --file <payload.json> --dry-run
```

7. Only after validation and user intent are clear, write (backup is automatic):

```powershell
python backend/scripts/import_visit_json.py --file <payload.json> --write
```

Same-day duplicate visits are refused unless you add `--allow-duplicate`.

8. Report the inserted `visit_id`, row counts, database path, and backup path.

## Mock Mode

Use mock mode for experiments or uncertain transformations:

```powershell
$env:HEALTH_MOCK_MODE='1'
python backend/scripts/import_visit_json.py --file <payload.json> --write
```

Unset mock mode before working with the real database in a new shell if needed.
## Write Boundaries

- Do not delete, rebuild, reset, or bulk-update the real database without explicit user confirmation.
- Do not silently modify old records when the task is to import a new report.
- When replacing existing records, do not leave duplicate visits unless the user explicitly wants history preserved. Prefer a transaction-based replace script that deletes old `attachments`, `meds`, `lab_results`, and `visits` together after backup.
- Check that `member_key` exists before importing.
- Use `YYYY-MM-DD` dates.
- Keep attachment paths project-relative, usually under `data/reports/...`.
- Fill `severity`, `diagnosis`, `notes`, and `note_full` from the evidence in the report. These keys must be present in the visit JSON. Do not leave `notes` or `note_full` empty for visit/report imports.
- Keep `diagnosis` as a list in JSON payloads. Use explicit diagnoses or report conclusions; use `[]` only when the source has no diagnosis or conclusion.
- Use only `严重`, `一般`, `轻微`, or null for `severity`. Choose the attention level from the source findings; use null only when evidence is insufficient.
- Keep `notes` to one short sentence with the highest-signal abnormal findings, instructions, or follow-up.
- Keep `note_full` as a structured Markdown summary with sections such as `### 医生诊断`, `### 诊疗意见`, and `### 治疗方案说明`. State when the source does not provide treatment or medication details instead of inventing them.
- Attachment titles should be clear and professional.

## File Management Rules

Handle source files (PDF, Markdown) before or during the import process:

1. **Naming Convention**: Always rename report files to `YYYYMMDD_机构名_项目名_姓名.扩展名`.
   - *Example*: `20240323_爱康国宾_春子_入职体检.pdf`
2. **Directory Structure**: Organize files by member and type:
   - PDFs: `data/reports/<member_key>/pdf/`
   - Markdowns: `data/reports/<member_key>/md/`
   - Images/Assets: `data/reports/<member_key>/images/`
3. **Traceability**: Ensure `attachments` in the JSON payload use these standardized paths. Use `source_file` in `visit` and `labs` to point to the primary Markdown report.
4. **Processing**: If provided a PDF in `data_incoming/`, convert it to Markdown (e.g., using `mineru`), move both files to their respective directories under `data/reports/`, and then perform the database import.
5. **Default Archiving Rule**: When the raw report still sits in the project root, a user-provided folder, or another staging location, list that location first, confirm the relevant files, then move the originals into the standardized `data/reports/<member_key>/...` directories as part of the same task. For image-only reports, archive the original images even if the database only stores a Markdown summary.
6. **No Root Leftovers**: After archiving, remove only the now-empty staging folder that held those source files. Do not delete unrelated root files.

## Table Extraction Lessons

- `backend/scripts/import_visit_json.py` writes JSON payloads exactly as given; it does not extract tables from Markdown.
- For multi-table medical reports, prepare JSON payloads under `data/imports/<member_key>/` and compare the dry-run lab count with the report's row count before writing.
- Always keep `visit.source_file` and `labs[].source_file` populated with the project-relative Markdown path. Missing `source_file` makes later audit and repair much harder.
- For replacement imports, preserve the generated JSON payloads in `data/imports/<member_key>/` so future audits can reproduce exactly what was written.

## Bundled Resources

- `references/database-write.md`: database paths, scripts, payload shape, visit rules, lab rules, and verification SQL.
- `assets/visit_import.example.json`: import payload template.
- `scripts/import_visit_json.py`: helper wrapper that delegates to `backend/scripts/import_visit_json.py` (useful when running from the skill directory).
