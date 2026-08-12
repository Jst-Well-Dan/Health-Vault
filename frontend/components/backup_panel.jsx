const backupFetchJson = async (path, options = {}) => {
  const res = await fetch(path, options); let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) { const detail = data?.detail || `${path} · ${res.status}`; throw new Error(Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail); }
  return data;
};
const formatBackupSize = (size) => { const n = Number(size || 0); return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`; };

function BackupPanel({ onClose }) {
  const [info, setInfo] = React.useState(null); const [lastBackup, setLastBackup] = React.useState(null); const [busy, setBusy] = React.useState(false); const [notice, setNotice] = React.useState(''); const [error, setError] = React.useState('');
  const [importFile, setImportFile] = React.useState(null); const [importConfirm, setImportConfirm] = React.useState(false); const [importBusy, setImportBusy] = React.useState(false); const [importResult, setImportResult] = React.useState(null);
  React.useEffect(() => { const { body, documentElement } = document; const a = body.style.overflow; const b = documentElement.style.overflow; body.style.overflow = 'hidden'; documentElement.style.overflow = 'hidden'; return () => { body.style.overflow = a; documentElement.style.overflow = b; }; }, []);
  const refresh = React.useCallback(async () => { setError(''); try { setInfo(await backupFetchJson('/api/backups/info')); } catch (err) { setError(err.message || '读取备份信息失败'); } }, []);
  React.useEffect(() => { refresh(); }, [refresh]);
  const create = async () => { setBusy(true); setNotice(''); setError(''); try { const result = await backupFetchJson('/api/backups', { method: 'POST' }); setLastBackup(result); setNotice(`已创建备份：${result.filename || result.backup_path}`); await refresh(); } catch (err) { setError(err.message || '创建备份失败'); } finally { setBusy(false); } };
  const doImport = async (event) => {
    event.preventDefault();
    if (!importFile || !importConfirm) return;
    setImportBusy(true); setError(''); setNotice(''); setImportResult(null);
    const form = new FormData();
    form.append('file', importFile);
    try {
      const result = await backupFetchJson('/api/backups/import', { method: 'POST', body: form });
      setImportResult(result);
      setNotice('导入成功：当前数据库已切换，请重启应用后再继续使用。');
      setImportFile(null); setImportConfirm(false);
      await refresh();
    } catch (err) { setError(err.message || '导入失败'); }
    finally { setImportBusy(false); }
  };
  const backups = info?.backups || [];
  return <div className="modal-backdrop"><div className="daily-modal sketch shadow backup-panel" style={{ maxWidth: 820 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 12 }}><div><div className="sec-label">数据安全</div><div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>数据备份</div></div><Btn ghost onClick={onClose}>关闭</Btn></div>
    <div className="sketch" style={{ padding: 12, marginBottom: 12, background: 'color-mix(in oklab, var(--accent-2) 20%, var(--paper))' }}><strong>本地 SQLite 备份。</strong><div className="mono" style={{ marginTop: 6, color: 'var(--ink-soft)' }}>浏览器可创建、查看、下载备份，或导入一个 .db 文件切换当前数据库（导入前会自动备份当前库）。</div></div>
    {error && <div className="sketch" style={{ padding: 10, marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}{notice && <div className="sketch" style={{ padding: 10, marginBottom: 12 }}>{notice}</div>}
    <div className="daily-form" style={{ display: 'grid', gap: 10 }}><label><span>当前数据库</span><input readOnly value={info?.database_path || '正在读取...'} /></label><label><span>备份目录</span><input readOnly value={info?.backup_dir || '正在读取...'} /></label></div>
    {lastBackup && <div className="sketch" style={{ padding: 12, marginTop: 12 }}><div className="sec-label">最近创建</div><div className="mono">{lastBackup.backup_path}</div><div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 4 }}>{formatBackupSize(lastBackup.size_bytes)} · {lastBackup.created_at}</div></div>}
    <DashLabel right={`${backups.length} 个`}>近期备份</DashLabel><div className="backup-list" style={{ display: 'grid', gap: 8, maxHeight: 260, overflow: 'auto' }}>{backups.length === 0 && <div className="mono" style={{ color: 'var(--ink-soft)' }}>暂无备份文件。</div>}{backups.map(item => <div key={item.backup_path} className="sketch" style={{ padding: 10 }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}><span style={{ fontWeight: 700 }}>{item.filename}</span><a href={`/api/backups/download/${encodeURIComponent(item.filename)}`} download={item.filename}><Btn ghost>下载</Btn></a></div><div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 4 }}>{formatBackupSize(item.size_bytes)} · {item.created_at}</div><div className="mono" style={{ marginTop: 4, overflowWrap: 'anywhere' }}>{item.backup_path}</div></div>)}</div>
    <DashLabel>导入备份文件（切换当前数据库）</DashLabel>
    <form className="daily-form" style={{ display: 'grid', gap: 10, marginBottom: 12 }} onSubmit={doImport}>
      <label><span>选择 .db 文件</span><input type="file" accept=".db" onChange={event => { setImportFile(event.target.files?.[0] || null); setImportResult(null); }} /></label>
      <label className="mono" style={{ fontWeight: 400, display: 'flex', gap: 8, alignItems: 'flex-start' }}><input type="checkbox" checked={importConfirm} onChange={event => setImportConfirm(event.target.checked)} /><span>我已明白：导入会替换当前数据库，系统会先自动备份当前库；成功后需要重启应用。</span></label>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <Btn primary type="submit" disabled={importBusy || !importFile || !importConfirm}>{importBusy ? '导入中...' : '导入并切换'}</Btn>
      </div>
    </form>
    {importResult && <div className="sketch" style={{ padding: 12, marginBottom: 12 }}>
      <div className="sec-label">导入结果</div>
      <div className="mono">当前数据库已切换为：{importResult.imported_filename}</div>
      <div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 4 }}>恢复前备份：{importResult.pre_restore_backup.backup_path}</div>
      <div className="mono" style={{ color: 'var(--danger)', marginTop: 4 }}>请重启应用后再继续使用。</div>
    </div>}
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginTop: 16, flexWrap: 'wrap' }}><Btn ghost disabled={busy || importBusy} onClick={refresh}>刷新列表</Btn><Btn primary disabled={busy || importBusy} onClick={create}>{busy ? '备份中...' : '立即创建备份'}</Btn></div>
  </div></div>;
}
window.BackupPanel = BackupPanel;
