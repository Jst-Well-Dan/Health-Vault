const REPORT_TYPE_OPTIONS = ['体检', '就医', '复查', '疫苗'];
const LAB_STATUS_OPTIONS = [
  ['unknown', '未知'],
  ['normal', '正常'],
  ['high', '偏高'],
  ['low', '偏低'],
  ['abnormal', '异常'],
];

const isBlank = (value) => !value || !String(value).trim();

const emptyLabRow = () => ({ panel: '', test_name: '', value: '', unit: '', ref_low: '', ref_high: '', status: 'unknown' });

const formFromProposal = (proposal) => ({
  date: proposal?.visit?.date || '',
  type: proposal?.visit?.type || '体检',
  hospital: proposal?.visit?.hospital || '',
  department: proposal?.visit?.department || '',
  doctor: proposal?.visit?.doctor || '',
  chief_complaint: proposal?.visit?.chief_complaint || '',
  severity: proposal?.visit?.severity || '',
  diagnosis_text: Array.isArray(proposal?.visit?.diagnosis) ? proposal.visit.diagnosis.join('\n') : '',
  notes: proposal?.visit?.notes || '',
  note_full: proposal?.visit?.note_full || '',
  attachment_title: proposal?.attachment_title || '',
  attachment_tag: proposal?.attachment_tag || '体检报告',
});

const labsFromProposal = (proposal) => (Array.isArray(proposal?.labs) ? proposal.labs : []).map((lab) => ({
  panel: lab.panel || '',
  test_name: lab.test_name || '',
  value: lab.value || '',
  unit: lab.unit || '',
  ref_low: lab.ref_low || '',
  ref_high: lab.ref_high || '',
  status: lab.status || 'unknown',
}));

const namesLooselyMatch = (a, b) => {
  const na = String(a || '').trim().replace(/\s+/g, '');
  const nb = String(b || '').trim().replace(/\s+/g, '');
  if (!na || !nb) return true;
  return na === nb || na.includes(nb) || nb.includes(na);
};

const FieldLabel = ({ label, required, flagged, className = '', children }) => (
  <label className={`${flagged ? 'field-flag' : ''} ${className}`.trim()}>
    <span>{label}{required && ' *'}{flagged && <b className="field-flag-badge">AI 未识别</b>}</span>
    {children}
  </label>
);

function ReportImportModal({ member, onClose, onImported }) {
  const bridge = window.healthReport;
  const [source, setSource] = React.useState(null);
  const [proposal, setProposal] = React.useState(null);
  const [form, setForm] = React.useState(null);
  const [labs, setLabs] = React.useState([]);
  const [nameOverride, setNameOverride] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const [result, setResult] = React.useState(null);

  if (!bridge) return null;

  const reset = () => { setProposal(null); setForm(null); setLabs([]); setNameOverride(false); };

  const selectFile = async () => {
    setBusy(true); setError(''); setResult(null); reset();
    try {
      const next = await bridge.select();
      if (next) setSource(next);
    } catch (err) { setError(err.message || String(err)); }
    finally { setBusy(false); }
  };

  const analyze = async () => {
    if (!source) return;
    setBusy(true); setError('');
    try {
      const next = await bridge.analyze(source, { key: member.key, name: member.name });
      setProposal(next);
      setForm(formFromProposal(next));
      setLabs(labsFromProposal(next));
      setNameOverride(false);
    } catch (err) { setError(err.message || String(err)); }
    finally { setBusy(false); }
  };

  const reanalyze = () => {
    if (busy) return;
    if (proposal && !window.confirm('重新解析会覆盖你已经修改的内容，确定继续吗？')) return;
    analyze();
  };

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));
  const setLabField = (index, key, value) => setLabs((prev) => prev.map((lab, i) => (i === index ? { ...lab, [key]: value } : lab)));
  const addLabRow = () => setLabs((prev) => [...prev, emptyLabRow()]);
  const removeLabRow = (index) => setLabs((prev) => prev.filter((_, i) => i !== index));
  const blockEnter = (event) => { if (event.key === 'Enter') event.preventDefault(); };

  const reportedName = proposal?.patient_name_on_report || '';
  const nameMismatch = !isBlank(reportedName) && !namesLooselyMatch(reportedName, member.name) && !namesLooselyMatch(reportedName, member.full_name);

  const flagged = form ? {
    date: isBlank(form.date),
    hospital: isBlank(form.hospital),
    department: isBlank(form.department),
    doctor: isBlank(form.doctor),
    chief_complaint: isBlank(form.chief_complaint),
    severity: isBlank(form.severity),
    diagnosis: isBlank(form.diagnosis_text),
    notes: isBlank(form.notes),
  } : {};

  const buildPayload = () => {
    const diagnosis = form.diagnosis_text.split(/[\n,，]/).map((s) => s.trim()).filter(Boolean);
    const visit = {
      date: form.date.trim(),
      type: form.type.trim() || '体检',
      hospital: form.hospital.trim() || null,
      department: form.department.trim() || null,
      doctor: form.doctor.trim() || null,
      chief_complaint: form.chief_complaint.trim() || null,
      severity: form.severity || null,
      diagnosis,
      notes: form.notes.trim() || null,
      note_full: form.note_full.trim() || null,
    };
    const labsPayload = labs
      .filter((lab) => !isBlank(lab.test_name))
      .map((lab) => ({
        panel: lab.panel.trim() || '其他',
        test_name: lab.test_name.trim(),
        value: lab.value.trim() || null,
        unit: lab.unit.trim() || null,
        ref_low: lab.ref_low.trim() || null,
        ref_high: lab.ref_high.trim() || null,
        status: lab.status || 'unknown',
      }));
    return {
      visit,
      labs: labsPayload,
      attachment_title: form.attachment_title.trim() || null,
      attachment_tag: form.attachment_tag.trim() || '体检报告',
    };
  };

  const commit = async () => {
    setError('');
    if (isBlank(form.date) || !/^\d{4}-\d{2}-\d{2}$/.test(form.date.trim())) {
      setError('请填写报告日期（格式 YYYY-MM-DD）后再写入。');
      return;
    }
    if (nameMismatch && !nameOverride) {
      setError('报告上的姓名与当前成员不一致，请先核实（见上方提示）。');
      return;
    }
    const payload = { ...buildPayload(), source_id: source.id, member_key: member.key };
    setBusy(true);
    try {
      const dryRun = await bridge.dryRun(payload);
      setBusy(false);
      if (!window.confirm(`dry-run 通过：将新增 ${dryRun.visit_count} 条就诊、${dryRun.lab_count} 条指标和 ${dryRun.attachment_count} 份附件。\n\n确认把「${source.filename}」写入 ${member.name} 的健康档案吗？应用将归档原件并创建数据库备份。`)) return;
      setBusy(true);
      const next = await bridge.commit(payload);
      setResult(next);
      await onImported?.(next);
    } catch (err) { setError(err.message || String(err)); }
    finally { setBusy(false); }
  };

  return (
    <div className="modal-backdrop report-import-backdrop" role="dialog" aria-modal="true" aria-label="导入体检报告">
      <div className="daily-modal sketch shadow report-import-modal">
        <div className="report-import-header">
          <div><div className="sec-label">报告导入</div><h3>导入体检报告</h3></div>
          <button className="report-import-close" onClick={onClose} disabled={busy} aria-label="关闭">×</button>
        </div>

        {!result && <>
          <p className="report-import-help">选择 PDF 或图片后，原件会先暂存于本机。解析会把报告页面发送给你在健康助手中配置的视觉模型；请确认你接受该模型服务的隐私政策。</p>
          <div className="report-import-actions">
            <Btn primary onClick={selectFile} disabled={busy}>{source ? '重新选择报告' : '选择报告文件'}</Btn>
            {source && <span className="mono">{source.filename} · {source.page_count} 页</span>}
          </div>
          {source && !form && <div className="report-import-actions"><Btn primary onClick={analyze} disabled={busy}>解析并生成导入草稿</Btn></div>}

          {form && <>
            <label className="report-import-label">请核对以下信息。标有「AI 未识别」的字段是模型没能从报告里读出来的内容，请补充或修正后再写入；其余字段也建议核对一遍。</label>

            {nameMismatch && (
              <div className="report-import-name-warning">
                报告上写的姓名是「{reportedName}」，与当前成员「{member.full_name || member.name}」不一致。
                <label className="report-import-name-ack">
                  <input type="checkbox" checked={nameOverride} onChange={(e) => setNameOverride(e.target.checked)} />
                  <span>我已核实，这份报告确实属于「{member.name}」</span>
                </label>
              </div>
            )}

            <form className="daily-form report-import-form" onSubmit={(e) => { e.preventDefault(); commit(); }}>
              <FieldLabel label="日期" required flagged={flagged.date}>
                <input type="date" value={form.date} onChange={(e) => setField('date', e.target.value)} />
              </FieldLabel>
              <label><span>类型</span>
                <input list="report-import-type-options" value={form.type} onChange={(e) => setField('type', e.target.value)} />
                <datalist id="report-import-type-options">{REPORT_TYPE_OPTIONS.map((t) => <option key={t} value={t} />)}</datalist>
              </label>
              <FieldLabel label="医院/机构" flagged={flagged.hospital}>
                <input value={form.hospital} onChange={(e) => setField('hospital', e.target.value)} placeholder="例如：社区医院" />
              </FieldLabel>
              <FieldLabel label="科室" flagged={flagged.department}>
                <input value={form.department} onChange={(e) => setField('department', e.target.value)} placeholder="例如：内科" />
              </FieldLabel>
              <FieldLabel label="医生" flagged={flagged.doctor}>
                <input value={form.doctor} onChange={(e) => setField('doctor', e.target.value)} />
              </FieldLabel>
              <FieldLabel label="严重程度" flagged={flagged.severity}>
                <select value={form.severity} onChange={(e) => setField('severity', e.target.value)}>
                  <option value="">未标记</option>
                  <option value="轻微">轻微</option>
                  <option value="一般">一般</option>
                  <option value="严重">严重</option>
                </select>
              </FieldLabel>
              <FieldLabel label="主诉/原因" flagged={flagged.chief_complaint} className="span-2">
                <input value={form.chief_complaint} onChange={(e) => setField('chief_complaint', e.target.value)} placeholder="例如：年度体检、咳嗽复诊" />
              </FieldLabel>
              <FieldLabel label="诊断/结论（每行或逗号分隔）" flagged={flagged.diagnosis} className="span-2">
                <textarea rows="3" value={form.diagnosis_text} onChange={(e) => setField('diagnosis_text', e.target.value)} />
              </FieldLabel>
              <FieldLabel label="备注" flagged={flagged.notes} className="span-2">
                <textarea rows="3" value={form.notes} onChange={(e) => setField('notes', e.target.value)} />
              </FieldLabel>
              <label className="span-2"><span>完整记录（选填，留空则自动生成摘要）</span>
                <textarea rows="4" value={form.note_full} onChange={(e) => setField('note_full', e.target.value)} placeholder="可粘贴报告原文或人工整理后的完整内容" />
              </label>

              <div className="span-2 report-import-labs-head">
                <span className="report-import-label" style={{ margin: 0 }}>检验指标</span>
                <Btn ghost onClick={addLabRow}>+ 添加一行</Btn>
              </div>
              <div className="span-2 report-import-labs-wrap">
                <table className="report-import-labs">
                  <thead><tr>
                    <th>分组</th><th>项目</th><th>结果</th><th>单位</th><th>参考下限</th><th>参考上限</th><th>状态</th><th></th>
                  </tr></thead>
                  <tbody>
                    {labs.map((lab, i) => {
                      const rowFlag = isBlank(lab.test_name) || isBlank(lab.value);
                      return (
                        <tr key={i} className={rowFlag ? 'field-flag' : ''}>
                          <td><input value={lab.panel} onKeyDown={blockEnter} onChange={(e) => setLabField(i, 'panel', e.target.value)} /></td>
                          <td><input value={lab.test_name} onKeyDown={blockEnter} onChange={(e) => setLabField(i, 'test_name', e.target.value)} /></td>
                          <td><input value={lab.value} onKeyDown={blockEnter} onChange={(e) => setLabField(i, 'value', e.target.value)} /></td>
                          <td><input value={lab.unit} onKeyDown={blockEnter} onChange={(e) => setLabField(i, 'unit', e.target.value)} /></td>
                          <td><input value={lab.ref_low} onKeyDown={blockEnter} onChange={(e) => setLabField(i, 'ref_low', e.target.value)} /></td>
                          <td><input value={lab.ref_high} onKeyDown={blockEnter} onChange={(e) => setLabField(i, 'ref_high', e.target.value)} /></td>
                          <td><select value={lab.status} onChange={(e) => setLabField(i, 'status', e.target.value)}>{LAB_STATUS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></td>
                          <td><button type="button" className="lab-remove" onClick={() => removeLabRow(i)} aria-label="删除该行">×</button></td>
                        </tr>
                      );
                    })}
                    {!labs.length && <tr><td colSpan="8" className="report-import-labs-empty">未识别到检验指标，可点击上方「添加一行」手动录入。</td></tr>}
                  </tbody>
                </table>
              </div>

              <label><span>附件标题</span><input value={form.attachment_title} onChange={(e) => setField('attachment_title', e.target.value)} placeholder="留空则使用主诉或“体检报告”" /></label>
              <label><span>附件标签</span><input value={form.attachment_tag} onChange={(e) => setField('attachment_tag', e.target.value)} /></label>

              <div className="form-actions">
                <Btn ghost type="button" onClick={reanalyze} disabled={busy}>重新解析</Btn>
                <Btn primary type="submit" disabled={busy}>确认归档并写入</Btn>
              </div>
            </form>

            <details className="report-import-raw">
              <summary>查看模型原始识别结果（只读 JSON，供核对用）</summary>
              <pre>{JSON.stringify(proposal, null, 2)}</pre>
            </details>
          </>}
        </>}

        {busy && <div className="mono report-import-status">正在处理，请稍候…</div>}
        {error && <div className="report-import-error">{error}</div>}
        {result && <div className="report-import-success">
          <h4>导入完成</h4>
          <p>新增就诊记录 #{result.visit_id}、检验指标 {result.lab_count} 条、附件 1 份。</p>
          <p className="mono">数据库：{result.database_path}<br />备份：{result.backup_path}</p>
          <Btn primary onClick={onClose}>完成</Btn>
        </div>}
      </div>
    </div>
  );
}
