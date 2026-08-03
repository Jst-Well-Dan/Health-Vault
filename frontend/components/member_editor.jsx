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
  breed: '',
  home_date: '',
  chip_id: '',
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
    sex: member.sex || '',
    blood_type: member.blood_type || '',
    allergies: arrayToText(member.allergies),
    chronic: arrayToText(member.chronic),
    species: member.species || 'human',
    breed: member.breed || '',
    home_date: member.home_date || '',
    chip_id: member.chip_id || '',
    doctor: member.doctor || '',
    notes: member.notes || '',
  };
};

function MemberEditorModal({ mode = 'create', kind = 'human', member = null, onClose, onSaved }) {
  const isEdit = mode === 'edit';
  const [form, setForm] = React.useState(() => formFromMember(member, kind));
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');
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

  const setField = (field, value) => setForm(prev => ({ ...prev, [field]: value }));
  const switchKind = (nextKind) => setForm(prev => ({ ...prev, species: nextKind === 'pet' ? (prev.species === 'human' ? 'cat' : prev.species || 'cat') : 'human' }));

  const payload = () => {
    const name = form.name.trim();
    if (!name) throw new Error('姓名/名字不能为空');
    if (!form.species) throw new Error('请选择成员类型');
    const base = {
      name,
      species: form.species,
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
        chip_id: null,
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
      chip_id: form.chip_id || null,
    };
  };

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const body = payload();
      const saved = isEdit
        ? await memberApiWrite(`/api/members/${encodeURIComponent(member.key)}`, 'PATCH', body)
        : await memberApiWrite('/api/members', 'POST', body);
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

        <div className="daily-form" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
          <label><span>姓名/名字 *</span><input value={form.name} onChange={e => setField('name', e.target.value)} /></label>
          {isPetForm ? (
            <label><span>宠物类型</span><select value={form.species} onChange={e => setField('species', e.target.value)}>{MEMBER_SPECIES_OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
          ) : (
            <label><span>完整姓名</span><input value={form.full_name} onChange={e => setField('full_name', e.target.value)} /></label>
          )}
          {!isPetForm && <label><span>称呼/关系</span><input value={form.role} onChange={e => setField('role', e.target.value)} placeholder="本人、妈妈、孩子..." /></label>}
          {isPetForm && <label><span>品种</span><input value={form.breed} onChange={e => setField('breed', e.target.value)} /></label>}
          <label><span>出生日期</span><input type="date" value={form.birth_date} onChange={e => setField('birth_date', e.target.value)} /></label>
          <label><span>性别</span><input value={form.sex} onChange={e => setField('sex', e.target.value)} placeholder="男/女/未知" /></label>
          {!isPetForm && <label><span>血型</span><input value={form.blood_type} onChange={e => setField('blood_type', e.target.value)} /></label>}
          {isPetForm && <label><span>到家日</span><input type="date" value={form.home_date} onChange={e => setField('home_date', e.target.value)} /></label>}
          {isPetForm && <label><span>芯片号</span><input value={form.chip_id} onChange={e => setField('chip_id', e.target.value)} /></label>}
          <label><span>常去医院/医生</span><input value={form.doctor} onChange={e => setField('doctor', e.target.value)} /></label>
          {!isPetForm && <label style={{ gridColumn: '1 / -1' }}><span>过敏史（每行或逗号分隔）</span><textarea rows="3" value={form.allergies} onChange={e => setField('allergies', e.target.value)} /></label>}
          {!isPetForm && <label style={{ gridColumn: '1 / -1' }}><span>慢病/长期关注（每行或逗号分隔）</span><textarea rows="3" value={form.chronic} onChange={e => setField('chronic', e.target.value)} /></label>}
          <label style={{ gridColumn: '1 / -1' }}><span>备注</span><textarea rows="4" value={form.notes} onChange={e => setField('notes', e.target.value)} /></label>
        </div>

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
