const backupFetchJson = async (path, options = {}) => {
  const res = await fetch(path, options);
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const detail = data?.detail || `${path} · ${res.status}`;
    throw new Error(Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail);
  }
  return data;
};

const backupInfo = () => window.healthBackup?.info
  ? window.healthBackup.info()
  : backupFetchJson('/api/backups/info');

const backupCreate = () => window.healthBackup?.create
  ? window.healthBackup.create()
  : backupFetchJson('/api/backups', { method: 'POST' });

const backupValidate = (filename) => window.healthBackup?.validate(filename);
const backupRestore = (filename) => window.healthBackup?.restore(filename);

const formatBackupSize = (size) => {
  const n = Number(size || 0);
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
};

function BackupPanel({ onClose }) {
  const [info, setInfo] = React.useState(null);
  const [lastBackup, setLastBackup] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [validating, setValidating] = React.useState('');
  const [restoring, setRestoring] = React.useState('');
  const [validationResults, setValidationResults] = React.useState({});
  const [notice, setNotice] = React.useState('');
  const [error, setError] = React.useState('');
  const canRestore = Boolean(window.healthBackup?.validate && window.healthBackup?.restore);

  React.useEffect(() => {
    const { body, documentElement } = document;
    const prevBodyOverflow = body.style.overflow;
    const prevHtmlOverflow = documentElement.style.overflow;
    body.style.overflow = 'hidden';
    documentElement.style.overflow = 'hidden';
    return () => {
      body.style.overflow = prevBodyOverflow;
      documentElement.style.overflow = prevHtmlOverflow;
    };
  }, []);

  const refresh = React.useCallback(async () => {
    setError('');
    try {
      setInfo(await backupInfo());
    } catch (err) {
      setError(err.message || '读取备份信息失败');
    }
  }, []);

  React.useEffect(() => { refresh(); }, [refresh]);

  const create = async () => {
    setBusy(true);
    setNotice('');
    setError('');
    try {
      const result = await backupCreate();
      setLastBackup(result);
      setNotice(`已创建备份：${result.filename || result.backup_path}`);
      await refresh();
    } catch (err) {
      setError(err.message || '创建备份失败');
    } finally {
      setBusy(false);
    }
  };

  const openFolder = async () => {
    setNotice('');
    setError('');
    if (!window.healthBackup?.openFolder) {
      setNotice('当前环境不能直接打开文件夹，请按下方路径在文件管理器中打开。');
      return;
    }
    try {
      const result = await window.healthBackup.openFolder();
      if (result) setError(result);
    } catch (err) {
      setError(err.message || '打开备份文件夹失败');
    }
  };

  const validate = async (filename) => {
    if (!canRestore || !filename) return;
    setValidating(filename);
    setNotice('');
    setError('');
    try {
      const result = await backupValidate(filename);
      setValidationResults(prev => ({ ...prev, [filename]: result }));
      setNotice(`校验通过：${filename}`);
    } catch (err) {
      setError(err.message || '备份校验失败');
    } finally {
      setValidating('');
    }
  };

  const restore = async (filename) => {
    if (!canRestore || !filename) return;
    const confirmed = window.confirm([
      `确认恢复数据库备份「${filename}」？`,
      '恢复会关闭并重启后端；恢复前会自动创建当前数据库备份。',
      '只恢复数据库，不处理附件/报告文件；如果附件文件来自较新状态，可能出现孤儿文件或缺失引用，需要恢复后自行核对。',
      'Electron 主进程还会再次弹出原生确认框。',
    ].join('\n\n'));
    if (!confirmed) return;

    setRestoring(filename);
    setNotice('');
    setError('');
    try {
      const result = await backupRestore(filename);
      if (result?.cancelled) {
        setNotice('已取消恢复，未创建恢复前备份，也未修改数据库。');
      } else if (result?.ok) {
        setNotice(`数据库已从 ${result.restored_filename || filename} 恢复，应用后端已重启。恢复前备份：${result.pre_restore_filename || '已创建'}。请核对附件/报告引用。`);
        await refresh();
      } else {
        const pre = result?.pre_restore_filename ? `；恢复前备份：${result.pre_restore_filename}` : '';
        setError(`${result?.error || '恢复失败'}${pre}`);
      }
    } catch (err) {
      setError(err.message || '恢复失败');
    } finally {
      setRestoring('');
    }
  };

  const backups = info?.backups || [];
  return (
    <div className="modal-backdrop">
      <div className="daily-modal sketch shadow backup-panel" style={{ maxWidth: 820 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 12 }}>
          <div>
            <div className="sec-label">数据安全</div>
            <div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>数据备份</div>
          </div>
          <Btn ghost onClick={onClose}>关闭</Btn>
        </div>

        <div className="sketch" style={{ padding: 12, marginBottom: 12, background: 'color-mix(in oklab, var(--accent-2) 20%, var(--paper))' }}>
          <strong>本地 SQLite 备份与用户可控恢复。</strong>
          <div className="mono" style={{ marginTop: 6, color: 'var(--ink-soft)' }}>
            恢复是高风险操作：仅 Electron 桌面版提供，恢复前会校验备份并自动留存当前数据库；只恢复数据库，不回滚附件/报告文件。恢复后如果附件文件来自较新状态，可能出现孤儿文件或缺失引用，需要用户自行核对。
          </div>
          {!canRestore && (
            <div className="mono" style={{ marginTop: 6, color: 'var(--ink-soft)' }}>
              当前环境为浏览器/静态预览时保持只读，不提供数据库恢复入口。
            </div>
          )}
        </div>

        {error && <div className="sketch" style={{ padding: 10, marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}
        {notice && <div className="sketch" style={{ padding: 10, marginBottom: 12 }}>{notice}</div>}

        <div className="daily-form" style={{ display: 'grid', gap: 10 }}>
          <label><span>当前数据库</span><input readOnly value={info?.database_path || '正在读取...'} /></label>
          <label><span>备份目录</span><input readOnly value={info?.backup_dir || '正在读取...'} /></label>
        </div>

        {lastBackup && (
          <div className="sketch" style={{ padding: 12, marginTop: 12 }}>
            <div className="sec-label">最近创建</div>
            <div className="mono">{lastBackup.backup_path}</div>
            <div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 4 }}>
              {formatBackupSize(lastBackup.size_bytes)} · {lastBackup.created_at}
            </div>
          </div>
        )}

        <DashLabel right={`${backups.length} 个`}>近期备份</DashLabel>
        <div className="backup-list" style={{ display: 'grid', gap: 8, maxHeight: 260, overflow: 'auto' }}>
          {backups.length === 0 && <div className="mono" style={{ color: 'var(--ink-soft)' }}>暂无备份文件。</div>}
          {backups.map(item => {
            const validation = validationResults[item.filename];
            const actionBusy = busy || validating === item.filename || restoring === item.filename;
            return (
              <div key={item.backup_path} className="sketch" style={{ padding: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
                  <div style={{ fontWeight: 700 }}>{item.filename}</div>
                  {canRestore && (
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      <Btn ghost disabled={actionBusy} onClick={() => validate(item.filename)}>{validating === item.filename ? '校验中...' : '校验'}</Btn>
                      <Btn disabled={actionBusy} onClick={() => restore(item.filename)}>{restoring === item.filename ? '恢复中...' : '恢复'}</Btn>
                    </div>
                  )}
                </div>
                <div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 4 }}>{formatBackupSize(item.size_bytes)} · {item.created_at}</div>
                <div className="mono" style={{ marginTop: 4, overflowWrap: 'anywhere' }}>{item.backup_path}</div>
                {validation && (
                  <div className="mono" style={{ marginTop: 6, color: 'var(--ok)' }}>
                    integrity: {validation.schema?.integrity_check || 'ok'} · user_version: {validation.user_version ?? validation.schema?.user_version ?? 0} · core tables: {validation.schema?.tables?.length || 0}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginTop: 16, flexWrap: 'wrap' }}>
          <Btn ghost disabled={busy || Boolean(restoring)} onClick={refresh}>刷新列表</Btn>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Btn disabled={busy || Boolean(restoring)} onClick={openFolder}>打开备份文件夹</Btn>
            <Btn primary disabled={busy || Boolean(restoring)} onClick={create}>{busy ? '备份中...' : '立即创建备份'}</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

window.BackupPanel = BackupPanel;
