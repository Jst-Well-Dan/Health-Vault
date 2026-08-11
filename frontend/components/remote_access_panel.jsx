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
  const [busyHost, setBusyHost] = React.useState(false);
  const [busyAutostart, setBusyAutostart] = React.useState(false);
  const [busyPassword, setBusyPassword] = React.useState(false);
  const [pwForm, setPwForm] = React.useState({ current: '', next: '', confirm: '' });
  const [pwError, setPwError] = React.useState('');

  React.useEffect(() => { const { body, documentElement } = document; const a = body.style.overflow; const b = documentElement.style.overflow; body.style.overflow = 'hidden'; documentElement.style.overflow = 'hidden'; return () => { body.style.overflow = a; documentElement.style.overflow = b; }; }, []);

  const refresh = React.useCallback(async () => {
    setError('');
    try { setInfo(await remoteFetchJson('/api/settings/system')); }
    catch (err) { setError(err.message || '读取设置失败'); }
  }, []);
  React.useEffect(() => { refresh(); }, [refresh]);

  const toggleHost = async (enableRemote) => {
    setBusyHost(true); setNotice(''); setError('');
    try {
      const result = await remoteFetchJson('/api/settings/host', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enable_remote: enableRemote }) });
      setNotice(result.restart_required ? `设置已保存，将在重启应用后监听 ${result.host}。` : `设置已保存，正在监听 ${result.host}。`);
      await refresh();
    } catch (err) { setError(err.message || '修改监听地址失败'); }
    finally { setBusyHost(false); }
  };

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

  const submitPassword = async (e) => {
    e.preventDefault();
    setPwError(''); setNotice('');
    if (pwForm.next !== pwForm.confirm) { setPwError('两次输入的新密码不一致'); return; }
    setBusyPassword(true);
    try {
      const result = await remoteFetchJson('/api/settings/password', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: pwForm.current, new_password: pwForm.next }),
      });
      if (result.warning) { setPwError(result.warning); setBusyPassword(false); return; }
      window.location.href = '/login';
    } catch (err) { setPwError(err.message || '修改密码失败'); setBusyPassword(false); }
  };

  const tailscale = info?.tailscale;
  const remoteEnabled = !!info?.pending_host && info.pending_host !== '127.0.0.1';

  return <div className="modal-backdrop"><div className="daily-modal sketch shadow" style={{ maxWidth: 720 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 12 }}>
      <div><div className="sec-label">远程访问</div><div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>Tailscale</div></div>
      <Btn ghost onClick={onClose}>关闭</Btn>
    </div>

    {error && <div className="sketch" style={{ padding: 10, marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}
    {notice && <div className="sketch" style={{ padding: 10, marginBottom: 12 }}>{notice}</div>}

    <DashLabel>Tailscale 检测</DashLabel>
    <div className="sketch" style={{ padding: 12, marginBottom: 16 }}>
      {!tailscale && <div className="mono" style={{ color: 'var(--ink-soft)' }}>正在检测...</div>}
      {tailscale && !tailscale.installed && <div className="mono">未检测到 Tailscale。请先前往 tailscale.com 下载安装并登录后再回到这里。</div>}
      {tailscale && tailscale.installed && !tailscale.connected && <div className="mono">已安装 Tailscale，但尚未连接。请先在 Tailscale 客户端登录。</div>}
      {tailscale && tailscale.connected && <div className="mono">已连接，Tailscale IP：<strong>{tailscale.ip}</strong></div>}
    </div>

    <DashLabel>手机访问（仅 Tailscale）</DashLabel>
    <div style={{ display: 'flex', gap: 10, marginBottom: 6 }}>
      <Btn primary={!remoteEnabled} ghost={remoteEnabled} disabled={busyHost} onClick={() => toggleHost(false)}>仅本机</Btn>
      <Btn primary={remoteEnabled} ghost={!remoteEnabled} disabled={busyHost} onClick={() => toggleHost(true)}>允许 Tailscale 访问</Btn>
    </div>
    {info && <div className="mono" style={{ color: 'var(--ink-soft)', marginBottom: 16 }}>当前生效：{info.current_host}{info.restart_required ? `（重启后将改为 ${info.pending_host}）` : ''}</div>}

    <DashLabel>修改家庭共享密码</DashLabel>
    <form className="daily-form" style={{ display: 'grid', gap: 10, marginBottom: 16 }} onSubmit={submitPassword}>
      {pwError && <div className="sketch" style={{ padding: 10, color: 'var(--danger)' }}>{pwError}</div>}
      <label><span>当前密码</span><input type="password" value={pwForm.current} onChange={e => setPwForm({ ...pwForm, current: e.target.value })} /></label>
      <label><span>新密码</span><input type="password" value={pwForm.next} onChange={e => setPwForm({ ...pwForm, next: e.target.value })} /></label>
      <label><span>确认新密码</span><input type="password" value={pwForm.confirm} onChange={e => setPwForm({ ...pwForm, confirm: e.target.value })} /></label>
      <Btn primary type="submit" disabled={busyPassword}>{busyPassword ? '修改中...' : '修改密码'}</Btn>
    </form>

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
