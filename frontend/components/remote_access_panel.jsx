const remoteFetchJson = async (path, options = {}) => {
  const res = await fetch(path, options); let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) { const detail = data?.detail || `${path} · ${res.status}`; throw new Error(Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail); }
  return data;
};

function RemoteAccessPanel({ onClose }) {
  const [info, setInfo] = React.useState(null);
  const [error, setError] = React.useState('');
  const [notice, setNotice] = React.useState('');
  const [busyAutostart, setBusyAutostart] = React.useState(false);

  React.useEffect(() => { const { body, documentElement } = document; const a = body.style.overflow; const b = documentElement.style.overflow; body.style.overflow = 'hidden'; documentElement.style.overflow = 'hidden'; return () => { body.style.overflow = a; documentElement.style.overflow = b; }; }, []);

  const refresh = React.useCallback(async () => {
    setError('');
    try { setInfo(await remoteFetchJson('/api/settings/system')); }
    catch (err) { setError(err.message || '读取设置失败'); }
  }, []);
  React.useEffect(() => { refresh(); }, [refresh]);

  const toggleAutostart = async (enabled) => {
    setBusyAutostart(true); setNotice(''); setError('');
    try {
      const result = await remoteFetchJson('/api/settings/autostart', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
      if (result.ok) setNotice(enabled ? '已启用开机自启。' : '已关闭开机自启。');
      else setError(result.message || '操作未成功');
      await refresh();
    } catch (err) { setError(err.message || '设置开机自启失败'); }
    finally { setBusyAutostart(false); }
  };

  return <div className="modal-backdrop"><div className="daily-modal sketch shadow" style={{ maxWidth: 720 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 12 }}>
      <div><div className="sec-label">本机设置</div><div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>本机与自启</div></div>
      <Btn ghost onClick={onClose}>关闭</Btn>
    </div>

    {error && <div className="sketch" style={{ padding: 10, marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}
    {notice && <div className="sketch" style={{ padding: 10, marginBottom: 12 }}>{notice}</div>}

    <DashLabel>监听地址</DashLabel>
    <div className="sketch" style={{ padding: 12, marginBottom: 16 }}>
      <div className="mono">本机模式：仅监听 <strong>127.0.0.1</strong>，远程访问（Tailscale）已停用。</div>
      {info && <div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 6 }}>当前生效：{info.current_host}{info.bind_warning ? `（${info.bind_warning}）` : ''}</div>}
    </div>

    <DashLabel>开机自启</DashLabel>
    {info && !info.autostart_supported && <div className="mono" style={{ color: 'var(--ink-soft)' }}>当前平台暂不支持网页端一键配置开机自启，请参考 README 手动配置。</div>}
    {info && info.autostart_supported && <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
      <Btn primary={!info.autostart_enabled} ghost={info.autostart_enabled} disabled={busyAutostart} onClick={() => toggleAutostart(false)}>关闭</Btn>
      <Btn primary={info.autostart_enabled} ghost={!info.autostart_enabled} disabled={busyAutostart} onClick={() => toggleAutostart(true)}>启用</Btn>
      {info.platform === 'Windows' && <span className="mono" style={{ color: 'var(--ink-soft)' }}>启用时会弹出 Windows 权限确认窗口，请点击"是"</span>}
    </div>}
  </div></div>;
}
window.RemoteAccessPanel = RemoteAccessPanel;
