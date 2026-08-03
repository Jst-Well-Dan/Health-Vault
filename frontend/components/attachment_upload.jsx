function AttachmentUploadModal({ member, visits = [], onClose, onUploaded }) {
  const bridge = window.healthAttachment;
  const [selected, setSelected] = React.useState(null);
  const [form, setForm] = React.useState({
    date: new Date().toISOString().slice(0, 10),
    title: '',
    org: '',
    tag: '',
    visit_id: '',
    notes: '',
  });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');

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

  const set = (key, value) => setForm(prev => ({ ...prev, [key]: value }));

  const selectFile = async () => {
    if (!bridge) return;
    setBusy(true);
    setError('');
    try {
      const file = await bridge.select();
      if (file) {
        setSelected(file);
        setForm(prev => ({ ...prev, title: prev.title || file.filename.replace(/\.[^.]+$/, '') }));
      }
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  const upload = async (event) => {
    event.preventDefault();
    if (!bridge) return;
    if (!selected?.token) { setError('请先选择附件文件'); return; }
    if (!form.title.trim()) { setError('请填写附件标题'); return; }
    if (!form.date) { setError('请填写附件日期'); return; }
    setBusy(true);
    setError('');
    try {
      const saved = await bridge.upload({
        file_token: selected.token,
        member_key: member.key,
        date: form.date,
        title: form.title.trim(),
        org: form.org.trim(),
        tag: form.tag.trim(),
        visit_id: form.visit_id,
        notes: form.notes.trim(),
      });
      await onUploaded?.(saved);
      onClose();
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="添加附件">
      <div className="daily-modal sketch shadow" style={{ maxWidth: 680 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, marginBottom: 12 }}>
          <div>
            <div className="sec-label">附件库 · {member?.name || ''}</div>
            <div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>添加普通附件</div>
          </div>
          <Btn ghost disabled={busy} onClick={onClose}>关闭</Btn>
        </div>

        {!bridge ? (
          <div className="sketch" style={{ padding: 16, background: 'color-mix(in oklab, var(--accent-2) 18%, var(--paper))' }}>
            普通附件上传需要通过 Electron 桌面版选择本地文件；静态预览或浏览器环境不支持。
          </div>
        ) : (
          <form className="daily-form" onSubmit={upload}>
            <div className="mono span-2" style={{ color: 'var(--ink-soft)' }}>
              此入口只归档原始文件并新增一条附件记录，不会自动创建就诊记录或化验指标。医疗报告结构化入库请继续使用“上传报告/附件”。
            </div>
            <div className="span-2" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <Btn onClick={selectFile} disabled={busy}>{selected ? '重新选择文件' : '选择本地文件'}</Btn>
              <span className="mono">{selected?.filename || '未选择文件'}</span>
            </div>
            <label>标题 *<input required value={form.title} onChange={e => set('title', e.target.value)} placeholder="例如：门诊发票、影像光盘说明" /></label>
            <label>日期 *<input required type="date" value={form.date} onChange={e => set('date', e.target.value)} /></label>
            <label>机构<input value={form.org} onChange={e => set('org', e.target.value)} placeholder="医院、体检中心或诊所" /></label>
            <label>标签<input value={form.tag} onChange={e => set('tag', e.target.value)} placeholder="发票、影像、处方、说明等" /></label>
            <label className="span-2">关联就诊<select value={form.visit_id} onChange={e => set('visit_id', e.target.value)}>
              <option value="">不关联</option>
              {visits.map(v => <option key={v.id} value={v.id}>{v.date} · {v.type || '就诊'} · {v.hospital || v.chief_complaint || `#${v.id}`}</option>)}
            </select></label>
            <label className="span-2">备注<textarea rows="4" value={form.notes} onChange={e => set('notes', e.target.value)} /></label>
            {error && <div className="report-import-error span-2">{error}</div>}
            <div className="form-actions span-2">
              <Btn ghost disabled={busy} onClick={onClose}>取消</Btn>
              <Btn primary type="submit" disabled={busy || !selected}>{busy ? '保存中...' : '保存附件'}</Btn>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

window.AttachmentUploadModal = AttachmentUploadModal;
