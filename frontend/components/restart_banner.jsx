// Persistent "restart needed / bind warning" banner plus the one-click
// self-restart flow (relaunchApp). Loaded as a Babel JSX script before the
// app shell; exposes window.RestartBanner and window.relaunchApp.

const _probeBase = (base) => new Promise((resolve) => {
  // Image probe works cross-origin without CORS: any 2xx fires onload.
  const img = new Image();
  const timer = setTimeout(() => { img.src = ''; resolve(false); }, 4000);
  img.onload = () => { clearTimeout(timer); resolve(true); };
  img.onerror = () => { clearTimeout(timer); resolve(false); };
  img.src = `${base}/api/meta?t=${Date.now()}`;
});

const _waitForServerUp = async (base, timeoutMs) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await _probeBase(base)) return;
    await new Promise((r) => setTimeout(r, 2500));
  }
  throw new Error(`等待 ${base} 就绪超时`);
};

window.relaunchApp = async (pendingHost) => {
  const port = window.location.port || '8000';
  const target = `${window.location.protocol}//${pendingHost}${port ? `:${port}` : ''}`;
  const overlay = document.createElement('div');
  overlay.className = 'restart-overlay';
  overlay.innerHTML = `<div class="restart-overlay-card">
      <div class="restart-overlay-title">正在重启应用…</div>
      <div class="restart-overlay-sub">新地址 ${target} 就绪后会自动跳转（约 10 秒），请稍候</div>
    </div>`;
  document.body.appendChild(overlay);
  try {
    const res = await fetch('/api/settings/restart', { method: 'POST' });
    if (!res.ok) {
      let detail = `重启失败 · ${res.status}`;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* ignore */ }
      throw new Error(detail);
    }
    await _waitForServerUp(target, 70000);
    window.location.assign(`${target}/`);
    // Navigation replaces this page; leave the overlay up.
  } catch (err) {
    overlay.remove();
    throw err;
  }
};

function RestartBanner() {
  const [info, setInfo] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const refresh = React.useCallback(async () => {
    try {
      const res = await fetch('/api/settings/system');
      if (res.ok) setInfo(await res.json());
    } catch (_) { /* server may be mid-restart; retry on next tick */ }
  }, []);
  React.useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => clearInterval(timer);
  }, [refresh]);

  if (!info) return null;
  const showAction = info.restart_required;
  const showNotice = !showAction && !!info.bind_warning;
  if (!showAction && !showNotice) return null;

  const text = showAction
    ? `监听地址变更未生效：当前 ${info.current_host}，重启后为 ${info.pending_host}。${info.bind_warning ? `（${info.bind_warning}）` : ''}`
    : info.bind_warning;

  // When Tailscale is down the pending remote address cannot be bound yet —
  // offering restart would kill the working local server for nothing.
  const tailscaleDown = !!(info.tailscale && !info.tailscale.connected) && info.pending_host !== '127.0.0.1';

  const doRestart = async () => {
    setBusy(true); setError('');
    try {
      await window.relaunchApp(info.pending_host);
    } catch (err) {
      setError(err.message || '重启失败，请手动重启应用');
      setBusy(false);
    }
  };

  return (
    <div className={`restart-banner ${showAction ? 'restart-banner-action' : ''}`} role="status">
      <div className="restart-banner-text">{text}</div>
      {showAction && !tailscaleDown && <button className="restart-banner-btn" disabled={busy} onClick={doRestart}>{busy ? '重启中…' : '立即重启'}</button>}
      {showAction && tailscaleDown && <span className="restart-banner-hint">请先连接 Tailscale 后再重启</span>}
      {error && <div className="restart-banner-error">{error}</div>}
    </div>
  );
}
window.RestartBanner = RestartBanner;
