const MEMBER_SPECIES_OPTIONS = [
  ['cat', '猫'],
  ['dog', '狗'],
  ['other', '其他宠物'],
];

const memberApiWrite = async (path, method, body) => {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const detail = data?.detail || `${path} · ${res.status}`;
    throw new Error(Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail);
  }
  return data;
};

const memberAvatarUpload = async (key, file) => {
  const formData = new FormData();
  formData.append('file', file);
  const path = `/api/members/${encodeURIComponent(key)}/avatar`;
  const res = await fetch(path, { method: 'POST', body: formData });
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const detail = data?.detail || `${path} · ${res.status}`;
    throw new Error(Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail);
  }
  return data;
};

const memberAvatarApplyPreset = async (key, name) => {
  const path = `/api/members/${encodeURIComponent(key)}/avatar/preset`;
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const detail = data?.detail || `${path} · ${res.status}`;
    throw new Error(Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail);
  }
  return data;
};

const arrayToText = (value) => Array.isArray(value) ? value.join('\n') : '';
const textToArray = (value) => String(value || '')
  .split(/[\n,，]/)
  .map(s => s.trim())
  .filter(Boolean);

const emptyMemberForm = (kind) => ({
  name: '',
  full_name: '',
  role: '',
  birth_date: '',
  sex: '',
  blood_type: '',
  allergies: '',
  chronic: '',
  species: kind === 'pet' ? 'cat' : 'human',
  species_detail: '',
  breed: '',
  home_date: '',
  doctor: '',
  notes: '',
});

const formFromMember = (member, fallbackKind) => {
  if (!member) return emptyMemberForm(fallbackKind || 'human');
  return {
    name: member.name || '',
    full_name: member.full_name || '',
    role: member.role || '',
    birth_date: member.birth_date || '',
    sex: member.species === 'human'
      ? (member.sex === '男' || member.sex === '女' ? member.sex : '')
      : (member.sex === '公' ? '弟弟' : member.sex === '母' ? '妹妹' : (member.sex === '弟弟' || member.sex === '妹妹' ? member.sex : '')),
    blood_type: member.blood_type || '',
    allergies: arrayToText(member.allergies),
    chronic: arrayToText(member.chronic),
    species: member.species || 'human',
    species_detail: member.species_detail || '',
    breed: member.breed || '',
    home_date: member.home_date || '',
    doctor: member.doctor || '',
    notes: member.notes || '',
  };
};

function MemberEditorModal({ mode = 'create', kind = 'human', member = null, onClose, onSaved }) {
  const isEdit = mode === 'edit';
  const [form, setForm] = React.useState(() => formFromMember(member, kind));
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');
  const [avatarFile, setAvatarFile] = React.useState(null);
  const [avatarPreview, setAvatarPreview] = React.useState('');
  const [presetOpen, setPresetOpen] = React.useState(false);
  const [presets, setPresets] = React.useState(null);
  const [presetLoading, setPresetLoading] = React.useState(false);
  const [presetError, setPresetError] = React.useState('');
  const [presetAvatarUrl, setPresetAvatarUrl] = React.useState('');
  const isPetForm = form.species !== 'human';
  const archived = Boolean(member?.archived_at);

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

  React.useEffect(() => () => {
    if (avatarPreview) URL.revokeObjectURL(avatarPreview);
  }, [avatarPreview]);

  const setField = (field, value) => setForm(prev => ({ ...prev, [field]: value }));
  const selectAvatar = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(file.type)) {
      setError('头像仅支持 JPG、PNG、WEBP 或 GIF 图片');
      event.target.value = '';
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError('头像不能超过 5MB');
      event.target.value = '';
      return;
    }
    setError('');
    setPresetAvatarUrl('');
    setAvatarFile(file);
    setAvatarPreview(URL.createObjectURL(file));
  };
  const openPresets = async () => {
    setPresetError('');
    setPresetOpen(true);
    if (presets !== null) return;
    setPresetLoading(true);
    try {
      const res = await fetch('/api/avatars/presets');
      let data = null;
      try { data = await res.json(); } catch (_) { data = null; }
      if (!res.ok) throw new Error(data?.detail || `/api/avatars/presets · ${res.status}`);
      setPresets(Array.isArray(data) ? data : []);
    } catch (err) {
      setPresetError(err.message || '加载预设头像失败');
    } finally {
      setPresetLoading(false);
    }
  };
  const applyPreset = async (item) => {
    setSaving(true);
    setPresetError('');
    try {
      const saved = await memberAvatarApplyPreset(member.key, item.name);
      setPresetAvatarUrl(saved?.avatar_url || '');
      setAvatarFile(null);
      setAvatarPreview('');
      setPresetOpen(false);
    } catch (err) {
      setPresetError(err.message || '应用预设头像失败');
    } finally {
      setSaving(false);
    }
  };
  const switchKind = (nextKind) => setForm(prev => ({ ...prev, species: nextKind === 'pet' ? (prev.species === 'human' ? 'cat' : prev.species || 'cat') : 'human' }));

  const payload = () => {
    const name = form.name.trim();
    if (!name) throw new Error('姓名/名字不能为空');
    if (!form.species) throw new Error('请选择成员类型');
    if (form.species === 'other' && !form.species_detail.trim()) throw new Error('请填写宠物类型');
    const base = {
      name,
      species: form.species,
      species_detail: form.species === 'other' ? form.species_detail.trim() : null,
      birth_date: form.birth_date || null,
      sex: form.sex || null,
      doctor: form.doctor || null,
      notes: form.notes || null,
    };
    if (form.species === 'human') {
      return {
        ...base,
        full_name: form.full_name || null,
        role: form.role || null,
        blood_type: form.blood_type || null,
        allergies: textToArray(form.allergies),
        chronic: textToArray(form.chronic),
        breed: null,
        home_date: null,
      };
    }
    return {
      ...base,
      full_name: null,
      role: null,
      blood_type: null,
      allergies: [],
      chronic: [],
      breed: form.breed || null,
      home_date: form.home_date || null,
    };
  };

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const body = payload();
      let saved = isEdit
        ? await memberApiWrite(`/api/members/${encodeURIComponent(member.key)}`, 'PATCH', body)
        : await memberApiWrite('/api/members', 'POST', body);
      if (isEdit && avatarFile) saved = await memberAvatarUpload(member.key, avatarFile);
      await onSaved?.(saved);
      onClose();
    } catch (err) {
      setError(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const toggleArchive = async () => {
    if (!isEdit || !member) return;
    const action = archived ? '恢复' : '归档';
    if (!window.confirm(`${action}成员「${member.name}」？\n\n归档后默认家庭列表不再显示该成员，但不会删除任何健康记录。`)) return;
    setSaving(true);
    setError('');
    try {
      const body = { archived_at: archived ? null : new Date().toISOString().slice(0, 19).replace('T', ' ') };
      const saved = await memberApiWrite(`/api/members/${encodeURIComponent(member.key)}`, 'PATCH', body);
      await onSaved?.(saved);
      onClose();
    } catch (err) {
      setError(err.message || `${action}失败`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div className="daily-modal sketch shadow" style={{ maxWidth: 680 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 12 }}>
          <div>
            <div className="sec-label">家庭成员管理</div>
            <div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>
              {isEdit ? `编辑资料 · ${member?.name || ''}` : isPetForm ? '新增宠物' : '新增家庭成员'}
            </div>
          </div>
          <Btn ghost onClick={onClose}>关闭</Btn>
        </div>

        {!isEdit && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <Btn primary={!isPetForm} onClick={() => switchKind('human')}>家庭成员</Btn>
            <Btn primary={isPetForm} onClick={() => switchKind('pet')}>宠物</Btn>
          </div>
        )}

        {error && <div className="sketch" style={{ padding: 10, marginBottom: 12, color: 'var(--danger)' }}>{error}</div>}

        {isEdit && (
          <div className="sketch" style={{ display: 'flex', alignItems: 'center', gap: 14, padding: 12, marginBottom: 12, flexWrap: 'wrap' }}>
            <Avatar
              label={(member?.name || '?').slice(0, 1)}
              size="lg"
              src={avatarPreview || presetAvatarUrl || member?.avatar_url || ''}
              alt={`${member?.name || '成员'}头像`}
            />
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8, minWidth: 200 }}>
              <label><span>头像</span><input type="file" accept="image/jpeg,image/png,image/webp,image/gif" onChange={selectAvatar} disabled={saving} /></label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <Btn ghost disabled={saving} onClick={openPresets}>从预设库选择</Btn>
                {avatarFile
                  ? <span className="scribble" style={{ fontSize: 12, color: 'var(--ink-soft)' }}>已选择图片，保存后生效</span>
                  : presetAvatarUrl
                    ? <span className="scribble" style={{ fontSize: 12, color: 'var(--ink-soft)' }}>预设头像已应用</span>
                    : null}
              </div>
            </div>
          </div>
        )}

        <div className="daily-form" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
          <label><span>姓名/名字 *</span><input value={form.name} onChange={e => setField('name', e.target.value)} /></label>
          {isPetForm ? (
            <>
              <label><span>宠物类型</span><select value={form.species} onChange={e => setField('species', e.target.value)}>{MEMBER_SPECIES_OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
              {form.species === 'other' && <label><span>请填写宠物类型 *</span><input value={form.species_detail} onChange={e => setField('species_detail', e.target.value)} placeholder="例如：兔、仓鼠、鹦鹉" /></label>}
            </>
          ) : (
            <label><span>完整姓名</span><input value={form.full_name} onChange={e => setField('full_name', e.target.value)} /></label>
          )}
          {!isPetForm && <label><span>称呼/关系</span><input value={form.role} onChange={e => setField('role', e.target.value)} placeholder="本人、妈妈、孩子..." /></label>}
          {isPetForm && <label><span>品种</span><input value={form.breed} onChange={e => setField('breed', e.target.value)} /></label>}
          <label><span>出生日期</span><input type="date" value={form.birth_date} onChange={e => setField('birth_date', e.target.value)} /></label>
          {isPetForm ? (
            <label><span>性别</span><select value={form.sex} onChange={e => setField('sex', e.target.value)}><option value="">请选择</option><option value="弟弟">弟弟</option><option value="妹妹">妹妹</option></select></label>
          ) : (
            <label><span>性别</span><select value={form.sex} onChange={e => setField('sex', e.target.value)}><option value="">请选择</option><option value="男">男</option><option value="女">女</option></select></label>
          )}
          {!isPetForm && <label><span>血型</span><input value={form.blood_type} onChange={e => setField('blood_type', e.target.value)} /></label>}
          {isPetForm && <label><span>到家日</span><input type="date" value={form.home_date} onChange={e => setField('home_date', e.target.value)} /></label>}
          <label><span>常去医院/医生</span><input value={form.doctor} onChange={e => setField('doctor', e.target.value)} /></label>
          {!isPetForm && <label style={{ gridColumn: '1 / -1' }}><span>过敏史（每行或逗号分隔）</span><textarea rows="3" value={form.allergies} onChange={e => setField('allergies', e.target.value)} /></label>}
          {!isPetForm && <label style={{ gridColumn: '1 / -1' }}><span>慢病/长期关注（每行或逗号分隔）</span><textarea rows="3" value={form.chronic} onChange={e => setField('chronic', e.target.value)} /></label>}
          <label style={{ gridColumn: '1 / -1' }}><span>备注</span><textarea rows="4" value={form.notes} onChange={e => setField('notes', e.target.value)} /></label>
        </div>

        {presetOpen && (
          <div className="modal-backdrop" style={{ zIndex: 300 }} onClick={() => !saving && setPresetOpen(false)}>
            <div className="daily-modal sketch shadow" style={{ maxWidth: 520 }} onClick={(e) => e.stopPropagation()}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', marginBottom: 12 }}>
                <div>
                  <div className="sec-label">头像预设库</div>
                  <div style={{ fontFamily: 'Caveat, cursive', fontSize: 28, fontWeight: 700, lineHeight: 1 }}>选一张当作头像</div>
                </div>
                <Btn ghost disabled={saving} onClick={() => setPresetOpen(false)}>关闭</Btn>
              </div>
              {presetError && <div className="sketch" style={{ padding: 10, marginBottom: 12, color: 'var(--danger)' }}>{presetError}</div>}
              {presetLoading ? (
                <div style={{ padding: 24, textAlign: 'center', color: 'var(--ink-soft)' }}>加载中…</div>
              ) : presets && presets.length === 0 ? (
                <div style={{ padding: 24, textAlign: 'center', color: 'var(--ink-soft)' }}>暂无预设头像，可改用上方「头像」上传图片。</div>
              ) : presets ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(84px, 1fr))', gap: 10, maxHeight: 420, overflowY: 'auto', padding: 4 }}>
                  {presets.map(item => (
                    <button
                      key={item.name}
                      type="button"
                      disabled={saving}
                      onClick={() => applyPreset(item)}
                      title={item.name}
                      style={{ border: '2px dashed var(--line)', borderRadius: 12, background: 'transparent', padding: 6, cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}
                    >
                      <img src={item.url} alt={item.name} style={{ width: 64, height: 64, objectFit: 'cover', borderRadius: 10, display: 'block' }} />
                      <span style={{ fontSize: 11, color: 'var(--ink-soft)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%' }}>{item.name.replace(/\.(webp|png|jpe?g|gif)$/i, '')}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginTop: 16, flexWrap: 'wrap' }}>
          <div>{isEdit && <Btn ghost disabled={saving} onClick={toggleArchive}>{archived ? '恢复成员' : '归档成员'}</Btn>}</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn ghost disabled={saving} onClick={onClose}>取消</Btn>
            <Btn primary disabled={saving} onClick={save}>{saving ? '保存中...' : '保存'}</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

window.MemberEditorModal = MemberEditorModal;
