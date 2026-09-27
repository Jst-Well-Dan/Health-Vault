const backupFetchJson = async (path, options = {}) => {
  const res = await fetch(path, options); let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) { const detail = data?.detail || `${path} · ${res.status}`; throw new Error(Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail); }
  return data;
};
const formatBackupSize = (size) => { const n = Number(size || 0); return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`; };

function BackupPanel({ onClose }) {
  const [info, setInfo] = React.useState(null); const [busy, setBusy] = React.useState(false); const [notice, setNotice] = React.useState(''); const [error, setError] = React.useState('');
  const [importFile, setImportFile] = React.useState(null); const [importBusy, setImportBusy] = React.useState(false); const [importResult, setImportResult] = React.useState(null);
  React.useEffect(() => { const { body, documentElement } = document; const a = body.style.overflow; const b = documentElement.style.overflow; body.style.overflow = 'hidden'; documentElement.style.overflow = 'hidden'; return () => { body.style.overflow = a; documentElement.style.overflow = b; }; }, []);
  const refresh = React.useCallback(async () => { setError(''); try { setInfo(await backupFetchJson('/api/backups/info')); } catch (err) { setError(err.message || '读取备份信息失败'); } }, []);
  React.useEffect(() => { refresh(); }, [refresh]);
  const doExport = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      const res = await fetch('/api/backups/export-bundle');
      if (!res.ok) throw new Error(`导出失败 · ${res.status}`);
      const blob = await res.blob();
      const name = (res.headers.get('content-disposition') || '').match(/filename=\"?([^\";]+)\"?/)?.[1] || `health-vault-${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')}.zip`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = name; document.body.appendChild(link); link.click();
      link.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
      setNotice(`已导出：${name}（${formatBackupSize(blob.size)}，含数据库 + 报告 + 设置）。写库前的 .db 快照仍在后台自动保留。`);
    } catch (err) { setError(err.message || '导出失败'); }
    finally { setBusy(false); }
  };
  const doImport = async (event) => {
    event.preventDefault();
    if (!importFile) return;
    if (!window.confirm('导入会替换当前数据库、报告与设置（系统已自动备份当前库），成功后需要重启应用。继续导入？')) return;
    setImportBusy(true); setError(''); setNotice(''); setImportResult(null);
    const form = new FormData();
    form.append('file', importFile);
    try {
      const result = await backupFetchJson('/api/backups/import-bundle', { method: 'POST', body: form });
      setImportResult(result);
      setNotice('导入成功：数据库、报告与设置已切换，请重启应用后再继续使用。');
      setImportFile(null);
      await refresh();
    } catch (err) { setError(err.message || '导入失败'); }
    finally { setImportBusy(false); }
  };
  return <div className="modal-backdrop"><div className="daily-modal sketch shadow backup-panel" style={{ maxWidth: 820 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 12 }}><div><div className="sec-label">数据安全</div><div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>数据备份</div></div><Btn ghost onClick={onClose}>关闭</Btn></div>
    <div className="sketch" style={{ padding: 12, marginBottom: 12, background: 'color-mix(in oklab, var(--accent-2) 20%, var(--paper))' }}><strong>迁移包（.zip）：数据库 + 报告 + 设置。</strong><div className="mono" style={{ marginTop: 6, color: 'var(--ink-soft)' }}>导出手动点才生成；写库前的 .db 快照仍在后台自动保留14天（启动时自动清理）。导入前会自动备份当前库，成功后需重启。</div></div>
    {error && <div className="sketch" style={{ padding: 10, marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}{notice && <div className="sketch" style={{ padding: 10, marginBottom: 12 }}>{notice}</div>}
    <div className="daily-form" style={{ display: 'grid', gap: 10 }}><label><span>当前数据库</span><input readOnly value={info?.database_path || '正在读取...'} /></label></div>
    <DashLabel>导出迁移包</DashLabel>
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
      <Btn primary disabled={busy || importBusy} onClick={doExport}>{busy ? '打包中...' : '导出 .zip 迁移包'}</Btn>
    </div>
    <DashLabel>导入迁移包（切换到另一台电脑的数据）</DashLabel>
    <form className="daily-form" style={{ display: 'grid', gap: 10, marginBottom: 12 }} onSubmit={doImport}>
      <label><span>选择 .zip 迁移包</span><input type="file" accept=".zip" onChange={event => { setImportFile(event.target.files?.[0] || null); setImportResult(null); }} /></label>
      <div className="mono" style={{ color: 'var(--ink-soft)' }}>导入会替换当前数据库、报告与设置，系统会先自动备份当前库；成功后需要重启应用。</div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <Btn primary type="submit" disabled={importBusy || !importFile}>{importBusy ? '导入中...' : '导入并切换'}</Btn>
      </div>
    </form>
    {importResult && <div className="sketch" style={{ padding: 12, marginBottom: 12 }}>
      <div className="sec-label">导入结果</div>
      <div className="mono">当前数据已切换为：{importResult.imported_filename}</div>
      <div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 4 }}>恢复报告文件：{importResult.report_files_restored} 个 · 恢复前备份：{importResult.pre_restore_backup?.backup_path}</div>
      <div className="mono" style={{ color: 'var(--danger)', marginTop: 4 }}>请重启应用后再继续使用。</div>
    </div>}
  </div></div>;
}
window.BackupPanel = BackupPanel;
