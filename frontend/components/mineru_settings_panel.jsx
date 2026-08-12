function MineruSettingsPanel({ onClose }) {
  const [info, setInfo] = React.useState(null);
  const [error, setError] = React.useState('');
  const [notice, setNotice] = React.useState('');
  const [token, setToken] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setError('');
    try {
      const response = await fetch('/api/settings/mineru');
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(data?.detail || '读取 MinerU 设置失败');
      setInfo(data);
      return data;
    } catch (err) {
      setError(err.message || '读取 MinerU 设置失败');
      return null;
    }
  }, []);
  React.useEffect(() => { refresh(); }, [refresh]);

  const request = async (path, options) => {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.detail || '操作失败');
    setInfo(data);
  };

  const setMode = async (mode) => {
    setBusy(true); setError(''); setNotice('');
    try {
      await request('/api/settings/mineru/mode', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }) });
      setNotice(mode === 'extract' ? '已切换为精确解析。请确认 Token 已配置。' : '已切换为快速解析。');
    } catch (err) { setError(err.message || '修改模式失败'); }
    finally { setBusy(false); }
  };

  const saveToken = async (event) => {
    event.preventDefault();
    if (!token.trim()) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await request('/api/settings/mineru/token', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) });
      setToken('');
      setNotice('Token 已保存到当前电脑的系统凭据库，并已通过格式验证。');
    } catch (err) { setError(err.message || '保存 Token 失败'); }
    finally { setBusy(false); }
  };

  const deleteToken = async () => {
    if (!window.confirm('确定删除应用保存的 MinerU Token 吗？')) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await request('/api/settings/mineru/token', { method: 'DELETE' });
      setNotice('已删除应用保存的 MinerU Token。');
    } catch (err) { setError(err.message || '删除 Token 失败'); }
    finally { setBusy(false); }
  };

  const modeLabel = info?.mode === 'extract' ? '精确解析' : info?.mode === 'flash' ? '快速解析' : '配置无效';
  const tokenLabel = info?.token_source === 'health_vault' ? '已由健康档案安全保存' : info?.token_source === 'mineru_cli' ? '已由 MinerU CLI 配置' : '未配置';

  return <div className="modal-backdrop"><div className="daily-modal sketch shadow" style={{ maxWidth: 680 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 12 }}>
      <div><div className="sec-label">报告转换</div><div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>MinerU</div></div>
      <Btn ghost onClick={onClose}>关闭</Btn>
    </div>

    {error && <div className="sketch" style={{ padding: 10, marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}
    {notice && <div className="sketch" style={{ padding: 10, marginBottom: 12 }}>{notice}</div>}
    {!info && !error && <div className="mono">正在检测...</div>}
    {info && <>
      <DashLabel>当前状态</DashLabel>
      <div className="sketch" style={{ padding: 12, marginBottom: 16, display: 'grid', gap: 6 }}>
        <div>CLI：<strong>{info.installed ? `已安装${info.version ? `（${info.version}）` : ''}` : '未检测到'}</strong></div>
        <div>转换模式：<strong>{modeLabel}</strong></div>
        <div>Token：<strong>{tokenLabel}</strong></div>
      </div>

      {!info.installed && <div className="mono" style={{ color: 'var(--ink-soft)', marginBottom: 16 }}>请先按安装指南安装 mineru-open-api，再点击刷新。</div>}
      {info.installed && <>
        <DashLabel>转换模式</DashLabel>
        <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
          <Btn primary={info.mode === 'flash'} ghost={info.mode !== 'flash'} disabled={busy} onClick={() => setMode('flash')}>快速解析</Btn>
          <Btn primary={info.mode === 'extract'} ghost={info.mode !== 'extract'} disabled={busy} onClick={() => setMode('extract')}>精确解析</Btn>
        </div>
        <div className="mono" style={{ color: 'var(--ink-soft)', marginBottom: 16 }}>快速解析无需 Token，但限制 10 MB / 20 页且不识别表格；精确解析需要 Token，并支持表格和公式。</div>

        <DashLabel>应用保存的 MinerU Token</DashLabel>
        {!info.secure_storage_available && <div className="sketch" style={{ padding: 10, marginBottom: 12, color: 'var(--danger)' }}>当前系统凭据库不可用，不能在网页中保存 Token。你仍可在本机终端运行 <code>mineru-open-api auth</code> 配置。</div>}
        {info.secure_storage_available && <form className="daily-form" style={{ display: 'grid', gap: 10, marginBottom: 12 }} onSubmit={saveToken}>
          <label><span>Token</span><input type="password" name="mineru-token" autoComplete="off" value={token} disabled={busy} onChange={event => setToken(event.target.value)} placeholder="粘贴 MinerU Token" /></label>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Btn primary type="submit" disabled={busy || !token.trim()}>{busy ? '保存中...' : '保存并验证'}</Btn>
            {info.token_source === 'health_vault' && <Btn ghost type="button" disabled={busy} onClick={deleteToken}>删除应用 Token</Btn>}
          </div>
        </form>}
        <div className="mono" style={{ color: 'var(--ink-soft)', marginBottom: 16 }}>Token 仅保存到当前 Windows Credential Manager 或 macOS Keychain，不写入健康档案、设置文件或日志；保存后不会再次显示。</div>
      </>}
      <div style={{ display: 'flex', gap: 10 }}><Btn ghost disabled={busy} onClick={refresh}>刷新状态</Btn></div>
    </>}
  </div></div>;
}
window.MineruSettingsPanel = MineruSettingsPanel;
