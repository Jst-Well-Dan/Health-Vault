// Persistent "restart needed / bind warning" banner plus the one-click
// self-restart flow (relaunchApp). Loaded as a Babel JSX script before the
// app shell; exposes window.RestartBanner and window.relaunchApp.

const _isLoopHost = (h) => ['127.0.0.1', '::1', 'localhost'].includes(h);
// fetch with no-cors: any response (opaque included) means the server is up.
// (The old Image probe never fired onload for the JSON /api/meta body.)
const _probeBase = async (base) => {
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 4000);
    await fetch(`${base}/api/meta?t=${Date.now()}`, { mode: 'no-cors', cache: 'no-store', signal: ctl.signal });
    clearTimeout(timer);
    return true;
  } catch (_) {
    return false;
  }
};

const _waitForServerUp = async (base, timeoutMs) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await _probeBase(base)) return;
    await new Promise((r) => setTimeout(r, 2500));
  }
  throw new Error(`等待 ${base} 就绪超时`);
};

window.relaunchApp = async (pending) => {
  const port = window.location.port || '8000';
  // Dual-listen: stay on the same family as the current page — loopback pages
  // stay on 127.0.0.1 (proxy-exempt), remote pages jump to the new 100.x.
  const list = (Array.isArray(pending) ? pending : [pending]).filter(Boolean);
  const stayLocal = _isLoopHost(window.location.hostname);
  const host = stayLocal
    ? (list.find(_isLoopHost) || '127.0.0.1')
    : (list.find((h) => !_isLoopHost(h)) || list[0] || window.location.hostname);
  const target = `${window.location.protocol}//${host}${port ? `:${port}` : ''}`;
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

  const hosts = info.current_hosts || (info.current_host ? [info.current_host] : []);
  const pending = info.pending_hosts || (info.pending_host ? [info.pending_host] : []);
  const text = showAction
    ? `监听地址变更未生效：当前 ${hosts.join(' + ')}，重启后为 ${pending.join(' + ')}。${info.bind_warning ? `（${info.bind_warning}）` : ''}`
    : info.bind_warning;

  // When Tailscale is down the pending remote address cannot be bound yet —
  // offering restart would kill the working local server for nothing.
  // (Loopback always stays bound, so local use is never interrupted.)
  const tailscaleDown = !!(info.tailscale && !info.tailscale.connected) && pending.some((h) => h && !_isLoopHost(h));

  const doRestart = async () => {
    setBusy(true); setError('');
    try {
      await window.relaunchApp(pending);
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
