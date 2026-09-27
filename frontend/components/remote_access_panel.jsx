const remoteFetchJson = async (path, options = {}) => {
  const res = await fetch(path, options); let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) { const detail = data?.detail || `${path} · ${res.status}`; throw new Error(Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail); }
  return data;
};

const _isLoopHost = (h) => ['127.0.0.1', '::1', 'localhost'].includes(h);
const _hostsOf = (info) => info.current_hosts || (info.current_host ? [info.current_host] : []);
const _pendingOf = (info) => info.pending_hosts || (info.pending_host ? [info.pending_host] : []);
const _remoteOf = (hosts) => (hosts || []).find((h) => h && !_isLoopHost(h));

function RemoteAccessPanel({ onClose }) {
  const [info, setInfo] = React.useState(null);
  const [error, setError] = React.useState('');
  const [notice, setNotice] = React.useState('');
  const [busyAutostart, setBusyAutostart] = React.useState(false);
  const [busyRemote, setBusyRemote] = React.useState(false);
  const [busyRestart, setBusyRestart] = React.useState(false);

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

    <DashLabel>监听地址（Tailscale-only）</DashLabel>
    <div className="sketch" style={{ padding: 12, marginBottom: 16 }}>
      <div className="mono">只允许 <strong>127.0.0.1</strong> 或 Tailscale <strong>100.x</strong>，拒绝 0.0.0.0/局域网。无登录鉴权，tailnet 内设备直接读写。</div>
      {info && <div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 6 }}>当前生效：{_hostsOf(info).join(' + ')}{_pendingOf(info).join() !== _hostsOf(info).join() ? ` → 待重启为 ${_pendingOf(info).join(' + ')}` : ''}{info.bind_warning ? `（${info.bind_warning}）` : ''}</div>}
      {info && <div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 6 }}>本机用 http://127.0.0.1:{window.location.port || '8000'}（免代理配置）{_remoteOf(_pendingOf(info)) || _remoteOf(_hostsOf(info)) ? `；手机用 http://${_remoteOf(_pendingOf(info)) || _remoteOf(_hostsOf(info))}:${window.location.port || '8000'}` : '（仅本机）'}</div>}
      {info && <div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 6 }}>Tailscale：{!info.tailscale?.installed ? '未安装' : !info.tailscale?.connected ? '未连接' : `已连接 ${info.tailscale.ip}`}</div>}
      <div style={{ display: 'flex', gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
        <Btn primary disabled={busyRemote || !info?.tailscale?.connected} onClick={async () => { setBusyRemote(true); setNotice(''); setError(''); try { const r = await remoteFetchJson('/api/settings/host', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enable_remote: true }) }); setNotice(`已切到 Tailscale ${r.host}，点“立即重启”生效（约10秒）。`); await refresh(); } catch (err) { setError(err.message || '启用失败'); } finally { setBusyRemote(false); } }}>{busyRemote ? '处理中…' : '允许 Tailscale 访问'}</Btn>
        <Btn ghost disabled={busyRemote} onClick={async () => { setBusyRemote(true); setNotice(''); setError(''); try { await remoteFetchJson('/api/settings/host', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enable_remote: false }) }); setNotice('已切回本机 127.0.0.1，点“立即重启”生效。'); await refresh(); } catch (err) { setError(err.message || '切回失败'); } finally { setBusyRemote(false); } }}>切回本机</Btn>
        {info?.restart_required && <Btn primary disabled={busyRestart || (!!info?.tailscale && !info.tailscale.connected && !!_remoteOf(_pendingOf(info)))} onClick={async () => { setBusyRestart(true); setError(''); try { await window.relaunchApp(_pendingOf(info)); } catch (err) { setError(err.message || '重启失败'); setBusyRestart(false); } }}>{busyRestart ? '重启中…' : '立即重启'}</Btn>}
      </div>
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
