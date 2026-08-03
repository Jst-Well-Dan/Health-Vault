# Database Write Reference

This reference consolidates database operations, visit writing, and lab result extraction for this project.

## Database Operations

Paths:

- Real database: `data/health.db`
- Mock database: `data/mock/health_mock.db`
- Backups: `data/backups/`
- Database selector: `backend/database.py`
- Safe import script: `backend/scripts/import_visit_json.py`
- Legacy payload importer used by the safe script: `backend/scripts/import_md.py`
- Table coverage audit script: `backend/scripts/audit_report_tables.py`
- Markdown table extraction helper, when present: `backend/scripts/extract_report_payloads.py`
- Visit replacement helper, when present: `backend/scripts/replace_visit_json.py`

Database selection order:

1. `HEALTH_DB_PATH`, when set
2. `HEALTH_MOCK_MODE=1`, which uses `data/mock/health_mock.db`
3. Default real database, `data/health.db`

Dry-run before writing:

```powershell
python backend/scripts/import_visit_json.py --file <payload.json> --dry-run
```

Write after validation:

```powershell
python backend/scripts/import_visit_json.py --file <payload.json> --write
```

Use mock mode for experiments:

```powershell
$env:HEALTH_MOCK_MODE='1'
python backend/scripts/import_visit_json.py --file <payload.json> --write
```

The safe import script validates payload shape, checks that `member_key` exists, backs up the real database before write, imports the visit, and prints counts.

After writing, report `visit_id`, row counts, database path, and backup path.

## Table Coverage Audit

`import_visit_json.py` does not parse Markdown or PDF tables. It writes exactly the `labs` array supplied in the JSON payload. When lab rows look incomplete, inspect the payload generation step before suspecting the database insert loop.

For converted medical reports with many HTML tables, run an audit before writing:

```powershell
python backend/scripts/audit_report_tables.py --member <member_key> --payload-dir data/imports/<member_key> <report.md> [...]
```

Read the columns as follows:

- `tables`: total HTML tables found in the Markdown.
- `result_tables`: tables that look like result tables.
- `estimated_result_rows`: rough extraction target, useful for detecting obvious misses.
- `payload_labs`: rows in the saved import JSON.
- `db_labs`: rows currently in `lab_results` for that report/date.

Investigate before writing when `payload_labs` is much smaller than the report's result rows, or when `db_labs` differs from `payload_labs` after an import. Keep generated payloads under `data/imports/<member_key>/` so the audit can compare source, payload, and database.

Known lesson: table extraction may miss or over-include rows when reports contain trend tables, split continuation tables, adjacent unrelated tables, or HTML table remnants in nearby text. Review sample rows from each generated payload before writing.

## Import Payload

Top-level fields:

- `visit`: required object
- `labs`: optional list
- `meds`: optional list
- `attachments`: optional list

Required fields:

- `visit.member_key`: existing member key
- `visit.date`: `YYYY-MM-DD`
- `visit.type`: optional primary category for frontend classification, such as `体检`, `就医`, `疫苗`, or `复查`
- `labs[].panel`
- `labs[].test_name`
- `meds[].name`
- `attachments[].title`

Common rules:

- Use `YYYY-MM-DD` dates.
- Keep attachment paths project-relative, usually under `data/reports/...`.
- Fill `severity`, `diagnosis`, `notes`, and `note_full` from the evidence in the source report. These are agent-judged fields and must be present in the visit JSON.
- Keep `diagnosis` as a list in JSON payloads. Use explicit diagnoses or report conclusions; use `[]` only when no diagnosis or conclusion is available.
- Use only `严重`, `一般`, `轻微`, or null for `severity`. Choose the attention level from the source findings; use null only when evidence is insufficient.
- Do not leave `notes` or `note_full` empty for visit/report imports.
- Do not delete, rebuild, reset, or bulk-update the real database without explicit user confirmation.
- Always populate `visit.source_file` and `labs[].source_file` with the project-relative Markdown path when a source report exists.
- Preserve final JSON payloads in `data/imports/<member_key>/` for traceability and future audits.

## File Organization & Naming

Standardize report files before importing to ensure consistent paths and traceability:

1. **Naming Pattern**: `YYYYMMDD_机构名_项目名_姓名.扩展名`
   - *机构名*: 爱康国宾, 北医三院, etc.
   - *项目名*: 入职体检, 胃镜检查, 哮喘复查, etc.
   - *姓名*: Member key or display name.
2. **Directory Structure**:
   - `data/reports/<member_key>/pdf/`: Original PDF reports.
   - `data/reports/<member_key>/md/`: Markdown versions (converted from PDF or manually created).
   - `data/reports/<member_key>/images/`: Extracted images or charts.
3. **Internal Links**:
   - `attachments.file_path`: Use the standardized path (e.g., `data/reports/chunzi/pdf/...`).
   - `visits.source_file`: Use the standardized Markdown filename.
4. **Archive Before Import**:
   - If the user gives a repo-root folder, loose root-level images, or files in a temporary incoming path, list that location and move the originals into the member's `pdf/`, `md/`, or `images/` directories before import.
   - Keep original image reports even when you also create a Markdown summary from them.
   - After moving the files, remove only the empty staging folder; do not delete unrelated files.
5. **Image-Only Reports**:
   - When the source is a single image or a set of JPEG/PNG pages, archive those originals under `data/reports/<member_key>/images/` with standardized names.
   - Then create the Markdown summary and reference both the Markdown and any archived originals in `attachments` when appropriate.

## Visits

`visits` describes one medical event: visit, recheck, treatment, screening, or report. Do not split each lab indicator into separate visits.

Related data belongs elsewhere:

- Lab indicators: `lab_results`
- Medication or treatment drugs: `meds`
- Source documents: `attachments`
- Summary only: `visits.notes`; structured detail summary: `visits.note_full`

Visit field rules:

- `member_key`: must exist in `members`.
- `date`: actual visit, sample, check, or treatment date.
- `type`: primary record category used by the frontend. Use `体检` for health checkups and `就医` for ordinary clinical visits. Do not rely on `attachments.tag` for visit/report page classification.
- `hospital`: hospital, clinic, or pet hospital; leave empty if unknown.
- `department`: department, clinic, check unit, or pet medical item; leave empty if unknown.
- `doctor`: leave empty if unknown.
- `chief_complaint`: short title for this event.
- `severity`: only `严重`, `轻微`, `一般`, or null.
- `diagnosis`: list of explicit diagnoses or report conclusions. Use `[]` if none.
- `notes`: one sentence summary of key instructions, abnormal findings, or follow-up.
- `note_full`: structured Markdown summary of the source report, usually with `### 医生诊断`, `### 诊疗意见`, and `### 治疗方案说明`.
- `source_file`: source Markdown or PDF path/name for traceability.

Chief complaint priority:

1. Original chief complaint.
2. Doctor diagnosis or visit purpose as a short title.
3. Report purpose.
4. Cleaned filename title.

Severity is the attention level of this event, not a permanent disease grade. Do not infer it from disease name alone.

- `严重`: uncontrolled disease, strong positive findings, suspected major disease, obvious inflammation, acute worsening, significantly abnormal key indicators, systemic treatment, close follow-up, or specialty treatment.
- `轻微`: symptoms or abnormalities without urgent evidence, short-term treatment, observation, recheck, mild abnormal labs, or recovery-phase abnormalities.
- `一般`: routine visits, maintenance therapy, preventive checks, stable planned treatment, normal reports, or archival continuity.
- null: evidence is insufficient.

Keep `notes` short. Include high-signal facts such as `FeNO 185.4 ppb`, `SAA 169.44 mg/L`, `建议规律用药并复查`, or `必要时核磁检查`. Do not paste full report text or list every lab indicator in `notes`.

Use `note_full` when the frontend needs a richer report detail. Keep it concise and evidence-based:

- `### 医生诊断`: diagnoses, report conclusions, or `报告未列出明确诊断。`
- `### 诊疗意见`: main abnormal findings, interpretation stated by the report, follow-up advice, or observation points.
- `### 治疗方案说明`: medications, procedures, treatment advice, or `报告中未提供具体用药或治疗方案。`
- Do not invent treatment, severity, or disease conclusions beyond the source. If only screening findings exist, describe them as screening findings.

## Lab Results

`lab_results` stores structured indicators from medical reports, checks, screening panels, scales, and pet reports. Avoid mixing OCR noise, medical inference, and raw report paragraphs.

Lab field rules:

- `member_key`: existing member key.
- `visit_id`: corresponding visit id. Import scripts usually create the visit first.
- `date`: sample/check date; use visit date if no separate date exists.
- `panel`: group such as `血常规`, `血生化`, `肺功能`, `FeNO`, `过敏原IgE`, `SAA`.
- `test_name`: cleaned full indicator name; no arrows, notes, or broken OCR fragments.
- `value`: original result value as text; numeric indicators should usually be numeric strings.
- `unit`: unit only, with obvious OCR unit corrections.
- `ref_low`: explicit reference lower bound only.
- `ref_high`: explicit reference upper bound only.
- `status`: `normal`, `high`, `low`, `abnormal`, or `unknown`.
- `source_file`: original Markdown or PDF for traceability.

Core lab rules:

- Use report-provided reference ranges. Do not override with generic medical knowledge.
- Do not guess whether a lone number is an upper or lower bound.
- Do not apply human reference ranges to pets.
- Do not write OCR arrows into `test_name`; arrows only affect `status`.
- If OCR rows are misaligned or incomplete, write less or use `unknown` rather than inventing structure.
- Use `normal` only when the report or explicit reference range supports it.
- Do not treat historical trend/comparison tables as current lab results unless the user explicitly asks to store trend rows.
- Continuation tables can share a header from the previous table, but confirm they are true continuations and not trend summaries or explanatory tables.

## Replacing Existing Visits

Only replace existing records when the user explicitly asks to replace or remove old data. Before replacing:

1. Identify exact old `visit_id` values and current row counts for `lab_results`, `attachments`, and `meds`.
2. Create a timestamped backup under `data/backups/`.
3. Delete dependent rows and visits in one transaction: `attachments`, `meds`, `lab_results`, then `visits`.
4. Insert the replacement payloads in the same transaction when possible.
5. Verify old visit IDs are gone and new `visit_id` values have expected row counts.

Use `backend/scripts/replace_visit_json.py` when available for transaction-based replacement. Report deleted IDs, deleted row counts, inserted IDs, inserted row counts, database path, and backup path.

Reference range parsing:

- `3.50~19.50` or `3.50-19.50`: `ref_low=3.50`, `ref_high=19.50`
- `≤2.00` or `<2.00`: `ref_low=null`, `ref_high=2.00`
- `≥80` or `>80`: `ref_low=80`, `ref_high=null`
- empty, `~`, or unclear: both null
- lone `80` without semantics: do not split; review manually

Status order:

1. Use report markers such as `↑`, `↓`, `H`, `L`, `偏高`, `偏低`, `阳性`, `阴性`.
2. Compare numeric value with explicit `ref_low`/`ref_high`.
3. Use explicit doctor/report abnormal conclusion.
4. Otherwise use `unknown`.

Status mapping:

- below lower bound: `low`
- above upper bound: `high`
- within explicit range: `normal`
- positive or abnormal without direction: `abnormal`
- unclear: `unknown`

Do not use `high` or `low` for trend changes compared with a previous report.

OCR cleanup:

- `g/1`, `g/`: `g/L`
- `mmoI/L`, `mmo1/L`: `mmol/L`
- `umo1/L`: `umol/L`
- `f1`: `fL`
- `10*9/1`, `10^9/`: `10^9/L`
- `u/L`: `U/L`
- Remove `↑`, `↓`, `→`, `备注`, and extra spaces from names.
- Merge split indicator names.
- Do not write fragments such as `度）`.

Special panels:

- Pulmonary function: store raw values as `FEV1`, `FVC`, `PEF`; store percent predicted as `FEV1%预计值`, `FVC%预计值`; do not hard-code `80` for `FEV1/FVC`.
- Specific IgE: for `<0.35 KUA/L`, use `ref_high=0.35` when appropriate.
- Adult FeNO: if the report threshold is `>=50 ppb`, use `ref_high=50`.
- Children and pets require report-specific thresholds.
- Pet reports must use the pet hospital's own reference ranges; SAA thresholds vary by kit.

## Verification SQL

```sql
SELECT * FROM visits WHERE id = ?;
SELECT COUNT(*) AS c FROM lab_results WHERE visit_id = ?;
SELECT COUNT(*) AS c FROM meds WHERE visit_id = ?;
SELECT COUNT(*) AS c FROM attachments WHERE visit_id = ?;
```

Lab consistency checks:

```sql
SELECT id, member_key, panel, test_name, value, unit, ref_low, ref_high, status
FROM lab_results
WHERE
  (ref_low IS NOT NULL AND ref_low <> '' AND CAST(value AS REAL) < CAST(ref_low AS REAL) AND status NOT IN ('low','abnormal'))
  OR
  (ref_high IS NOT NULL AND ref_high <> '' AND CAST(value AS REAL) > CAST(ref_high AS REAL) AND status NOT IN ('high','abnormal'))
  OR
  (status='high' AND ref_high IS NOT NULL AND ref_high <> '' AND CAST(value AS REAL) <= CAST(ref_high AS REAL))
  OR
  (status='low' AND ref_low IS NOT NULL AND ref_low <> '' AND CAST(value AS REAL) >= CAST(ref_low AS REAL));

SELECT id, panel, test_name, value, unit, ref_low, ref_high, status
FROM lab_results
WHERE unit LIKE '%1%'
   OR unit LIKE '%I%'
   OR test_name LIKE '%↑%'
   OR test_name LIKE '%↓%'
   OR test_name LIKE '%→%'
   OR test_name='度）'
   OR test_name LIKE '%备注%';
```
