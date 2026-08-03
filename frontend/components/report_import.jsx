function ReportImportModal({ member, onClose, onImported }) {
  const bridge = window.healthReport;
  const [source, setSource] = React.useState(null);
  const [draft, setDraft] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const [result, setResult] = React.useState(null);

  if (!bridge) return null;

  const selectFile = async () => {
    setBusy(true); setError(''); setResult(null); setDraft('');
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
      const proposal = await bridge.analyze(source, { key: member.key, name: member.name });
      setDraft(JSON.stringify(proposal, null, 2));
    } catch (err) { setError(err.message || String(err)); }
    finally { setBusy(false); }
  };

  const commit = async () => {
    let proposal;
    try { proposal = JSON.parse(draft); }
    catch { setError('解析结果不是有效 JSON，请修正后再写入。'); return; }
    if (!proposal?.visit?.date) { setError('请确认报告日期后再写入。'); return; }
    const payload = { ...proposal, source_id: source.id, member_key: member.key };
    setBusy(true); setError('');
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
          {source && !draft && <div className="report-import-actions"><Btn primary onClick={analyze} disabled={busy}>解析并生成导入草稿</Btn></div>}
          {draft && <>
            <label className="report-import-label">请核对并按需修正以下结构化草稿。只有点击“确认归档并写入”才会改动数据库。</label>
            <textarea className="report-import-json" value={draft} onChange={(event) => setDraft(event.target.value)} spellCheck="false" />
            <div className="report-import-actions"><Btn primary onClick={commit} disabled={busy}>确认归档并写入</Btn></div>
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
