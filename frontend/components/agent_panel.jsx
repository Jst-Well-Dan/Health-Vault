const agentRequest = async (path, options = {}) => {
  const response = await fetch(`/api/agent-runtime${path}`, {
    ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) },
  });
  const text = await response.text();
  if (!response.ok) {
    try { throw new Error(JSON.parse(text).detail || response.statusText); }
    catch (error) { if (error instanceof SyntaxError) throw new Error(text || response.statusText); throw error; }
  }
  return text ? JSON.parse(text) : null;
};

function AgentPanel({ onDataChanged, settingsAction, onSettingsActionHandled }) {
  const [open, setOpen] = React.useState(false);
  const [messages, setMessages] = React.useState([]);
  const [draft, setDraft] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [request, setRequest] = React.useState(null);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [settings, setSettings] = React.useState(null);
  const [apiKey, setApiKey] = React.useState('');
  const [notice, setNotice] = React.useState('');
  const [reportImportOpen, setReportImportOpen] = React.useState(false);
  const [reportMembers, setReportMembers] = React.useState([]);
  const [openingReportImport, setOpeningReportImport] = React.useState(false);
  const endRef = React.useRef(null);

  const loadSettings = React.useCallback(async (provider) => {
    const value = await agentRequest(`/agent/settings${provider ? `?provider=${encodeURIComponent(provider)}` : ''}`);
    setSettings(value);
    return value;
  }, []);

  React.useEffect(() => {
    agentRequest('/agent/history').then(setMessages).catch(err => setNotice(err.message));
    loadSettings().catch(err => setNotice(err.message));
    const stream = new EventSource('/api/agent-runtime/agent/stream');
    stream.onmessage = (event) => { try { handleEvent(JSON.parse(event.data)); } catch (_) {} };
    stream.onerror = () => setNotice('健康助手连接已断开，请刷新页面后重试。');
    return () => stream.close();
  }, [loadSettings]);

  React.useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, open]);
  React.useEffect(() => {
    if (!settingsAction) return;
    if (settingsAction.section === 'ai') setSettingsOpen(true);
    onSettingsActionHandled?.();
  }, [settingsAction]);

  const handleEvent = (event) => {
    if (event.type === 'delta') setMessages(rows => {
      const next = [...rows]; const last = next[next.length - 1];
      if (last?.role === 'assistant' && last.streaming) last.content += event.text;
      else next.push({ role: 'assistant', content: event.text, streaming: true });
      return next;
    });
    if (event.type === 'done') { setBusy(false); setMessages(rows => rows.map(row => row.streaming ? { ...row, streaming: false } : row)); if (event.error) setNotice(event.error); }
    if (event.type === 'request') { if (event.kind === 'approval') setRequest(event); else answerAuthPrompt(event); }
    if (event.type === 'auth') { const item = event.event; setNotice(item.message || item.instructions || (item.url ? `请在浏览器打开：${item.url}` : '正在登录…')); if (item.url) window.open(item.url, '_blank'); }
    if (event.type === 'data-changed') onDataChanged?.();
    if (event.type === 'notice' || event.type === 'fatal') setNotice(event.text);
    if (event.type === 'reset') { setMessages([]); setBusy(false); setRequest(null); setNotice('对话已重置，健康助手不再记得之前的对话内容。'); }
  };

  const resetContext = async () => {
    if (!window.confirm('清空当前对话并重置健康助手的上下文记忆？\n\n已经写入的健康数据不会受影响，只是对话历史会被清空。')) return;
    try { await agentRequest('/agent/reset', { method: 'POST' }); }
    catch (err) { setNotice(err.message || String(err)); }
  };

  const respond = (id, value) => agentRequest('/agent/respond', { method: 'POST', body: JSON.stringify({ id, value }) });
  const answerAuthPrompt = (event) => {
    const prompt = event.payload; let value = '';
    if (prompt.type === 'select') { const choices = prompt.options.map((item, index) => `${index + 1}. ${item.label}`).join('\n'); const selected = window.prompt(`${prompt.message}\n${choices}`, '1'); value = prompt.options[Math.max(0, Number(selected || 1) - 1)]?.id || ''; }
    else value = window.prompt(prompt.message, prompt.placeholder || '') || '';
    respond(event.id, value).catch(err => setNotice(err.message));
  };
  const send = async () => {
    const content = draft.trim(); if (!content || busy) return;
    setMessages(rows => [...rows, { role: 'user', content }]); setDraft(''); setBusy(true); setNotice('');
    try { await agentRequest('/agent/send', { method: 'POST', body: JSON.stringify({ message: content }) }); }
    catch (err) { setBusy(false); setNotice(err.message || String(err)); }
  };
  const openReportImport = async () => {
    if (openingReportImport) return;
    setOpeningReportImport(true); setNotice('');
    try {
      const response = await fetch('/api/members');
      const text = await response.text();
      if (!response.ok) {
        try { throw new Error(JSON.parse(text).detail || '无法读取家庭成员'); }
        catch (error) { if (error instanceof SyntaxError) throw new Error(text || '无法读取家庭成员'); throw error; }
      }
      const members = JSON.parse(text);
      if (!Array.isArray(members) || !members.length) throw new Error('请先创建家庭成员，再上传报告。');
      setReportMembers(members);
      setReportImportOpen(true);
    } catch (err) { setNotice(err.message || String(err)); }
    finally { setOpeningReportImport(false); }
  };
  const answerApproval = (approved) => { respond(request.id, approved).catch(err => setNotice(err.message)); setRequest(null); };
  const chooseProvider = async (provider) => { const next = await loadSettings(provider); setSettings({ ...next, provider, model: next.models[0]?.id || '' }); };
  const saveSettings = async () => {
    try {
      if (apiKey.trim()) await agentRequest('/agent/login', { method: 'POST', body: JSON.stringify({ provider: settings.provider, type: 'api_key', apiKey }) });
      const next = await agentRequest('/agent/settings', { method: 'POST', body: JSON.stringify({ provider: settings.provider, model: settings.model }) });
      setSettings(next); setApiKey(''); setSettingsOpen(false); setNotice('模型设置已保存');
    } catch (err) { setNotice(err.message || String(err)); }
  };
  const oauthLogin = async () => { try { setNotice('正在登录…'); setSettings(await agentRequest('/agent/login', { method: 'POST', body: JSON.stringify({ provider: settings.provider, type: 'oauth' }) })); } catch (err) { setNotice(err.message || String(err)); } };

  return <>
    <button className={`agent-fab ${open ? 'panel-open' : ''}`} onClick={() => setOpen(value => !value)} aria-label="打开健康助手">✦</button>
    <aside className={`agent-panel ${open ? 'open' : ''}`} aria-hidden={!open}>
      <header><div><b>健康档案助手</b></div><div><button onClick={resetContext} title="重置对话上下文">重置</button><button onClick={() => setOpen(false)}>×</button></div></header>
      <div className="agent-messages">{!messages.length && <div className="agent-empty">可以问：“爸爸最近在吃什么药？”<br/>也可以点击下方「上传报告」导入 PDF 或图片。<br/>写入前会展示实际字段并等待你确认。</div>}{messages.map((message, index) => <div key={message.id || index} className={`agent-message ${message.role}`}>{message.content}</div>)}<div ref={endRef} /></div>
      {notice && <div className="agent-notice">{notice}</div>}
      <div className="agent-compose"><textarea value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder="询问或整理健康档案…" /><div className="agent-compose-actions"><button onClick={openReportImport} disabled={openingReportImport} title="上传 PDF 或图片报告">{openingReportImport ? '读取中…' : '上传报告'}</button><button onClick={busy ? () => agentRequest('/agent/stop', { method: 'POST' }) : send}>{busy ? '停止' : '发送'}</button></div></div>
    </aside>
    {reportImportOpen && <ReportImportModal members={reportMembers} onClose={() => setReportImportOpen(false)} onImported={async () => { await onDataChanged?.(); setNotice('报告已归档，可继续向助手提问。'); }} />}
    {request && <div className="agent-modal-backdrop"><div className="agent-dialog"><h3>确认数据改动</h3><div className="agent-tool">{request.payload.tool}</div><div className="agent-diff"><section><b>修改前</b><pre>{JSON.stringify(request.payload.before, null, 2) || '—'}</pre></section><section><b>修改后</b><pre>{JSON.stringify(request.payload.after, null, 2) || '—'}</pre></section></div><div className="agent-actions"><button onClick={() => answerApproval(false)}>拒绝</button><button className="primary" onClick={() => answerApproval(true)}>确认执行</button></div></div></div>}
    {settingsOpen && settings && <div className="agent-modal-backdrop"><div className="agent-dialog agent-settings"><h3>模型设置</h3>{settings.source === 'pi' && <div className="agent-tool">当前跟随 Pi 默认模型：{settings.piDefault?.provider}/{settings.piDefault?.model}</div>}<label>Provider<select value={settings.provider} onChange={e => chooseProvider(e.target.value)}>{settings.providers.map(item => <option key={item.id} value={item.id}>{item.name}{item.configured ? ' · 已登录' : ''}</option>)}</select></label><label>模型<select value={settings.model} onChange={e => setSettings({ ...settings, model: e.target.value })}>{settings.models.map(item => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}</select></label><label>API Key（留空则不修改）<input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} /></label><div className="agent-actions"><button onClick={() => setSettingsOpen(false)}>取消</button>{settings.providers.find(item => item.id === settings.provider)?.auth.includes('oauth') && <button onClick={oauthLogin}>OAuth 登录</button>}<button className="primary" onClick={saveSettings}>保存</button></div></div></div>}
  </>;
}
