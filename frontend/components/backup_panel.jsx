const backupFetchJson = async (path, options = {}) => {
  const res = await fetch(path, options); let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) { const detail = data?.detail || `${path} · ${res.status}`; throw new Error(Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail); }
  return data;
};
const formatBackupSize = (size) => { const n = Number(size || 0); return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`; };

function BackupPanel({ onClose }) {
  const [info, setInfo] = React.useState(null); const [lastBackup, setLastBackup] = React.useState(null); const [busy, setBusy] = React.useState(false); const [notice, setNotice] = React.useState(''); const [error, setError] = React.useState('');
  React.useEffect(() => { const { body, documentElement } = document; const a = body.style.overflow; const b = documentElement.style.overflow; body.style.overflow = 'hidden'; documentElement.style.overflow = 'hidden'; return () => { body.style.overflow = a; documentElement.style.overflow = b; }; }, []);
  const refresh = React.useCallback(async () => { setError(''); try { setInfo(await backupFetchJson('/api/backups/info')); } catch (err) { setError(err.message || '读取备份信息失败'); } }, []);
  React.useEffect(() => { refresh(); }, [refresh]);
  const create = async () => { setBusy(true); setNotice(''); setError(''); try { const result = await backupFetchJson('/api/backups', { method: 'POST' }); setLastBackup(result); setNotice(`已创建备份：${result.filename || result.backup_path}`); await refresh(); } catch (err) { setError(err.message || '创建备份失败'); } finally { setBusy(false); } };
  const backups = info?.backups || [];
  return <div className="modal-backdrop"><div className="daily-modal sketch shadow backup-panel" style={{ maxWidth: 820 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 12 }}><div><div className="sec-label">数据安全</div><div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>数据备份</div></div><Btn ghost onClick={onClose}>关闭</Btn></div>
    <div className="sketch" style={{ padding: 12, marginBottom: 12, background: 'color-mix(in oklab, var(--accent-2) 20%, var(--paper))' }}><strong>本地 SQLite 备份。</strong><div className="mono" style={{ marginTop: 6, color: 'var(--ink-soft)' }}>浏览器可创建和查看备份；数据库恢复只能在保存数据的电脑上通过本地维护命令执行，不提供手机端恢复入口。</div></div>
    {error && <div className="sketch" style={{ padding: 10, marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}{notice && <div className="sketch" style={{ padding: 10, marginBottom: 12 }}>{notice}</div>}
    <div className="daily-form" style={{ display: 'grid', gap: 10 }}><label><span>当前数据库</span><input readOnly value={info?.database_path || '正在读取...'} /></label><label><span>备份目录</span><input readOnly value={info?.backup_dir || '正在读取...'} /></label></div>
    {lastBackup && <div className="sketch" style={{ padding: 12, marginTop: 12 }}><div className="sec-label">最近创建</div><div className="mono">{lastBackup.backup_path}</div><div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 4 }}>{formatBackupSize(lastBackup.size_bytes)} · {lastBackup.created_at}</div></div>}
    <DashLabel right={`${backups.length} 个`}>近期备份</DashLabel><div className="backup-list" style={{ display: 'grid', gap: 8, maxHeight: 260, overflow: 'auto' }}>{backups.length === 0 && <div className="mono" style={{ color: 'var(--ink-soft)' }}>暂无备份文件。</div>}{backups.map(item => <div key={item.backup_path} className="sketch" style={{ padding: 10 }}><div style={{ fontWeight: 700 }}>{item.filename}</div><div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 4 }}>{formatBackupSize(item.size_bytes)} · {item.created_at}</div><div className="mono" style={{ marginTop: 4, overflowWrap: 'anywhere' }}>{item.backup_path}</div></div>)}</div>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginTop: 16, flexWrap: 'wrap' }}><Btn ghost disabled={busy} onClick={refresh}>刷新列表</Btn><Btn primary disabled={busy} onClick={create}>{busy ? '备份中...' : '立即创建备份'}</Btn></div>
  </div></div>;
}
window.BackupPanel = BackupPanel;
