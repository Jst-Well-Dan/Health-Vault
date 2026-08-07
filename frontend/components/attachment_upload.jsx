function AttachmentUploadModal({ member, visits = [], onClose, onUploaded }) {
  const fileInputRef = React.useRef(null);
  const [selected, setSelected] = React.useState(null);
  const [form, setForm] = React.useState({ date: new Date().toISOString().slice(0, 10), title: '', org: '', tag: '', visit_id: '', notes: '' });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    const { body, documentElement } = document; const prevBodyOverflow = body.style.overflow; const prevHtmlOverflow = documentElement.style.overflow;
    body.style.overflow = 'hidden'; documentElement.style.overflow = 'hidden';
    return () => { body.style.overflow = prevBodyOverflow; documentElement.style.overflow = prevHtmlOverflow; };
  }, []);
  const set = (key, value) => setForm(prev => ({ ...prev, [key]: value }));
  const selectFile = (event) => {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file) return;
    setSelected(file); setForm(prev => ({ ...prev, title: prev.title || file.name.replace(/\.[^.]+$/, '') }));
  };
  const upload = async (event) => {
    event.preventDefault();
    if (!selected) { setError('请先选择附件文件'); return; }
    if (!form.title.trim() || !form.date) { setError('请填写附件标题和日期'); return; }
    setBusy(true); setError('');
    try {
      const data = new FormData();
      data.append('file', selected, selected.name); data.append('member_key', member.key); data.append('date', form.date); data.append('title', form.title.trim());
      for (const key of ['org', 'tag', 'visit_id', 'notes']) if (form[key]) data.append(key, form[key]);
      const response = await fetch('/api/attachments/upload', { method: 'POST', body: data });
      const text = await response.text();
      if (!response.ok) throw new Error(JSON.parse(text).detail || '附件上传失败');
      await onUploaded?.(JSON.parse(text)); onClose();
    } catch (err) { setError(err.message || String(err)); }
    finally { setBusy(false); }
  };

  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="添加附件"><div className="daily-modal sketch shadow" style={{ maxWidth: 680 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, marginBottom: 12 }}><div><div className="sec-label">附件库 · {member?.name || ''}</div><div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>添加普通附件</div></div><Btn ghost disabled={busy} onClick={onClose}>关闭</Btn></div>
    <form className="daily-form" onSubmit={upload}>
      <div className="mono span-2" style={{ color: 'var(--ink-soft)' }}>此入口只归档原始文件并新增一条附件记录，不会自动创建就诊记录或化验指标。医疗报告结构化入库请继续使用“上传报告/附件”。</div>
      <input ref={fileInputRef} type="file" onChange={selectFile} hidden />
      <div className="span-2" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}><Btn onClick={() => fileInputRef.current?.click()} disabled={busy}>{selected ? '重新选择文件' : '选择本地文件'}</Btn><span className="mono">{selected?.name || '未选择文件'}</span></div>
      <label>标题 *<input required value={form.title} onChange={e => set('title', e.target.value)} placeholder="例如：门诊发票、影像光盘说明" /></label><label>日期 *<input required type="date" value={form.date} onChange={e => set('date', e.target.value)} /></label><label>机构<input value={form.org} onChange={e => set('org', e.target.value)} placeholder="医院、体检中心或诊所" /></label><label>标签<input value={form.tag} onChange={e => set('tag', e.target.value)} placeholder="发票、影像、处方、说明等" /></label>
      <label className="span-2">关联就诊<select value={form.visit_id} onChange={e => set('visit_id', e.target.value)}><option value="">不关联</option>{visits.map(v => <option key={v.id} value={v.id}>{v.date} · {v.type || '就诊'} · {v.hospital || v.chief_complaint || `#${v.id}`}</option>)}</select></label><label className="span-2">备注<textarea rows="4" value={form.notes} onChange={e => set('notes', e.target.value)} /></label>
      {error && <div className="report-import-error span-2">{error}</div>}<div className="form-actions span-2"><Btn ghost disabled={busy} onClick={onClose}>取消</Btn><Btn primary type="submit" disabled={busy || !selected}>{busy ? '保存中...' : '保存附件'}</Btn></div>
    </form>
  </div></div>;
}
window.AttachmentUploadModal = AttachmentUploadModal;
