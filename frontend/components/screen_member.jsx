// Member detail screen backed by REST API data.

const HUMAN_TABS = ['概览', '体检报告', '就医记录', '用药', '附件库', '提醒'];
const PET_TABS = ['概览', '记事', '疫苗接种', '就医记录', '用药', '体重趋势', '附件库', '提醒'];
const PET_CARE_KINDS = ['驱虫', '洗澡', '换猫砂'];
const PET_CARE_KIND_SET = new Set(PET_CARE_KINDS);
const PET_KIND_LABELS = {
  weight: '体重',
  pet_care: '疫苗/驱虫',
  checkup: '体检',
};

const petKindLabel = (kind, fallback = '提醒') => PET_KIND_LABELS[kind] || kind || fallback;

const apiJson = async (path, options) => {
  const res = await fetch(path, options);
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const detail = data?.detail;
    const message = Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('；') : detail;
    throw new Error(message || `${path} · ${res.status}`);
  }
  return data;
};

const apiWrite = (path, method, body) => apiJson(path, {
  method,
  headers: body ? { 'Content-Type': 'application/json' } : undefined,
  body: body ? JSON.stringify(body) : undefined,
});

const todayIso = () => new Date().toISOString().slice(0, 10);

const cleanPayload = (payload) => Object.fromEntries(
  Object.entries(payload).map(([key, value]) => [key, value === '' ? null : value])
);

const splitTextList = (value) => String(value || '')
  .split(/[\n,，]/)
  .map(s => s.trim())
  .filter(Boolean);

const extractNumber = (value) => {
  const n = parseFloat(String(value ?? '').replace(/[^\d.-]/g, ''));
  return Number.isFinite(n) ? n : null;
};

const formatValue = (value, digits = 1) => {
  const n = extractNumber(value);
  return n === null ? (value ?? '—') : Number(n.toFixed(digits)).toString();
};

const formatWeight = (value) => {
  const n = extractNumber(value);
  return n === null ? (value ?? '—') : n.toFixed(2);
};

const petAgeAtText = (birthDate, atDate) => {
  if (!birthDate || !atDate) return '';
  const birth = new Date(`${birthDate}T00:00:00`);
  const target = new Date(`${atDate}T00:00:00`);
  if (Number.isNaN(birth.getTime()) || Number.isNaN(target.getTime())) return '';
  let months = (target.getFullYear() - birth.getFullYear()) * 12 + target.getMonth() - birth.getMonth();
  if (target.getDate() < birth.getDate()) months -= 1;
  months = Math.max(0, months);
  return `年龄 ${Math.floor(months / 12)}岁${months % 12}个月`;
};

const weightPointNote = (member, weight) => (
  [weight?.notes, petAgeAtText(member?.birth_date, weight?.date)].filter(Boolean).join(' · ')
);

const latestByName = (labs) => {
  const map = new Map();
  labs.forEach(lab => {
    const prev = map.get(lab.test_name);
    if (!prev || `${lab.date}-${lab.id}` > `${prev.date}-${prev.id}`) map.set(lab.test_name, lab);
  });
  return Array.from(map.values()).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 6);
};

const refForLab = (lab) => {
  if (!lab) return null;
  const lo = extractNumber(lab.ref_low);
  const hi = extractNumber(lab.ref_high);
  if (lo !== null && hi !== null) return [lo, hi];
  if (hi !== null) return [0, hi];
  return null;
};

const displayRef = (low, high) => {
  if (low != null && high != null) return `${low}–${high}`;
  if (low != null) return `≥${low}`;
  if (high != null) return `≤${high}`;
  return '—';
};

const labDirection = (item) => {
  const status = String(item?.status || '').toLowerCase();
  if (status === 'high' || status === 'low') return status;
  if (status === 'normal') return 'normal';
  if (status === 'abnormal' || item?.warn) return 'abnormal';
  return 'unknown';
};

const labDirectionMark = (direction) => {
  if (direction === 'high') return ' ↑';
  if (direction === 'low') return ' ↓';
  if (direction === 'abnormal') return ' !';
  return '';
};

const reportFromVisit = (visit, attachment) => ({
  id: `visit-${visit.id}`,
  attachmentId: attachment?.attachmentId,
  visitId: visit.id,
  d: visit.date,
  t: visit.chief_complaint || (visit.diagnosis || []).join(' / ') || '就诊记录',
  org: [visit.hospital, visit.department].filter(Boolean).join(' · '),
  tag: visit.type || '就医',
  severity: visit.severity,
  type: visit.type || '就医',
  chiefComplaint: visit.chief_complaint,
  abn: (visit.diagnosis || []).length ? visit.diagnosis : [visit.notes || '已记录'],
  fullNote: visit.note_full,
  file: attachment?.file || visit.source_file || `visit-${visit.id}`,
  filePath: attachment?.file_path,
});

const reportFromAttachment = (a) => ({
  id: `att-${a.id}`,
  attachmentId: a.id,
  visitId: a.visit_id,
  d: a.date,
  t: a.title,
  org: a.org || '附件',
  tag: a.tag || '其他',
  abn: [a.notes || a.tag || '已归档'],
  file: a.filename || a.file_path || `attachment-${a.id}`,
  filePath: a.file_path,
  raw: a,
});

const reportTooltip = (r) => [r.t, r.d, r.org, r.file].filter(Boolean).join(' · ');

const isCheckupReport = (report) => report.tag === '体检' || report.tag === '体检报告';

const extOf = (file) => {
  const match = String(file || '').toLowerCase().match(/\.([a-z0-9]+)(?:$|\?)/);
  return match ? match[1] : '';
};

const previewKind = (file) => {
  const ext = extOf(file);
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'].includes(ext)) return 'image';
  if (ext === 'pdf') return 'pdf';
  if (['md', 'txt', 'csv', 'json'].includes(ext)) return 'text';
  return 'unsupported';
};

const isImageAttachment = (attachment) => previewKind(attachment?.filename || attachment?.file_path) === 'image';
const isPdfAttachment = (attachment) => previewKind(attachment?.filename || attachment?.file_path) === 'pdf';

const attachmentFileName = (attachment) => (
  attachment?.filename || attachment?.file_path || `attachment-${attachment?.id}`
);

const sortAttachments = (items) => items.slice().sort((a, b) => {
  const aFile = attachmentFileName(a);
  const bFile = attachmentFileName(b);
  return aFile.localeCompare(bFile, 'zh-Hans-CN', { numeric: true, sensitivity: 'base' }) || (a.id || 0) - (b.id || 0);
});

const listLine = (label, value) => value === undefined || value === null || value === ''
  ? ''
  : `- ${label}: ${Array.isArray(value) ? value.join(' / ') : value}`;

const compactLines = (lines) => lines.filter(Boolean).join('\n');

const sectionText = (title, body) => {
  const text = Array.isArray(body) ? compactLines(body) : String(body || '').trim();
  return text ? `## ${title}\n${text}` : '';
};

const labsContextText = (labs) => {
  if (!labs.length) return '';
  return labs.map(lab => compactLines([
    `- ${lab.panel || '检验结果'} / ${lab.test_name}: ${lab.value ?? '—'}${lab.unit ? ` ${lab.unit}` : ''}`,
    lab.ref_low != null || lab.ref_high != null ? `  参考值: ${displayRef(lab.ref_low, lab.ref_high)}` : '',
    lab.status ? `  状态: ${lab.status}` : '',
  ])).join('\n');
};

const visitContextText = ({ member, report, visit, labs, meds, attachments, conclusion, textPreview }) => {
  const memberName = member?.full_name || member?.name || member?.key || '未命名成员';
  return [
    `# ${memberName} - 本次就诊上下文`,
    sectionText('成员档案', [
      listLine('姓名', memberName),
      listLine('成员类型', isPet(member) ? '宠物' : '人'),
      listLine('品种', member?.breed),
      listLine('出生日期', member?.birth_date),
      listLine('到家日期', member?.home_date),
      listLine('年龄', member ? memberAge(member.birth_date) : ''),
      listLine('性别', member?.sex),
      listLine('血型', member?.blood_type),
      listLine('过敏史', member?.allergies),
      listLine('慢病/长期问题', member?.chronic),
      listLine('家庭医生', member?.doctor),
    ]),
    sectionText('就诊信息', [
      listLine('日期', visit?.date || report.d),
      listLine('机构', visit?.hospital || report.org),
      listLine('科室', visit?.department),
      listLine('医生', visit?.doctor),
      listLine('主诉/标题', visit?.chief_complaint || report.t),
      listLine('严重程度', visit?.severity || report.severity),
      listLine('诊断', visit?.diagnosis || report.abn),
      listLine('来源文件', report.file),
    ]),
    sectionText('医生结论/备注', conclusion),
    sectionText('本次检验/检查指标', labsContextText(labs)),
    sectionText('本次相关用药', meds.map(med => compactLines([
      `- ${med.name || '未命名用药'}`,
      med.dose ? `  剂量: ${med.dose}` : '',
      med.freq ? `  频次: ${med.freq}` : '',
      med.route ? `  途径: ${med.route}` : '',
      med.start_date || med.end_date ? `  日期: ${med.start_date || '—'} 至 ${med.ongoing ? '仍在使用' : (med.end_date || '—')}` : '',
      med.notes ? `  备注: ${med.notes}` : '',
    ])).join('\n')),
    sectionText('相关附件', attachments.map(a => `- ${a.title || a.filename || a.file} (${a.filename || a.file_path || '未记录文件名'})`).join('\n')),
    sectionText('原始文本预览', textPreview),
  ].filter(Boolean).join('\n\n');
};

const copyTextToClipboard = async (text) => {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
};

const speciesText = (m, weights) => {
  if (!m) return '';
  const sex = isPet(m) ? ({ 公: '弟弟', 母: '妹妹' }[m.sex] || m.sex) : m.sex;
  if (!isPet(m)) return `${memberAge(m.birth_date)}岁 · ${sex || '未录性别'} · ${m.blood_type || '血型未录'} · ${(m.allergies || []).length ? `过敏: ${m.allergies.join('/')}` : '无过敏史'} · ${(m.chronic || []).length ? `慢病: ${m.chronic.join('/')}` : '无慢病'}`;
  const latestWeight = weights[weights.length - 1];
  const type = m.species_detail || ({ cat: '猫', dog: '狗', other: '其他宠物' }[m.species] || '宠物');
  const breed = m.breed ? ` · ${m.breed}` : '';
  const home = m.home_date ? ` · 到家 ${m.home_date}` : '';
  return `${type}${breed} · ${sex || '未录性别'} · ${memberAge(m.birth_date)}岁${home}${latestWeight ? ` · ${formatWeight(latestWeight.weight_kg)} kg` : ''}`;
};

/* ── Static enriched detail for known reports ──────────────── */
const DETAIL_EXTRA = {
  'TJ-2026-03188.pdf': {
    title: '年度体检报告',
    date: '2026-03-18', org: '三甲A 体检中心', doctor: '周医生',
    sections: [
      {
        name: '血脂四项', items: [
          { k: 'LDL-C', v: '3.8', u: 'mmol/L', ref: '< 3.4', warn: true },
          { k: 'HDL-C', v: '1.6', u: 'mmol/L', ref: '> 1.0', warn: false },
          { k: 'TC', v: '5.4', u: 'mmol/L', ref: '< 5.2', warn: true },
          { k: 'TG', v: '1.1', u: 'mmol/L', ref: '< 1.7', warn: false },
        ]
      },
      {
        name: '血常规', items: [
          { k: 'WBC', v: '6.2', u: '×10⁹/L', ref: '4-10', warn: false },
          { k: 'RBC', v: '4.4', u: '×10¹²/L', ref: '3.8-5.1', warn: false },
          { k: 'HGB', v: '128', u: 'g/L', ref: '110-150', warn: false },
          { k: 'PLT', v: '210', u: '×10⁹/L', ref: '100-300', warn: false },
        ]
      },
      {
        name: '肝功能', items: [
          { k: 'ALT', v: '22', u: 'U/L', ref: '< 40', warn: false },
          { k: 'AST', v: '19', u: 'U/L', ref: '< 40', warn: false },
          { k: 'TBIL', v: '12', u: 'μmol/L', ref: '< 21', warn: false },
        ]
      },
    ],
    conclusion: '血脂中LDL-C及TC略高于参考上限，建议低脂饮食、减少饱和脂肪摄入，3个月后复查。其余项目未见明显异常。',
    ai: 'LDL-C 3.8 mmol/L，较2025年同期升高0.3，呈缓慢上升趋势。建议关注饮食结构，适量增加有氧运动。若3个月后复查仍≥3.4，考虑与医生讨论干预方案。',
  },
  'BP-0315.pdf': {
    title: '高血压社区复查',
    date: '2026-03-15', org: '社区卫生服务中心', doctor: '李医生',
    sections: [
      {
        name: '血压记录', items: [
          { k: '收缩压', v: '132', u: 'mmHg', ref: '< 140', warn: false },
          { k: '舒张压', v: '84', u: 'mmHg', ref: '< 90', warn: false },
          { k: '心率', v: '72', u: 'bpm', ref: '60-100', warn: false },
        ]
      },
      {
        name: '当前用药', items: [
          { k: '氨氯地平', v: '5mg', u: '1次/日·早', ref: '按时服用', warn: false },
        ]
      },
    ],
    conclusion: '血压控制良好，维持现有用药方案。嘱低盐饮食，2个月后复诊。',
    ai: '收缩压132 mmHg，较上次（136）下降4个单位，控制趋势向好。继续氨氯地平5mg，保持低盐低脂饮食。',
  },
  'EN-0302.pdf': {
    title: '内分泌门诊记录',
    date: '2026-03-02', org: '三甲B 内分泌科', doctor: '王主任',
    sections: [
      {
        name: '糖尿病监测', items: [
          { k: 'HbA1c', v: '7.1', u: '%', ref: '< 6.5', warn: true },
          { k: '空腹血糖', v: '6.8', u: 'mmol/L', ref: '< 6.1', warn: true },
          { k: 'C肽', v: '1.2', u: 'ng/mL', ref: '0.9-4', warn: false },
        ]
      },
      {
        name: '用药调整', items: [
          { k: '二甲双胍', v: '0.5g', u: '2次/日·餐时', ref: '继续', warn: false },
          { k: '阿托伐他汀', v: '10mg', u: '1次/日·睡前', ref: '新增', warn: false },
        ]
      },
    ],
    conclusion: 'HbA1c较上次（7.3%）有所下降，血糖控制改善，但仍高于目标值。新增阿托伐他汀调脂，3个月后复查HbA1c及血脂。',
    ai: 'HbA1c从7.6%降至7.1%，下降趋势明显，提示二甲双胍方案有效。继续关注饮食管理及规律运动，目标HbA1c < 7.0%。',
  },
  'PET-1214.pdf': {
    title: '猫咪年度体检',
    date: '2025-12-14', org: '宠爱动物医院', doctor: '陈兽医',
    sections: [
      {
        name: '血常规', items: [
          { k: 'WBC', v: '9.8', u: '×10⁹/L', ref: '5-19.5', warn: false },
          { k: 'RBC', v: '8.1', u: '×10¹²/L', ref: '5-10', warn: false },
          { k: 'HGB', v: '122', u: 'g/L', ref: '80-150', warn: false },
          { k: 'PLT', v: '312', u: '×10⁹/L', ref: '200-500', warn: false },
        ]
      },
      {
        name: '生化', items: [
          { k: 'BUN', v: '8.2', u: 'mmol/L', ref: '7-28', warn: false },
          { k: 'CREA', v: '85', u: 'μmol/L', ref: '44-159', warn: false },
          { k: 'ALT', v: '31', u: 'U/L', ref: '< 100', warn: false },
        ]
      },
      {
        name: '体格检查', items: [
          { k: '体重', v: '4.1', u: 'kg', ref: '3.5-5.0', warn: false },
          { k: '体温', v: '38.6', u: '°C', ref: '38-39.2', warn: false },
          { k: '牙结石', v: '轻度', u: '', ref: '定期洁牙', warn: true },
        ]
      },
    ],
    conclusion: '整体状况良好，血常规及生化均在正常范围。牙结石轻度，建议1年内进行一次牙科洁牙。下次年度体检 2026-12。',
    ai: '团子各项指标正常，肾功能良好（CREA 85），适合英短猫年龄。关注牙齿健康，建议预约洁牙。体重4.1 kg，处于理想区间。',
  },
};

/* ── Report Detail Drawer ───────────────────────────────────── */
const ReportDetail = ({ report, member, data, memberKey, onClose }) => {
  const extra = DETAIL_EXTRA[report.file] || {};
  const title = extra.title || report.t;
  const date = extra.date || report.d;
  const org = extra.org || report.org;
  const doctor = extra.doctor || '—';
  const conclusion = extra.conclusion || report.fullNote || (report.abn?.length ? report.abn.join('；') + '。' : '—');

  const [trendFor, setTrendFor] = React.useState(null);
  const [visitLabs, setVisitLabs] = React.useState([]);
  const [textPreview, setTextPreview] = React.useState('');
  const [textError, setTextError] = React.useState('');
  const [copyState, setCopyState] = React.useState('idle');
  const [activeAttachmentId, setActiveAttachmentId] = React.useState(report.attachmentId || null);

  const visit = (data?.visits || []).find(v => v.id === report.visitId) || null;
  const contextAttachments = React.useMemo(() => sortAttachments((data?.attachments || []).filter(a => (
    (report.visitId && a.visit_id === report.visitId) || a.id === report.attachmentId
  ))), [data?.attachments, report.visitId, report.attachmentId]);
  const imageAttachments = React.useMemo(() => contextAttachments.filter(isImageAttachment), [contextAttachments]);
  const pdfAttachments = React.useMemo(() => contextAttachments.filter(isPdfAttachment), [contextAttachments]);
  const selectedAttachment = contextAttachments.find(a => a.id === activeAttachmentId)
    || pdfAttachments[0]
    || imageAttachments[0]
    || contextAttachments.find(a => a.id === report.attachmentId)
    || null;
  const selectedFile = selectedAttachment ? attachmentFileName(selectedAttachment) : (report.file || '');
  const attachmentUrl = selectedAttachment ? (selectedAttachment.static_url || `/api/attachments/${selectedAttachment.id}/file`) : '';
  const kind = selectedAttachment ? previewKind(selectedFile) : (report.attachmentId ? previewKind(report.file) : 'none');
  const imageIndex = selectedAttachment ? imageAttachments.findIndex(a => a.id === selectedAttachment.id) : -1;
  const canPageImages = imageAttachments.length > 1 && imageIndex >= 0;

  const renderMd = (text) => {
    if (!text) return '';
    try {
      // @ts-ignore
      return marked.parse(text);
    } catch (e) {
      return text;
    }
  };

  React.useEffect(() => {
    setTrendFor(null);
    setVisitLabs([]);
    setCopyState('idle');
    setActiveAttachmentId(null);
  }, [report.id]);

  React.useEffect(() => {
    if (pdfAttachments.length) {
      setActiveAttachmentId(current => (
        pdfAttachments.some(a => a.id === current) ? current : pdfAttachments[0].id
      ));
      return;
    }
    if (imageAttachments.length) {
      setActiveAttachmentId(current => (
        imageAttachments.some(a => a.id === current) ? current : imageAttachments[0].id
      ));
      return;
    }
    if (contextAttachments.length) {
      setActiveAttachmentId(current => (
        contextAttachments.some(a => a.id === current) ? current : contextAttachments[0].id
      ));
    }
  }, [pdfAttachments, imageAttachments, contextAttachments]);

  React.useEffect(() => {
    setTextPreview('');
    setTextError('');
    if (!selectedAttachment?.id || kind !== 'text') return undefined;
    let ignore = false;
    fetch(`/api/attachments/${selectedAttachment.id}/text`)
      .then(res => {
        if (!res.ok) throw new Error(`文本预览失败 · ${res.status}`);
        return res.text();
      })
      .then(text => { if (!ignore) setTextPreview(text); })
      .catch(err => { if (!ignore) setTextError(err.message || '文本预览失败'); });
    return () => { ignore = true; };
  }, [selectedAttachment?.id, kind]);

  React.useEffect(() => {
    if (!report.visitId || extra.sections) return undefined;
    let ignore = false;
    apiJson(`/api/labs?member=${encodeURIComponent(memberKey)}&visit_id=${report.visitId}`)
      .then(labs => { if (!ignore) setVisitLabs(labs); })
      .catch(() => { });
    return () => { ignore = true; };
  }, [report.visitId, memberKey]);

  const abnItems = (report.abn || []).map((a, i) => {
    const isDiagnosis = report.tag === '就医' || report.tag === '体检';
    return {
      k: isDiagnosis ? (i === 0 ? '主要诊断' : '合并诊断') : '结论',
      v: String(a), u: '', ref: '—',
      warn: String(a).includes('↑') || String(a).includes('高'),
      noTrend: true,
    };
  });

  const visitLabSections = React.useMemo(() => {
    const panelMap = new Map();
    visitLabs.forEach(lab => {
      const panel = lab.panel || '检验结果';
      if (!panelMap.has(panel)) panelMap.set(panel, []);
      panelMap.get(panel).push({
        k: lab.test_name,
        v: lab.value,
        u: lab.unit || '',
        ref: displayRef(lab.ref_low, lab.ref_high),
        refLow: lab.ref_low,
        refHigh: lab.ref_high,
        status: lab.status,
      });
    });
    return Array.from(panelMap.entries()).map(([name, items]) => ({ name, items }));
  }, [visitLabs]);

  const sections = extra.sections || (visitLabSections.length ? visitLabSections : (
    abnItems.length ? [{ name: '摘要', items: abnItems }] : []
  ));

  const contextLabs = visitLabs.length ? visitLabs : (data?.labs || []).filter(lab => lab.visit_id === report.visitId);
  const contextMeds = (data?.meds || []).filter(med => med.visit_id === report.visitId);
  const canIncludeText = kind === 'text' && textPreview;

  const pageImage = (delta) => {
    if (!canPageImages) return;
    const nextIndex = (imageIndex + delta + imageAttachments.length) % imageAttachments.length;
    setActiveAttachmentId(imageAttachments[nextIndex].id);
  };

  const handleCopyContext = async () => {
    const context = visitContextText({
      member,
      report,
      visit,
      labs: contextLabs,
      meds: contextMeds,
      attachments: contextAttachments,
      conclusion,
      textPreview: canIncludeText ? textPreview : '',
    });
    setCopyState('copying');
    try {
      await copyTextToClipboard(context);
      setCopyState('done');
      window.setTimeout(() => setCopyState('idle'), 2200);
    } catch (err) {
      setCopyState('error');
    }
  };

  const toggleTrend = (testName, noTrend) => {
    if (noTrend) return;
    setTrendFor(prev => prev === testName ? null : testName);
  };

  const renderSection = (sec, si) => (
    <div key={si} className="sketch report-section">
      <div className="sec-label">{sec.name}</div>
      <div className="report-result-grid report-result-head">
        <div className="mono" style={{ color: 'var(--ink-ghost)', padding: '3px 0', fontSize: 9.5 }}>项目</div>
        <div className="mono" style={{ color: 'var(--ink-ghost)', padding: '3px 0', fontSize: 9.5 }}>结果</div>
        <div className="mono" style={{ color: 'var(--ink-ghost)', padding: '3px 0', fontSize: 9.5 }}>单位</div>
        <div className="mono" style={{ color: 'var(--ink-ghost)', padding: '3px 0', fontSize: 9.5 }}>参考值</div>
      </div>
      {sec.items.map((item, ii) => {
        const direction = labDirection(item);
        const abnormal = ['high', 'low', 'abnormal'].includes(direction);
        return (
          <React.Fragment key={ii}>
            <div
              className="report-result-grid report-result-row"
              style={{ cursor: item.noTrend ? 'default' : 'pointer' }}
              onClick={() => toggleTrend(item.k, item.noTrend)}
              title={item.noTrend ? '' : '点击查看历史趋势'}
            >
              <div style={{
                padding: '5px 0', borderTop: '1px dashed var(--rule)',
                fontFamily: 'Caveat, cursive', fontSize: 18,
                color: trendFor === item.k ? 'var(--accent)' : 'inherit',
              }}>
                {item.k}
              </div>
              <div style={{ padding: '5px 0', borderTop: '1px dashed var(--rule)', fontFamily: 'Caveat, cursive', fontSize: 20, fontWeight: 700, color: abnormal ? 'var(--danger)' : 'var(--ink)' }}>
                {item.v}{labDirectionMark(direction)}
              </div>
              <div style={{ padding: '5px 0', borderTop: '1px dashed var(--rule)' }} className="mono">{item.u}</div>
              <div style={{ padding: '5px 0', borderTop: '1px dashed var(--rule)' }} className="mono">{item.ref}</div>
            </div>
            {trendFor === item.k && (
              <div style={{ borderTop: '1px dashed var(--rule)', paddingTop: 4 }}>
                <MiniTrend memberKey={memberKey} testName={item.k} />
              </div>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );

  return (
    <div className="report-detail">
      <div className="report-detail__header">
        <div className="report-title-block">
          <div className="mono report-crumb">
            就诊记录详情 · {date} · {org}
          </div>
          <div className="report-title">
            <Scribble>{title}</Scribble>
          </div>
        </div>
        <div className="report-actions">
          <Btn primary onClick={onClose}>← 返回</Btn>
        </div>
      </div>

      <div className="report-meta-strip">
        <div><span className="mono">日期</span><strong>{date}</strong></div>
        <div><span className="mono">机构</span><strong>{org || '—'}</strong></div>
        <div><span className="mono">医生</span><strong>{doctor}</strong></div>
        <div><span className="mono">附件</span><strong>{selectedFile || report.file || '未关联'}</strong></div>
      </div>

      <div className="report-detail__body">
        <div className="report-insight-col">
          <div className="report-preview-card sketch">
            <div className="report-panel-head">
              <div>
                <div className="sec-label">原始附件</div>
                <div className="mono report-file-name">{selectedFile || report.file || '未关联原始文件'}</div>
              </div>
              <div className="report-panel-actions">
                {attachmentUrl ? <Btn ghost onClick={() => window.open(attachmentUrl, '_blank')}>打开原文件</Btn> : <Chip>结构化记录</Chip>}
              </div>
            </div>
            {imageAttachments.length > 0 && (
              <div className="attachment-pager">
                <button type="button" className="attachment-pager__btn" onClick={() => pageImage(-1)} disabled={!canPageImages} title="上一张">‹</button>
                <div className="attachment-pager__status mono">
                  {imageIndex >= 0 ? `${imageIndex + 1} / ${imageAttachments.length}` : `${imageAttachments.length} 张图片`}
                </div>
                <button type="button" className="attachment-pager__btn" onClick={() => pageImage(1)} disabled={!canPageImages} title="下一张">›</button>
              </div>
            )}
            <FilePreview
              kind={kind}
              file={selectedFile || report.file}
              url={attachmentUrl}
              text={textPreview}
              error={textError}
            />
            {contextAttachments.length > 1 && (
              <div className="attachment-strip">
                {contextAttachments.map(a => {
                  const file = attachmentFileName(a);
                  return (
                    <button
                      type="button"
                      key={a.id}
                      className={`attachment-strip__item ${a.id === selectedAttachment?.id ? 'active' : ''}`}
                      onClick={() => setActiveAttachmentId(a.id)}
                      title={file}
                    >
                      {previewKind(file) === 'image' ? '图片' : previewKind(file) === 'text' ? '文本' : previewKind(file) === 'pdf' ? 'PDF' : '文件'}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className="sketch report-ai-card">
            <div className="sec-label">AI 上下文</div>
            <div style={{ fontSize: 15, lineHeight: 1.7, marginTop: 6 }}>
              <Scribble>AI</Scribble> · 复制本次就诊的成员档案、就诊信息、医生结论、指标、相关用药和附件清单，便于粘贴到任意 AI 工具继续分析。
              {kind === 'text' && !textPreview && !textError && <span className="mono" style={{ color: 'var(--ink-soft)' }}> 正在读取原始文本...</span>}
            </div>
            <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Btn ghost onClick={handleCopyContext}>
                {copyState === 'copying' ? '复制中...' : copyState === 'done' ? '已复制' : copyState === 'error' ? '复制失败' : '复制就诊上下文'}
              </Btn>
              {copyState === 'done' && <span className="mono" style={{ color: 'var(--ok)' }}>可直接粘贴给 AI</span>}
              {copyState === 'error' && <span className="mono" style={{ color: 'var(--danger)' }}>浏览器拒绝剪贴板写入</span>}
            </div>
          </div>
        </div>

        <div className="report-insight-col">
          <div className="sketch report-summary-card">
            <div className="sec-label">医生结论</div>
            <div
              className="md-content report-conclusion"
              dangerouslySetInnerHTML={{ __html: renderMd(conclusion) }}
            />
          </div>

          {sections.length > 0 ? sections.map(renderSection) : (
            <div className="sketch" style={{ padding: 14 }}>
              <div className="sec-label">摘要</div>
              <div className="mono" style={{ color: 'var(--ink-soft)', padding: '10px 0' }}>暂无结构化数据</div>
            </div>
          )}
          {contextMeds.length > 0 && (
            <div className="sketch" style={{ padding: 14 }}>
              <div className="sec-label">本次处方</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                {contextMeds.map(m => {
                  const { generic, brand } = parseMedName(m.name);
                  const cat = getCatDisplay(m.category);
                  const usage = [m.dose, m.route, m.freq].filter(Boolean).join('  ·  ');
                  return (
                    <div key={m.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '7px 0', borderTop: '1px dashed var(--rule)' }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontFamily: 'Caveat, cursive', fontSize: 17, fontWeight: 700, lineHeight: 1.2 }}>{generic}</div>
                        {brand && <div className="mono" style={{ color: 'var(--ink-ghost)', fontSize: 10 }}>{brand}</div>}
                        <div className="mono" style={{ color: 'var(--ink-soft)', fontSize: 10, marginTop: 2 }}>{usage || '用法未录'}</div>
                        <div className="mono" style={{ color: 'var(--ink-ghost)', fontSize: 10, marginTop: 1 }}>
                          {m.start_date || '?'} → {m.ongoing ? '至今' : (m.end_date || '?')}
                        </div>
                      </div>
                      <Chip variant={cat.color}>{cat.label}</Chip>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};



const FilePreview = ({ kind, file, url, text, error }) => {
  const frameStyle = {
    width: '100%',
    maxWidth: '100%',
    height: 'calc(100vh - 220px)',
    minHeight: 400,
    border: '1.5px dashed var(--line)',
    borderRadius: 10,
    background: 'var(--paper-2)',
    display: 'block',
    overflow: 'hidden',
  };

  if (kind === 'pdf') {
    const pdfUrl = url ? `${url}#toolbar=0&navpanes=0&view=FitH&zoom=page-width` : '';
    return <iframe className="file-preview file-preview--pdf" title={file} src={pdfUrl} style={frameStyle} />;
  }

  if (kind === 'image') {
    return (
      <div className="file-preview file-preview--image" style={{ ...frameStyle, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'visible' }}>
        <HoverTip tip={file} className="hover-tip-block" style={{ maxWidth: '100%', maxHeight: '100%' }}>
          <img src={url} alt={file} title={file} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', display: 'block' }} />
        </HoverTip>
      </div>
    );
  }

  if (kind === 'text') {
    return (
      <pre className="file-preview file-preview--text" style={{
        ...frameStyle,
        margin: 0,
        overflow: 'auto',
        padding: 14,
        whiteSpace: 'pre-wrap',
        fontFamily: 'JetBrains Mono, monospace',
        fontSize: 11,
        lineHeight: 1.6,
      }}>
        {error || text || '正在读取文本预览...'}
      </pre>
    );
  }

  return (
    <div className="ph" style={{ height: 360, borderRadius: 12, fontSize: 13 }}>
      [ {file} ]<br />
      <span style={{ fontSize: 11, marginTop: 8, display: 'block' }}>
        {url ? '该文件类型暂不支持内嵌预览，可打开原文件。' : '未关联可预览文件。'}
      </span>
    </div>
  );
};

const ScreenMember = ({ members = [], memberKey, onChangeMember, onDataChanged, onCreateMember, onEditMember }) => {
  const member = members.find(f => f.key === memberKey) || members[0];
  const isCat = member ? isPet(member) : false;
  const TABS = isCat ? PET_TABS : HUMAN_TABS;
  const [tab, setTab] = React.useState('概览');
  const [detail, setDetail] = React.useState(null);
  const [editor, setEditor] = React.useState(null);
  const [reportImportOpen, setReportImportOpen] = React.useState(false);
  const [attachmentUploadOpen, setAttachmentUploadOpen] = React.useState(false);
  const [attachmentEditor, setAttachmentEditor] = React.useState(null);
  const [data, setData] = React.useState({
    visits: [],
    labs: [],
    meds: [],
    weights: [],
    reminders: [],
    attachments: [],
  });
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (!TABS.includes(tab)) setTab('概览');
    setDetail(null);
  }, [member?.key, isCat]);

  const loadMemberData = React.useCallback(async () => {
    if (!member?.key) return null;
    setLoading(true);
    setError('');
    try {
      const [visits, labs, meds, weights, reminders, attachments] = await Promise.all([
        apiJson(`/api/visits?member=${encodeURIComponent(member.key)}&limit=50`),
        apiJson(`/api/labs?member=${encodeURIComponent(member.key)}`),
        apiJson(`/api/meds?member=${encodeURIComponent(member.key)}`),
        apiJson(`/api/weight?member=${encodeURIComponent(member.key)}`),
        apiJson(`/api/reminders?member=${encodeURIComponent(member.key)}${member.species === 'cat' ? '&include_done=true' : ''}`),
        apiJson(`/api/attachments?member=${encodeURIComponent(member.key)}`),
      ]);
      const nextData = {
        visits: visits.items || [],
        labs,
        meds,
        weights,
        reminders,
        attachments,
      };
      setData(nextData);
      return nextData;
    } catch (err) {
      setError(err.message || '成员数据加载失败');
      return null;
    } finally {
      setLoading(false);
    }
  }, [member?.key]);

  React.useEffect(() => {
    let ignore = false;
    if (!member?.key) return undefined;
    loadMemberData().then(() => {
      if (ignore) return;
    });
    return () => { ignore = true; };
  }, [loadMemberData]);

  const mutateDaily = async (action) => {
    setSaving(true);
    setError('');
    try {
      await action();
      await loadMemberData();
      if (onDataChanged) await onDataChanged();
      setEditor(null);
    } catch (err) {
      setError(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const openCreate = (type) => setEditor({ type, item: null });
  const openChooser = () => setEditor({ type: 'choose', item: null });
  const editItem = (type, item) => setEditor({ type, item });

  const saveReminder = (values, item) => mutateDaily(() => {
    const payload = cleanPayload({ member_key: member.key, ...values });
    return item
      ? apiWrite(`/api/reminders/${item.id}`, 'PATCH', payload)
      : apiWrite('/api/reminders', 'POST', payload);
  });
  const saveCareLog = (values, item) => mutateDaily(() => {
    const payload = cleanPayload({ member_key: member.key, done: true, ...values });
    return item
      ? apiWrite(`/api/reminders/${item.id}`, 'PATCH', payload)
      : apiWrite('/api/reminders', 'POST', payload);
  });
  const completeReminder = (item) => {
    if (!window.confirm(`标记提醒「${item.title}」为完成？`)) return;
    mutateDaily(() => apiWrite(`/api/reminders/${item.id}`, 'PATCH', { done: true }));
  };
  const skipReminder = (item) => {
    if (!window.confirm(`跳过提醒「${item.title}」并进入下一个周期？`)) return;
    mutateDaily(() => apiWrite(`/api/reminders/${item.id}/skip`, 'POST'));
  };
  const deleteReminder = (item) => {
    if (!window.confirm(`删除提醒「${item.title}」？`)) return;
    mutateDaily(() => apiWrite(`/api/reminders/${item.id}`, 'DELETE'));
  };
  const saveMed = (values, item) => mutateDaily(() => {
    const payload = cleanPayload({ member_key: member.key, ...values });
    return item
      ? apiWrite(`/api/meds/${item.id}`, 'PATCH', payload)
      : apiWrite('/api/meds', 'POST', payload);
  });
  const stopMed = (item) => {
    if (!window.confirm(`停用「${item.name}」？`)) return;
    mutateDaily(() => apiWrite(`/api/meds/${item.id}`, 'PATCH', { ongoing: false, end_date: item.end_date || todayIso() }));
  };
  const deleteMed = (item) => {
    if (!window.confirm(`删除用药「${item.name}」？`)) return;
    mutateDaily(() => apiWrite(`/api/meds/${item.id}`, 'DELETE'));
  };
  const saveVisit = (values, item) => mutateDaily(() => {
    const payload = cleanPayload({ member_key: member.key, ...values, diagnosis: splitTextList(values.diagnosis_text) });
    delete payload.diagnosis_text;
    if (item) delete payload.member_key;
    return item
      ? apiWrite(`/api/visits/${item.id}`, 'PATCH', payload)
      : apiWrite('/api/visits', 'POST', payload);
  });
  const saveLab = (values, item) => mutateDaily(() => {
    const payload = cleanPayload({ member_key: member.key, ...values });
    if (payload.visit_id !== null && payload.visit_id !== undefined) payload.visit_id = Number(payload.visit_id);
    if (item) delete payload.member_key;
    return item
      ? apiWrite(`/api/labs/${item.id}`, 'PATCH', payload)
      : apiWrite('/api/labs', 'POST', payload);
  });
  const saveWeight = (values) => mutateDaily(() => apiWrite('/api/weight', 'POST', cleanPayload({ member_key: member.key, ...values })));
  const deleteWeight = (item) => {
    if (!window.confirm(`删除 ${item.date} 的体重记录？`)) return;
    mutateDaily(() => apiWrite(`/api/weight/${item.id}`, 'DELETE'));
  };
  const deleteVisit = (report) => {
    const visitId = report?.visitId || report?.id;
    if (!visitId) return;
    const title = report.t || report.chief_complaint || `#${visitId}`;
    if (!window.confirm(`删除就诊记录「${title}」？\n\n仅当没有关联化验、用药或附件时才会删除；不会自动级联删除关联数据。`)) return;
    mutateDaily(async () => {
      await apiWrite(`/api/visits/${visitId}`, 'DELETE');
      if (detail?.visitId === visitId) setDetail(null);
    });
  };
  const deleteLab = (item) => {
    if (!item?.id) return;
    const title = [item.panel, item.test_name].filter(Boolean).join(' / ') || `#${item.id}`;
    if (!window.confirm(`删除化验指标「${title}」？\n\n只删除这一条化验行，不会删除就诊记录或附件。`)) return;
    mutateDaily(() => apiWrite(`/api/labs/${item.id}`, 'DELETE'));
  };
  const saveAttachment = async (values, item) => {
    if (!item?.id) return;
    const payload = cleanPayload(values);
    if (payload.visit_id !== null && payload.visit_id !== undefined) payload.visit_id = Number(payload.visit_id);
    setSaving(true);
    setError('');
    try {
      await apiWrite(`/api/attachments/${item.id}`, 'PATCH', payload);
      await loadMemberData();
      if (onDataChanged) await onDataChanged();
      setAttachmentEditor(null);
      if (detail?.attachmentId === item.id) setDetail(null);
    } catch (err) {
      setError(err.message || '保存附件失败');
    } finally {
      setSaving(false);
    }
  };
  const deleteAttachment = async (report, deleteFile = false) => {
    const attachmentId = report?.attachmentId || report?.raw?.id;
    if (!attachmentId) return;
    const filename = report.file || report.t || `#${attachmentId}`;
    const message = deleteFile
      ? `删除附件记录并尝试删除原始归档文件「${filename}」？\n\n此操作会先移除数据库元数据，再删除当前数据目录内的原文件；不会删除就诊、化验等结构化记录。若原文件删除失败，系统会提示你手动核对。`
      : `仅移除附件记录「${filename}」？\n\n原始归档文件会保留在磁盘上；就诊、化验等结构化记录不受影响。`;
    if (!window.confirm(message)) return;
    setSaving(true);
    setError('');
    try {
      await loadMemberData();
      const result = await apiWrite(`/api/attachments/${attachmentId}?delete_file=${deleteFile ? 'true' : 'false'}`, 'DELETE');
      await loadMemberData();
      if (result?.warning) setError(result.warning);
      if (onDataChanged) await onDataChanged();
      if (detail?.attachmentId === attachmentId) setDetail(null);
    } catch (err) {
      setError(err.message || '删除附件失败');
    } finally {
      setSaving(false);
    }
  };
  if (!member) {
    return (
      <section className="sketch shadow" style={{ padding: 32, textAlign: 'center', background: 'var(--paper)' }}>
        <div className="sec-label">成员档案</div>
        <div style={{ fontFamily: 'Caveat, cursive', fontSize: 34, fontWeight: 700, margin: '8px 0' }}>还没有可查看的成员</div>
        <p className="mono" style={{ color: 'var(--ink-soft)' }}>请先新增家庭成员或宠物，再开始整理健康档案。</p>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap', marginTop: 14 }}>
          <Btn primary onClick={() => onCreateMember?.('human')}>+ 新增家庭成员</Btn>
        </div>
      </section>
    );
  }

  const attachmentReports = data.attachments.map(reportFromAttachment);
  const primaryAttachmentByVisit = new Map();
  attachmentReports.forEach(a => {
    if (!a.visitId) return;
    const prev = primaryAttachmentByVisit.get(a.visitId);
    const isNewPdf = extOf(a.file) === 'pdf';
    const isOldMd = prev?.file.endsWith('.md');
    const isOldNotPdf = prev && extOf(prev.file) !== 'pdf';
    if (!prev || (isOldMd && !a.file.endsWith('.md')) || (isNewPdf && isOldNotPdf)) {
      primaryAttachmentByVisit.set(a.visitId, a);
    }
  });
  const visitReports = data.visits.map(v => reportFromVisit(v, primaryAttachmentByVisit.get(v.id)));
  const editVisitReport = (report) => {
    const visit = data.visits.find(v => v.id === report?.visitId);
    if (visit) editItem('visit', visit);
  };
  const editVisitId = (visitId) => {
    const visit = data.visits.find(v => v.id === visitId);
    if (visit) editItem('visit', visit);
  };
  return (
    <div className="binder" style={{ boxShadow: '4px 4px 0 var(--line)' }}>
      <aside className="binder__side">
        <div className="sec-label">家庭 · Family</div>
        {members.map(f => (
          <div
            key={f.key}
            className={`rail-item ${f.key === member.key ? 'active' : ''}`}
            onClick={() => onChangeMember(f.key)}
          >
            <Avatar label={f.initial || f.name?.[0] || '?'} src={memberAvatarSrc(f)} alt={f.name} size="sm" cat={isPet(f)} ring={f.key === member.key} />
            <div style={{ lineHeight: 1.1, flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: 'Caveat, cursive', fontSize: 20, fontWeight: 700 }}>{f.name}</div>
              <div className="mono" style={{ color: 'var(--ink-soft)', fontSize: 9.5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {memberStatus(f)}
              </div>
            </div>
          </div>
        ))}
      </aside>

      <div className="binder__body" style={{ position: 'relative' }}>
        <div className="member-hero" style={{
          padding: '18px 22px', display: 'flex', justifyContent: 'space-between',
          alignItems: 'center', borderBottom: '2px solid var(--line)',
          background: isCat ? 'color-mix(in oklab, var(--accent-3) 28%, var(--paper))' : 'var(--paper)',
        }}>
          <div className="member-hero__identity" style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
            <Avatar label={member.initial || member.name?.[0] || '?'} src={memberAvatarSrc(member)} alt={member.name} size="xl" cat={isCat} ring={memberWarn(member) || isCat} />
            <div className="member-hero__text">
              <div className="mono" style={{ color: 'var(--ink-soft)' }}>
                {isCat ? '宠物档案 · ' : '档案 · '}{member.full_name || member.name}
              </div>
              <div className="member-hero__name" style={{ fontFamily: 'Caveat, cursive', fontSize: 42, fontWeight: 700, lineHeight: 1 }}>
                <Scribble>{member.name}</Scribble>
              </div>
              <div className="mono" style={{ color: 'var(--ink-soft)', marginTop: 6 }}>
                {speciesText(member, data.weights)}
              </div>
            </div>
          </div>
          <div className="member-hero__actions" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <Btn ghost onClick={() => onEditMember?.(member)}>编辑资料</Btn>
            {window.healthReport && <Btn onClick={() => setReportImportOpen(true)}>+ 上传报告/附件</Btn>}
            <Btn primary onClick={openChooser}>+ 新增记录</Btn>
          </div>
        </div>

        <div className="tabs-row">
          {TABS.map(t => (
            <div key={t} className={`t ${t === tab ? 'active' : ''}`} onClick={() => { setTab(t); setDetail(null); }}>{t}</div>
          ))}
        </div>

        <div className="member-content" style={{ padding: 22, background: 'var(--paper)' }}>
          {error && <div className="sketch" style={{ padding: 14, marginBottom: 14, color: 'var(--danger)' }}>{error}</div>}
          {loading && <div className="mono" style={{ marginBottom: 14, color: 'var(--ink-soft)' }}>正在同步成员数据...</div>}

          {detail ? (
            <ReportDetail report={detail} member={member} data={data} memberKey={member.key} onClose={() => setDetail(null)} />
          ) : (
            <>
              {!isCat && tab === '概览' && (
                <TabOverview
                  member={member}
                  labs={data.labs}
                  visits={visitReports}
                  meds={data.meds}
                  reminders={data.reminders}
                  attachments={data.attachments}
                  onOpen={setDetail}
                />
              )}
              {!isCat && tab === '体检报告' && <TabCheckup data={data} memberKey={member.key} reports={visitReports.filter(isCheckupReport)} onOpen={setDetail} onAddLab={() => openCreate('lab')} onEditLab={(item) => editItem('lab', item)} onDeleteLab={deleteLab} onEditVisit={editVisitId} />}
              {!isCat && tab === '就医记录' && <TabReports reports={visitReports} kind="就医" onOpen={setDetail} onAdd={() => openCreate('visit')} onEdit={editVisitReport} onDelete={deleteVisit} />}
              {!isCat && tab === '用药' && <TabMeds meds={data.meds} visits={data.visits} onAdd={() => openCreate('med')} onEdit={(item) => editItem('med', item)} onStop={stopMed} onDelete={deleteMed} />}
              {!isCat && tab === '附件库' && <TabAttachments reports={attachmentReports} onOpen={setDetail} onAddAttachment={() => setAttachmentUploadOpen(true)} onImport={window.healthReport ? () => setReportImportOpen(true) : undefined} onEditAttachment={(report) => setAttachmentEditor(report.raw)} onDeleteAttachment={deleteAttachment} />}
              {!isCat && tab === '提醒' && <TabReminders items={data.reminders} onAdd={() => openCreate('reminder')} onEdit={(item) => editItem('reminder', item)} onDone={completeReminder} onSkip={skipReminder} onDelete={deleteReminder} />}

              {isCat && tab === '概览' && (
                <TabPetOverview
                  member={member}
                  labs={data.labs}
                  visits={data.visits}
                  meds={data.meds}
                  weights={data.weights}
                  reminders={data.reminders}
                  attachments={data.attachments}
                  onOpen={setDetail}
                />
              )}
              {isCat && tab === '记事' && <TabPetCare reminders={data.reminders} attachments={data.attachments} onAdd={() => openCreate('care')} onEdit={(item) => editItem('care', item)} onDelete={deleteReminder} />}
              {isCat && tab === '疫苗接种' && <TabVax labs={data.labs} attachments={data.attachments} onAddLab={() => openCreate('lab')} />}
              {isCat && tab === '就医记录' && <TabReports reports={visitReports} kind="就医" onOpen={setDetail} onAdd={() => openCreate('visit')} onEdit={editVisitReport} onDelete={deleteVisit} />}
              {isCat && tab === '用药' && <TabMeds meds={data.meds} visits={data.visits} onAdd={() => openCreate('med')} onEdit={(item) => editItem('med', item)} onStop={stopMed} onDelete={deleteMed} />}
              {isCat && tab === '体重趋势' && <TabPetWeight member={member} weights={data.weights} onAdd={() => openCreate('weight')} onDelete={deleteWeight} />}
              {isCat && tab === '附件库' && <TabAttachments reports={attachmentReports} onOpen={setDetail} onAddAttachment={() => setAttachmentUploadOpen(true)} onImport={window.healthReport ? () => setReportImportOpen(true) : undefined} onEditAttachment={(report) => setAttachmentEditor(report.raw)} onDeleteAttachment={deleteAttachment} />}
              {isCat && tab === '提醒' && <TabReminders items={data.reminders.filter(r => !r.done)} onAdd={() => openCreate('reminder')} onEdit={(item) => editItem('reminder', item)} onDone={completeReminder} onSkip={skipReminder} onDelete={deleteReminder} />}
            </>
          )}
        </div>

        {reportImportOpen && <ReportImportModal
          member={member}
          onClose={() => setReportImportOpen(false)}
          onImported={async () => { await loadMemberData(); await onDataChanged?.(); }}
        />}

        {attachmentUploadOpen && <AttachmentUploadModal
          member={member}
          visits={data.visits}
          onClose={() => setAttachmentUploadOpen(false)}
          onUploaded={async () => { await loadMemberData(); await onDataChanged?.(); }}
        />}

        {attachmentEditor && <AttachmentEditorModal
          attachment={attachmentEditor}
          visits={data.visits}
          saving={saving}
          onClose={() => setAttachmentEditor(null)}
          onSave={saveAttachment}
        />}

        {editor && (
          <DailyEditor
            editor={editor}
            member={member}
            isPetMember={isCat}
            saving={saving}
            onClose={() => setEditor(null)}
            onChoose={openCreate}
            onSaveReminder={saveReminder}
            onSaveCareLog={saveCareLog}
            visits={data.visits}
            onSaveVisit={saveVisit}
            onSaveLab={saveLab}
            onSaveMed={saveMed}
            onSaveWeight={saveWeight}
          />
        )}
      </div>
    </div>
  );
};

const AttachmentEditorModal = ({ attachment, visits = [], saving, onClose, onSave }) => {
  const [form, setForm] = React.useState({
    date: attachment?.date || todayIso(),
    title: attachment?.title || '',
    org: attachment?.org || '',
    tag: attachment?.tag || '',
    visit_id: attachment?.visit_id ? String(attachment.visit_id) : '',
    notes: attachment?.notes || '',
  });

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

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="编辑附件元数据">
      <div className="daily-modal sketch shadow" style={{ maxWidth: 680 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, marginBottom: 12 }}>
          <div>
            <div className="sec-label">附件库</div>
            <div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>编辑附件信息</div>
          </div>
          <Btn ghost disabled={saving} onClick={onClose}>关闭</Btn>
        </div>
        <form className="daily-form" onSubmit={(e) => { e.preventDefault(); onSave(form, attachment); }}>
          <div className="mono span-2" style={{ color: 'var(--ink-soft)' }}>
            原始文件：{attachmentFileName(attachment)}。此处只修改附件元数据和就诊关联，不提供替换原始文件入口。
          </div>
          <label>标题 *<input required value={form.title} onChange={e => set('title', e.target.value)} /></label>
          <label>日期 *<input required type="date" value={form.date} onChange={e => set('date', e.target.value)} /></label>
          <label>机构<input value={form.org} onChange={e => set('org', e.target.value)} placeholder="医院、体检中心或诊所" /></label>
          <label>标签<input value={form.tag} onChange={e => set('tag', e.target.value)} placeholder="发票、影像、处方、说明等" /></label>
          <label className="span-2">关联就诊<select value={form.visit_id} onChange={e => set('visit_id', e.target.value)}>
            <option value="">不关联</option>
            {visits.map(v => <option key={v.id} value={v.id}>{v.date} · {v.type || '就诊'} · {v.hospital || v.chief_complaint || `#${v.id}`}</option>)}
          </select></label>
          <label className="span-2">备注<textarea rows="4" value={form.notes} onChange={e => set('notes', e.target.value)} /></label>
          <div className="form-actions span-2">
            <Btn ghost disabled={saving} onClick={onClose}>取消</Btn>
            <Btn primary type="submit" disabled={saving}>{saving ? '保存中...' : '保存'}</Btn>
          </div>
        </form>
      </div>
    </div>
  );
};

const DailyEditor = ({ editor, member, isPetMember, visits = [], saving, onClose, onChoose, onSaveReminder, onSaveCareLog, onSaveVisit, onSaveLab, onSaveMed, onSaveWeight }) => {
  const title = editor.type === 'choose'
    ? '新增记录'
    : editor.type === 'reminder'
      ? editor.item ? '编辑提醒' : '新增提醒'
      : editor.type === 'visit'
        ? (editor.item ? '编辑就诊记录' : '新增就诊记录')
        : editor.type === 'lab'
          ? (editor.item ? '编辑化验指标' : '新增化验指标')
          : editor.type === 'med'
            ? editor.item ? '编辑用药' : '新增用药'
            : editor.type === 'care'
              ? editor.item ? '编辑记事' : '添加记事'
              : '记录体重';

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

  return (
    <div className="modal-backdrop">
      <div className="daily-modal sketch shadow">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, marginBottom: 12 }}>
          <div>
            <div className="sec-label">{member.name}</div>
            <div style={{ fontFamily: 'Caveat, cursive', fontSize: 32, fontWeight: 700, lineHeight: 1 }}>{title}</div>
          </div>
          <Btn ghost onClick={onClose}>关闭</Btn>
        </div>
        {editor.type === 'choose' && (
          <div className="daily-choice-grid">
            <button className="daily-choice" onClick={() => onChoose('visit')}>
              <span>就诊记录</span>
              <small>门诊、复诊、体检或其他接触记录</small>
            </button>
            <button className="daily-choice" onClick={() => onChoose('lab')}>
              <span>化验指标</span>
              <small>手动补录单项检验值，可关联就诊</small>
            </button>
            <button className="daily-choice" onClick={() => onChoose('reminder')}>
              <span>提醒</span>
              <small>复诊、复查、驱虫、疫苗等</small>
            </button>
            <button className="daily-choice" onClick={() => onChoose('med')}>
              <span>用药</span>
              <small>药名、剂量、频次、起止日期</small>
            </button>
            {isPetMember && (
              <button className="daily-choice" onClick={() => onChoose('care')}>
                <span>记事</span>
                <small>驱虫、洗澡、换猫砂</small>
              </button>
            )}
            <button className="daily-choice" onClick={() => onChoose('weight')}>
              <span>体重</span>
              <small>日常体重记录</small>
            </button>
          </div>
        )}
        {editor.type === 'reminder' && <ReminderForm item={editor.item} saving={saving} onSubmit={onSaveReminder} onCancel={onClose} />}
        {editor.type === 'visit' && <VisitForm item={editor.item} saving={saving} onSubmit={onSaveVisit} onCancel={onClose} />}
        {editor.type === 'lab' && <LabForm item={editor.item} visits={visits} saving={saving} onSubmit={onSaveLab} onCancel={onClose} />}
        {editor.type === 'care' && <CareLogForm item={editor.item} saving={saving} onSubmit={onSaveCareLog} onCancel={onClose} />}
        {editor.type === 'med' && <MedForm item={editor.item} saving={saving} onSubmit={onSaveMed} onCancel={onClose} />}
        {editor.type === 'weight' && <WeightForm saving={saving} onSubmit={onSaveWeight} onCancel={onClose} />}
      </div>
    </div>
  );
};

const VisitForm = ({ item, saving, onSubmit, onCancel }) => {
  const [form, setForm] = React.useState({
    date: item?.date || todayIso(),
    type: item?.type || '就医',
    hospital: item?.hospital || '',
    department: item?.department || '',
    doctor: item?.doctor || '',
    chief_complaint: item?.chief_complaint || '',
    severity: item?.severity || '',
    diagnosis_text: Array.isArray(item?.diagnosis) ? item.diagnosis.join('\n') : '',
    notes: item?.notes || '',
    note_full: item?.note_full || '',
  });
  const set = (key, value) => setForm(prev => ({ ...prev, [key]: value }));
  return (
    <form className="daily-form" onSubmit={(e) => { e.preventDefault(); onSubmit(form, item); }}>
      <div className="mono span-2" style={{ color: 'var(--ink-soft)', marginBottom: -2 }}>日期默认今天，请按实际就诊/体检日期修改。</div>
      <label>日期 *<input required type="date" value={form.date} onChange={e => set('date', e.target.value)} /></label>
      <label>类型<select value={form.type} onChange={e => set('type', e.target.value)}>
        <option value="就医">就医</option>
        <option value="体检">体检</option>
        <option value="其他">其他</option>
      </select></label>
      <label>医院/机构<input value={form.hospital} onChange={e => set('hospital', e.target.value)} placeholder="例如：社区医院" /></label>
      <label>科室<input value={form.department} onChange={e => set('department', e.target.value)} placeholder="例如：内科" /></label>
      <label>医生<input value={form.doctor} onChange={e => set('doctor', e.target.value)} /></label>
      <label>严重程度<select value={form.severity} onChange={e => set('severity', e.target.value)}>
        <option value="">未标记</option>
        <option value="轻微">轻微</option>
        <option value="一般">一般</option>
        <option value="严重">严重</option>
      </select></label>
      <label className="span-2">主诉/原因<input value={form.chief_complaint} onChange={e => set('chief_complaint', e.target.value)} placeholder="例如：年度体检、咳嗽复诊" /></label>
      <label className="span-2">诊断/结论（每行或逗号分隔）<textarea value={form.diagnosis_text} onChange={e => set('diagnosis_text', e.target.value)} rows="3" /></label>
      <label className="span-2">备注<textarea value={form.notes} onChange={e => set('notes', e.target.value)} rows="3" /></label>
      <label className="span-2">完整记录<textarea value={form.note_full} onChange={e => set('note_full', e.target.value)} rows="5" placeholder="可粘贴门诊小结或人工整理后的完整内容" /></label>
      <div className="form-actions">
        <Btn ghost onClick={onCancel}>取消</Btn>
        <Btn primary type="submit">{saving ? '保存中...' : '保存'}</Btn>
      </div>
    </form>
  );
};

const LabForm = ({ item, visits = [], saving, onSubmit, onCancel }) => {
  const latestVisit = visits[0] || null;
  const [form, setForm] = React.useState({
    date: item?.date || latestVisit?.date || todayIso(),
    panel: item?.panel || '',
    test_name: item?.test_name || '',
    value: item?.value || '',
    unit: item?.unit || '',
    ref_low: item?.ref_low || '',
    ref_high: item?.ref_high || '',
    status: item?.status || '',
    visit_id: item ? (item.visit_id ? String(item.visit_id) : '') : latestVisit?.id ? String(latestVisit.id) : '',
    source_file: item?.source_file || '',
  });
  const set = (key, value) => setForm(prev => ({ ...prev, [key]: value }));
  const setVisit = (value) => {
    const visit = visits.find(v => String(v.id) === value);
    setForm(prev => ({ ...prev, visit_id: value, date: visit?.date || prev.date }));
  };
  return (
    <form className="daily-form" onSubmit={(e) => { e.preventDefault(); onSubmit(form, item); }}>
      <div className="mono span-2" style={{ color: 'var(--ink-soft)', marginBottom: -2 }}>日期默认取最近就诊日期；没有就诊时默认今天，均可修改。</div>
      <label>日期 *<input required type="date" value={form.date} onChange={e => set('date', e.target.value)} /></label>
      <label>关联就诊<select value={form.visit_id} onChange={e => setVisit(e.target.value)}>
        <option value="">不关联</option>
        {visits.map(v => <option key={v.id} value={v.id}>{v.date} · {v.type || '就诊'} · {v.hospital || v.chief_complaint || `#${v.id}`}</option>)}
      </select></label>
      <label>检查项目 *<input required value={form.panel} onChange={e => set('panel', e.target.value)} placeholder="例如：血常规" /></label>
      <label>指标名称 *<input required value={form.test_name} onChange={e => set('test_name', e.target.value)} placeholder="例如：血红蛋白" /></label>
      <label>数值<input value={form.value} onChange={e => set('value', e.target.value)} /></label>
      <label>单位<input value={form.unit} onChange={e => set('unit', e.target.value)} placeholder="例如：g/L" /></label>
      <label>参考下限<input value={form.ref_low} onChange={e => set('ref_low', e.target.value)} /></label>
      <label>参考上限<input value={form.ref_high} onChange={e => set('ref_high', e.target.value)} /></label>
      <label>状态<select value={form.status} onChange={e => set('status', e.target.value)}>
        <option value="">未标记</option>
        <option value="normal">正常</option>
        <option value="high">偏高</option>
        <option value="low">偏低</option>
        <option value="abnormal">异常</option>
      </select></label>
      <label>来源文件<input value={form.source_file} onChange={e => set('source_file', e.target.value)} placeholder="可选" /></label>
      <div className="form-actions">
        <Btn ghost onClick={onCancel}>取消</Btn>
        <Btn primary type="submit">{saving ? '保存中...' : '保存'}</Btn>
      </div>
    </form>
  );
};

const ReminderForm = ({ item, saving, onSubmit, onCancel }) => {
  const [form, setForm] = React.useState({
    date: item?.date || todayIso(),
    title: item?.title || '',
    kind: item?.kind || '复查',
    priority: item?.priority || 'normal',
    notes: item?.notes || '',
  });
  const set = (key, value) => setForm(prev => ({ ...prev, [key]: value }));
  return (
    <form className="daily-form" onSubmit={(e) => { e.preventDefault(); onSubmit(form, item); }}>
      <label>日期<input required type="date" value={form.date} onChange={e => set('date', e.target.value)} /></label>
      <label>标题<input required value={form.title} onChange={e => set('title', e.target.value)} placeholder="例如：复查血脂" /></label>
      <label>类型<input value={form.kind} onChange={e => set('kind', e.target.value)} placeholder="复查 / 就医 / 驱虫 / 洗澡 / 换猫砂" /></label>
      <label>优先级<select value={form.priority} onChange={e => set('priority', e.target.value)}>
        <option value="normal">普通</option>
        <option value="high">重要</option>
        <option value="low">低</option>
      </select></label>
      <label className="span-2">备注<textarea value={form.notes} onChange={e => set('notes', e.target.value)} rows="3" /></label>
      <div className="form-actions">
        <Btn ghost onClick={onCancel}>取消</Btn>
        <Btn primary type="submit">{saving ? '保存中...' : '保存'}</Btn>
      </div>
    </form>
  );
};

const CareLogForm = ({ item, saving, onSubmit, onCancel }) => {
  const [form, setForm] = React.useState({
    date: item?.date || todayIso(),
    kind: PET_CARE_KIND_SET.has(item?.kind) ? item.kind : PET_CARE_KINDS[0],
    title: item?.title || '',
    notes: item?.notes || '',
  });
  const set = (key, value) => setForm(prev => ({ ...prev, [key]: value }));
  return (
    <form className="daily-form" onSubmit={(e) => { e.preventDefault(); onSubmit({ ...form, title: form.title || form.kind }, item); }}>
      <label>日期<input required type="date" value={form.date} onChange={e => set('date', e.target.value)} /></label>
      <label>类型<select required value={form.kind} onChange={e => set('kind', e.target.value)}>
        {PET_CARE_KINDS.map(kind => <option key={kind} value={kind}>{kind}</option>)}
      </select></label>
      <label>备注标题<input value={form.title} onChange={e => set('title', e.target.value)} placeholder={`例如：${form.kind}（可选）`} /></label>
      <label className="span-2">备注<textarea value={form.notes} onChange={e => set('notes', e.target.value)} rows="2" /></label>
      <div className="form-actions">
        <Btn ghost onClick={onCancel}>取消</Btn>
        <Btn primary type="submit">{saving ? '保存中...' : item ? '保存' : '记录'}</Btn>
      </div>
    </form>
  );
};

const MedForm = ({ item, saving, onSubmit, onCancel }) => {
  const [form, setForm] = React.useState({
    name: item?.name || '',
    dose: item?.dose || '',
    freq: item?.freq || '',
    route: item?.route || '',
    start_date: item?.start_date || todayIso(),
    end_date: item?.end_date || '',
    ongoing: item?.ongoing ?? true,
    notes: item?.notes || '',
  });
  const set = (key, value) => setForm(prev => ({ ...prev, [key]: value }));
  return (
    <form className="daily-form" onSubmit={(e) => { e.preventDefault(); onSubmit(form, item); }}>
      <label>药名<input required value={form.name} onChange={e => set('name', e.target.value)} placeholder="例如：二甲双胍" /></label>
      <label>剂量<input value={form.dose} onChange={e => set('dose', e.target.value)} placeholder="例如：0.5g" /></label>
      <label>频次<input value={form.freq} onChange={e => set('freq', e.target.value)} placeholder="例如：2次/日" /></label>
      <label>途径<input value={form.route} onChange={e => set('route', e.target.value)} placeholder="口服 / 外用" /></label>
      <label>开始日期<input type="date" value={form.start_date || ''} onChange={e => set('start_date', e.target.value)} /></label>
      <label>结束日期<input type="date" value={form.end_date || ''} onChange={e => set('end_date', e.target.value)} /></label>
      <label className="check span-2">
        <input type="checkbox" checked={form.ongoing} onChange={e => set('ongoing', e.target.checked)} />
        <span>仍在使用</span>
      </label>
      <label className="span-2">备注<textarea value={form.notes} onChange={e => set('notes', e.target.value)} rows="3" /></label>
      <div className="form-actions">
        <Btn ghost onClick={onCancel}>取消</Btn>
        <Btn primary type="submit">{saving ? '保存中...' : '保存'}</Btn>
      </div>
    </form>
  );
};

const WeightForm = ({ saving, onSubmit, onCancel }) => {
  const [form, setForm] = React.useState({ date: todayIso(), weight_kg: '', notes: '' });
  const set = (key, value) => setForm(prev => ({ ...prev, [key]: value }));
  return (
    <form className="daily-form" onSubmit={(e) => { e.preventDefault(); onSubmit({ ...form, weight_kg: Number(form.weight_kg) }); }}>
      <label>日期<input required type="date" value={form.date} onChange={e => set('date', e.target.value)} /></label>
      <label>体重 kg<input required type="number" step="0.01" min="0" value={form.weight_kg} onChange={e => set('weight_kg', e.target.value)} placeholder="4.20" /></label>
      <label className="span-2">备注<textarea value={form.notes} onChange={e => set('notes', e.target.value)} rows="3" /></label>
      <div className="form-actions">
        <Btn ghost onClick={onCancel}>取消</Btn>
        <Btn primary type="submit">{saving ? '保存中...' : '保存'}</Btn>
      </div>
    </form>
  );
};

const dateLabel = (date) => String(date || '').slice(0, 10) || '日期未录';

const daysFromToday = (date) => {
  if (!date) return null;
  const target = new Date(`${date}T00:00:00`);
  if (Number.isNaN(target.getTime())) return null;
  const base = new Date();
  base.setHours(0, 0, 0, 0);
  return Math.round((target - base) / 86400000);
};

const relationText = (items, emptyText) => {
  const list = (items || []).filter(Boolean);
  return list.length ? list.join(' / ') : emptyText;
};

const makeFocusItems = ({ member, labs, visits, meds, reminders }) => {
  const items = [];
  const recentVisits = visits.slice(0, 6);
  const diagnosisCounts = new Map();
  recentVisits.forEach(v => (v.abn || []).forEach(d => {
    const name = String(d || '').trim();
    if (!name || name === '已记录') return;
    diagnosisCounts.set(name, (diagnosisCounts.get(name) || 0) + 1);
  }));
  const repeated = Array.from(diagnosisCounts.entries()).sort((a, b) => b[1] - a[1])[0];
  const activeMeds = meds.filter(m => m.ongoing);
  const abnormalLabs = latestByName(labs).filter(l => ['high', 'low', 'abnormal'].includes(l.status)).slice(0, 3);
  const nextReminder = reminders.filter(r => !r.done).sort((a, b) => a.date.localeCompare(b.date))[0] || member.next_reminder;
  const latestVisit = recentVisits[0];

  if (nextReminder) {
    const delta = daysFromToday(nextReminder.date);
    items.push({
      title: nextReminder.title,
      meta: `${dateLabel(nextReminder.date)} · ${nextReminder.kind || '提醒'}`,
      body: delta === null ? '有一条未完成提醒需要回看。' : delta >= 0 ? `距离提醒还有 ${delta} 天。` : `已超过提醒日期 ${Math.abs(delta)} 天。`,
      tone: delta !== null && delta < 0 ? 'danger' : 'accent',
    });
  }

  if (repeated && repeated[1] >= 2) {
    items.push({
      title: `${repeated[0]} 近期反复出现`,
      meta: `最近 ${recentVisits.length} 次记录中出现 ${repeated[1]} 次`,
      body: latestVisit ? `最近一次为 ${dateLabel(latestVisit.d)}，来源：${latestVisit.org || '医疗记录'}。` : '建议结合就诊记录回看病程变化。',
      tone: 'accent-2',
    });
  } else if (latestVisit) {
    items.push({
      title: latestVisit.t || '最近就诊记录',
      meta: `${dateLabel(latestVisit.d)} · ${latestVisit.org || '医疗机构'}`,
      body: relationText(latestVisit.abn, '本次记录暂无结构化诊断。'),
      tone: 'accent-2',
      report: latestVisit,
    });
  }

  if (activeMeds.length) {
    items.push({
      title: `在用药物 ${activeMeds.length} 种`,
      meta: activeMeds.slice(0, 3).map(m => parseMedName(m.name).generic).join(' / '),
      body: '适合在复诊前核对剂量、频次、是否仍需继续使用。',
      tone: 'accent-3',
    });
  }

  if (abnormalLabs.length) {
    items.push({
      title: `异常检验 ${abnormalLabs.length} 项`,
      meta: abnormalLabs.map(l => `${l.test_name} ${l.value}${l.unit || ''}`).join(' / '),
      body: '指标详情保留在体检报告中，首页只提示需要结合报告回看。',
      tone: 'danger',
    });
  }

  return items.slice(0, 3);
};

const OverviewPanel = ({ title, right, children, className = '' }) => (
  <section className={`overview-panel ${className}`}>
    <div className="overview-panel__head">
      <span className="sec-label">{title}</span>
      {right && <span className="mono">{right}</span>}
    </div>
    {children}
  </section>
);

const TabOverview = ({ member, labs, visits, meds = [], reminders = [], attachments = [], onOpen }) => {
  const focusItems = makeFocusItems({ member, labs, visits, meds, reminders });
  const pendingReminders = reminders.filter(r => !r.done).sort((a, b) => a.date.localeCompare(b.date)).slice(0, 4);
  const activeMeds = meds.filter(m => m.ongoing);
  const timeline = visits.slice(0, 6);
  const summary = [
    ['就诊记录', visits.length],
    ['检查指标', labs.length],
    ['用药记录', meds.length],
    ['附件', attachments.length],
  ];

  return (
    <div className="overview-workbench">
      <div className="overview-main">
        <OverviewPanel title="当前关注" right={focusItems.length ? `${focusItems.length} 项` : '暂无突出事项'} className="overview-focus-panel">
          {focusItems.length === 0 ? (
            <div className="overview-empty">暂无需要优先处理的事项。最近记录会在这里形成健康上下文。</div>
          ) : (
            <div className="focus-list">
              {focusItems.map((item, idx) => (
                <button
                  key={`${item.title}-${idx}`}
                  className={`focus-card ${item.tone || ''}`}
                  onClick={() => item.report && onOpen && onOpen(item.report)}
                  disabled={!item.report}
                >
                  <div className="focus-card__title">{item.title}</div>
                  <div className="mono focus-card__meta">{item.meta}</div>
                  <div className="focus-card__body">{item.body}</div>
                </button>
              ))}
            </div>
          )}
        </OverviewPanel>

        <OverviewPanel title="最近健康时间线" right={`${timeline.length} 条`}>
          {timeline.length === 0 ? (
            <div className="overview-empty">暂无就诊记录</div>
          ) : (
            <div className="health-timeline">
              {timeline.map(item => (
                <div key={item.id} className="timeline-item">
                  <div className="timeline-date mono">{dateLabel(item.d)}</div>
                  <div className="timeline-body">
                    <div className="timeline-title">{item.t}</div>
                    <div className="mono timeline-meta">{item.org || '医疗机构'} · {relationText(item.abn, '已记录')}</div>
                    <div className="timeline-tags">
                      <Chip variant="accent">{item.tag || item.type || '就医'}</Chip>
                      {reportChipLabels(item).map((tag, i) => (
                        <Chip key={`${item.id}-${i}`} variant={severityBadgeVariant(item.severity)}>{tag}</Chip>
                      ))}
                    </div>
                  </div>
                  <Btn ghost onClick={() => onOpen && onOpen(item)}>查看 →</Btn>
                </div>
              ))}
            </div>
          )}
        </OverviewPanel>
      </div>

      <aside className="overview-side">
        <OverviewPanel title="待办与提醒" right={pendingReminders.length ? `${pendingReminders.length} 条` : ''}>
          {pendingReminders.length === 0 ? (
            <div className="overview-empty small">暂无未完成提醒</div>
          ) : (
            <div className="reminder-stack">
              {pendingReminders.map(r => {
                const delta = daysFromToday(r.date);
                return (
                  <div key={r.id} className={`reminder-item ${delta !== null && delta < 0 ? 'is-overdue' : ''}`}>
                    <div>
                      <div className="reminder-title">{r.title}</div>
                      <div className="mono reminder-meta">{r.kind || '提醒'} · {dateLabel(r.date)}</div>
                    </div>
                    <span className="mono reminder-delta">
                      {delta === null ? '—' : delta === 0 ? '今天' : delta > 0 ? `${delta}天` : `过期${Math.abs(delta)}天`}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </OverviewPanel>

        <OverviewPanel title="风险与禁忌">
          <div className="risk-list">
            <div>
              <div className="mono risk-label">过敏</div>
              <div className="risk-value">{relationText(member.allergies, '暂无过敏记录')}</div>
            </div>
            <div>
              <div className="mono risk-label">慢病 / 长期问题</div>
              <div className="risk-value">{relationText(member.chronic, '暂无慢病记录')}</div>
            </div>
            <div>
              <div className="mono risk-label">在用药物</div>
              <div className="risk-value">{activeMeds.length ? activeMeds.slice(0, 4).map(m => parseMedName(m.name).generic).join(' / ') : '暂无在用药物'}</div>
            </div>
          </div>
        </OverviewPanel>

        <OverviewPanel title="档案摘要">
          <div className="archive-summary">
            {summary.map(([label, value]) => (
              <div key={label} className="archive-stat">
                <span className="mono">{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <div className="mono overview-note">
            {member.doctor ? `常去机构 · ${member.doctor}` : '常去机构未录入'}
          </div>
        </OverviewPanel>
      </aside>
    </div>
  );
};

const MiniTrend = ({ memberKey, testName }) => {
  const [trend, setTrend] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let ignore = false;
    setTrend(null);
    setLoading(true);
    apiJson(`/api/labs/trend?member=${encodeURIComponent(memberKey)}&test_name=${encodeURIComponent(testName)}`)
      .then(d => { if (!ignore) { setTrend(d); setLoading(false); } })
      .catch(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [memberKey, testName]);

  if (loading) {
    return <div className="mono" style={{ color: 'var(--ink-soft)', padding: '8px 0', fontSize: 11 }}>加载趋势中…</div>;
  }

  const points = (trend?.points || []).map(p => p.value);
  const ref = trend ? refForLab({ ref_low: trend.ref_low, ref_high: trend.ref_high }) : null;
  const latestPoint = (trend?.points || [])[points.length - 1];
  const direction = labDirection(latestPoint);
  const hasKnownStatus = ['high', 'low', 'abnormal', 'normal'].includes(direction);
  const warn = ['high', 'low', 'abnormal'].includes(direction);
  const statusLabel = !hasKnownStatus
    ? '状态未标记'
    : direction === 'high'
      ? '当前偏高'
      : direction === 'low'
        ? '当前偏低'
        : warn
          ? '当前异常'
          : '在参考范围内';

  if (points.length < 2) {
    return <div className="mono" style={{ color: 'var(--ink-soft)', padding: '8px 0', fontSize: 11 }}>历史记录不足以绘图</div>;
  }

  return (
    <div style={{ padding: '10px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <span className="mono" style={{ color: 'var(--ink-soft)', fontSize: 10 }}>
          {points.length} 次记录{ref ? ` · 参考 ${ref[0]}–${ref[1]} ${trend?.unit || ''}` : ''}
        </span>
        <span className="mono" style={{ color: !hasKnownStatus ? 'var(--ink-soft)' : warn ? 'var(--danger)' : 'var(--ok)', fontSize: 10 }}>
          {statusLabel}
        </span>
      </div>
      <EChartLine
        points={(trend?.points || []).map(p => ({ ...p, value: p.value, label: p.date }))}
        height={150}
        unit={trend?.unit || ''}
        yName={testName}
        color={warn ? 'var(--danger)' : 'var(--accent)'}
        refBand={ref}
        emptyText="暂无指标趋势"
      />
    </div>
  );
};

/* ── Checkup Tab ─────────────────────────────────────────────── */
const CheckupLabRow = ({ item, memberKey, autoExpanded, onEdit, onDelete }) => {
  const direction = labDirection(item);
  const abnormal = ['high', 'low', 'abnormal'].includes(direction);
  const [expanded, setExpanded] = React.useState(autoExpanded);

  return (
    <div className="ck-lab-item">
      <div
        className={`ck-lab-row ${abnormal ? 'ck-lab-row--abn' : ''}`}
        onClick={() => setExpanded(e => !e)}
        title="点击折叠/展开趋势"
      >
        <div className="ck-lab-name">{item.k}</div>
        <div className="ck-lab-val" style={{ color: abnormal ? 'var(--danger)' : 'var(--ink)' }}>
          {item.v}{labDirectionMark(direction)}
        </div>
        <div className="mono ck-lab-unit">{item.u}</div>
        <div className="mono ck-lab-ref">{item.ref}</div>
        {onEdit && item.raw && <Btn ghost onClick={(e) => { e.stopPropagation(); onEdit(item.raw); }}>编辑</Btn>}
        {onDelete && item.raw && <Btn ghost onClick={(e) => { e.stopPropagation(); onDelete(item.raw); }}>删除</Btn>}
        <div className="mono ck-lab-chevron">{expanded ? '▲' : '▼'}</div>
      </div>
      {expanded && (
        <div className="ck-trend-wrap">
          <MiniTrend memberKey={memberKey} testName={item.k} />
        </div>
      )}
    </div>
  );
};

const TabCheckup = ({ data, memberKey, reports, onOpen, onAddLab, onEditLab, onDeleteLab, onEditVisit }) => {
  const checkupReports = React.useMemo(() => (
    reports.slice().sort((a, b) => b.d.localeCompare(a.d))
  ), [reports]);
  const [selectedId, setSelectedId] = React.useState(null);
  const [showNormal, setShowNormal] = React.useState(false);

  const selected = checkupReports.find(r => r.id === selectedId) || checkupReports[0] || null;
  const effectiveId = selected?.id ?? null;

  const selectCheckup = (id) => { setSelectedId(id); setShowNormal(false); };

  const extra = selected ? (DETAIL_EXTRA[selected.file] || {}) : {};

  const labItems = React.useMemo(() => {
    if (extra.sections) {
      return extra.sections.flatMap(sec => sec.items.map(item => ({ ...item, panel: sec.name })));
    }
    if (!selected?.visitId) return [];
    return data.labs
      .filter(l => l.visit_id === selected.visitId)
      .map(lab => ({
        k: lab.test_name,
        v: lab.value,
        u: lab.unit || '',
        ref: displayRef(lab.ref_low, lab.ref_high),
        status: lab.status,
        panel: lab.panel,
        raw: lab,
      }));
  }, [extra.sections, selected?.visitId, data.labs]);

  const abnormalItems = labItems.filter(item => ['high', 'low', 'abnormal'].includes(labDirection(item)));
  const normalItems = labItems.filter(item => !['high', 'low', 'abnormal'].includes(labDirection(item)));

  if (checkupReports.length === 0) {
    return (
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <DashLabel right="可手动补录单项指标">体检 / 化验</DashLabel>
          <Btn primary onClick={onAddLab}>+ 新增化验</Btn>
        </div>
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-soft)' }}>暂无体检报告记录</div>
      </div>
    );
  }

  return (
    <div className="checkup-tab">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <DashLabel right="可手动补录单项指标">体检 / 化验</DashLabel>
        <Btn primary onClick={onAddLab}>+ 新增化验</Btn>
      </div>
      <div className="checkup-selector">
        {checkupReports.map(r => (
          <button
            key={r.id}
            className={`checkup-sel-btn ${r.id === effectiveId ? 'active' : ''}`}
            onClick={() => selectCheckup(r.id)}
          >
            <div className="mono">{r.d}</div>
            <div className="hand" style={{ fontSize: 15, fontWeight: 700 }}>{r.t || r.org}</div>
          </button>
        ))}
      </div>

      {selected && (
        <div>
          <div className="checkup-summary-bar">
            <span className="mono">共 {labItems.length} 项</span>
            {abnormalItems.length > 0 && (
              <span className="mono checkup-summary-bar__abn">异常 {abnormalItems.length} 项</span>
            )}
            <span className="mono" style={{ color: 'var(--ok)' }}>正常 {normalItems.length} 项</span>
            {extra.conclusion && (
              <span className="mono checkup-summary-bar__note">{extra.conclusion.slice(0, 60)}{extra.conclusion.length > 60 ? '…' : ''}</span>
            )}
            {selected.visitId && onEditVisit && <Btn ghost onClick={() => onEditVisit(selected.visitId)}>编辑就诊</Btn>}
            <Btn ghost onClick={() => onOpen && onOpen(selected)}>完整报告 →</Btn>
          </div>

          {abnormalItems.length > 0 && (
            <div className="checkup-section checkup-section--abn sketch">
              <div className="checkup-section-head">
                <div className="sec-label" style={{ color: 'var(--danger)' }}>异常指标</div>
                <div className="mono" style={{ color: 'var(--ink-soft)' }}>{abnormalItems.length} 项 · 点击行可折叠趋势</div>
              </div>
              {abnormalItems.map((item, i) => (
                <CheckupLabRow key={`${item.k}-${i}`} item={item} memberKey={memberKey} autoExpanded={false} onEdit={onEditLab} onDelete={onDeleteLab} />
              ))}
            </div>
          )}

          {normalItems.length > 0 && (
            <div className="checkup-section sketch">
              <button className="checkup-normal-toggle" onClick={() => setShowNormal(v => !v)}>
                <div className="sec-label">正常指标</div>
                <div className="mono">{normalItems.length} 项&nbsp;&nbsp;{showNormal ? '▲ 收起' : '▼ 展开'}</div>
              </button>
              {showNormal && normalItems.map((item, i) => (
                <CheckupLabRow key={`${item.k}-${i}`} item={item} memberKey={memberKey} autoExpanded={false} onEdit={onEditLab} onDelete={onDeleteLab} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const TabReports = ({ reports, kind, onOpen, onAdd, onEdit, onDelete }) => (
  <div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <DashLabel right={`${reports.length} 条`}>全部{kind}记录</DashLabel>
      <Btn primary onClick={onAdd}>+ 新增就诊</Btn>
    </div>
    {reports.length === 0 ? (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-soft)' }}>暂无 {kind} 记录</div>
    ) : (
      <div className="row-list">
        {reports.map(r => (
          <div key={r.id} className="row">
            <span className="mono" style={{ color: 'var(--ink-soft)' }}>{r.d}</span>
            <div>
              <div style={{ fontFamily: 'Caveat, cursive', fontSize: 20, fontWeight: 700 }}>{r.t}</div>
              <span className="mono" style={{ color: 'var(--ink-soft)' }}>{r.org} · {r.file}</span>
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {(reportChipLabels(r)).map((a, j) => (
                <Chip key={j} variant={severityBadgeVariant(r.severity)}>{a}</Chip>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              {onEdit && <Btn ghost onClick={() => onEdit(r)}>编辑</Btn>}
              {onDelete && <Btn ghost onClick={() => onDelete(r)}>删除</Btn>}
              <Btn ghost onClick={() => onOpen && onOpen(r)}>打开 →</Btn>
            </div>
          </div>
        ))}
      </div>
    )}
  </div>
);

const reportChipLabels = (report) => {
  if (report.tag === '就医' && report.chiefComplaint) return [report.chiefComplaint];
  return (report.abn || []).slice(0, 2);
};

const SEVERITY_BADGE_VARIANTS = {
  '严重': 'severity-severe',
  '轻微': 'severity-mild',
  '一般': 'severity-general',
};

const severityBadgeVariant = (severity) => SEVERITY_BADGE_VARIANTS[severity] || '';

/* ── Drug category display map (label → color/desc，无推断逻辑) ── */
const DRUG_CAT_MAP = {
  '免疫治疗': { color: 'accent', desc: '变应原脱敏 · 调节免疫' },
  '抗组胺': { color: 'accent-2', desc: '抑制组胺 · 缓解过敏症状' },
  '白三烯拮抗': { color: 'accent-2', desc: '减轻气道炎症 · 控制哮喘' },
  '糖皮质激素': { color: 'accent-3', desc: '抗炎 · 抑制免疫反应' },
  '支气管扩张': { color: 'accent', desc: '扩张气道 · 改善通气' },
  '心血管': { color: 'danger', desc: '控制血压 · 保护心脏' },
  '降糖药': { color: 'accent-3', desc: '控制血糖' },
  '调脂药': { color: 'accent-2', desc: '降低胆固醇 · 稳定斑块' },
  '抗菌药': { color: 'danger', desc: '抗感染治疗' },
  '止痛退烧': { color: '', desc: '解热镇痛' },
};

const getCatDisplay = (category) => {
  if (!category) return { label: '未分类', color: '', desc: '' };
  const meta = DRUG_CAT_MAP[category];
  return meta ? { label: category, ...meta } : { label: category, color: '', desc: '' };
};

const parseMedName = (name) => {
  const m = /^(.*?)\s*[【\[（(](.*?)[】\]）)]\s*$/.exec(name || '');
  if (m) return { generic: m[1].trim(), brand: m[2].trim() };
  return { generic: name || '', brand: '' };
};

const medDaysText = (med) => {
  if (!med.start_date) return null;
  const start = new Date(med.start_date);
  const end = med.end_date ? new Date(med.end_date) : new Date();
  const days = Math.round((end - start) / 86400000);
  if (days < 0) return null;
  return days < 30 ? `${days} 天` : `约 ${Math.round(days / 30)} 个月`;
};

const MedCard = ({ med, onEdit, onStop, onDelete, historyCount = 0, expanded = false, onToggleHistory }) => {
  const cat = getCatDisplay(med.category);
  const { generic, brand } = parseMedName(med.name);
  const daysText = medDaysText(med);
  const usage = [med.dose, med.route, med.freq].filter(Boolean).join('  ·  ');
  return (
    <div className="sketch" style={{ padding: 14, background: med.ongoing ? 'var(--paper)' : 'var(--paper-2)', opacity: med.ongoing ? 1 : 0.78 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: 'Caveat, cursive', fontSize: 22, fontWeight: 700, lineHeight: 1.2, wordBreak: 'break-all' }}>{generic}</div>
          {brand && <div className="mono" style={{ color: 'var(--ink-ghost)', fontSize: 10, marginTop: 1 }}>{brand}</div>}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-end', flexShrink: 0 }}>
          <Chip variant={cat.color}>{cat.label}</Chip>
          <Chip variant={med.ongoing ? 'ok' : ''}>{med.ongoing ? '在用' : '已停'}</Chip>
        </div>
      </div>
      <div className="mono" style={{ background: 'var(--paper-2)', padding: '5px 8px', borderRadius: 5, marginBottom: 8, fontSize: 11 }}>
        {usage || '用法未录'}
      </div>
      <div className="mono" style={{ color: 'var(--ink-soft)', fontSize: 10 }}>
        {med.start_date || '?'} → {med.ongoing ? '至今' : (med.end_date || '?')}
        {daysText && <span style={{ marginLeft: 8, color: 'var(--ink)', fontWeight: 600 }}>共 {daysText}</span>}
      </div>
      {med.notes && (
        <div className="mono" style={{ color: 'var(--ink-soft)', fontSize: 10, marginTop: 6, borderTop: '1px dashed var(--rule)', paddingTop: 5 }}>
          {med.notes}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, justifyContent: 'space-between', alignItems: 'center', marginTop: 10 }}>
        {historyCount > 0 ? (
          <button onClick={onToggleHistory} style={{
            background: 'none', border: 'none', cursor: 'pointer', padding: 0,
            fontFamily: 'JetBrains Mono, monospace', fontSize: 10,
            color: 'var(--ink-soft)', textDecoration: 'underline dotted',
          }}>
            {expanded ? '▲ 收起历史' : `▼ 另有 ${historyCount} 次处方记录`}
          </button>
        ) : <span />}
        <div style={{ display: 'flex', gap: 6 }}>
          <Btn ghost onClick={() => onEdit(med)}>编辑</Btn>
          {med.ongoing && <Btn ghost onClick={() => onStop(med)}>停用</Btn>}
          <Btn ghost onClick={() => onDelete(med)}>删除</Btn>
        </div>
      </div>
    </div>
  );
};

const MedHistoryRow = ({ med, onEdit, onDelete }) => {
  const usage = [med.dose, med.route, med.freq].filter(Boolean).join(' · ');
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '5px 10px', marginTop: 3,
      background: 'var(--paper-2)', borderRadius: 6,
      borderLeft: '3px solid var(--rule)',
    }}>
      <span className="mono" style={{ color: 'var(--ink-ghost)', fontSize: 10, flexShrink: 0 }}>
        {med.start_date || '?'} → {med.ongoing ? '至今' : (med.end_date || '?')}
      </span>
      <span className="mono" style={{ color: 'var(--ink-soft)', fontSize: 10, flex: 1 }}>{usage || '用法未录'}</span>
      <Chip variant={med.ongoing ? 'ok' : ''}>{med.ongoing ? '在用' : '已停'}</Chip>
      <Btn ghost onClick={() => onEdit(med)}>编辑</Btn>
      <Btn ghost onClick={() => onDelete(med)}>删除</Btn>
    </div>
  );
};

const TabMeds = ({ meds, visits = [], onAdd, onEdit, onStop, onDelete }) => {
  const [filter, setFilter] = React.useState('在用');
  const [selectedVisit, setSelectedVisit] = React.useState(null);
  const [expandedNames, setExpandedNames] = React.useState(new Set());
  const active = meds.filter(m => m.ongoing);
  const stopped = meds.filter(m => !m.ongoing);
  const byStatus = filter === '在用' ? active : filter === '已停' ? stopped : meds;
  const displayed = selectedVisit != null ? byStatus.filter(m => m.visit_id === selectedVisit) : byStatus;

  /* 有处方记录的就诊，按日期倒序作为筛选选项 */
  const visitIdsWithMeds = new Set(meds.map(m => m.visit_id).filter(v => v != null));
  const visitOptions = visits.filter(v => visitIdsWithMeds.has(v.id))
    .sort((a, b) => b.date.localeCompare(a.date));

  /* 按类别分组，再在类别内按药名去重 */
  const grouped = {};
  displayed.forEach(m => {
    const cat = getCatDisplay(m.category);
    if (!grouped[cat.label]) grouped[cat.label] = { cat, byName: {} };
    const nameKey = parseMedName(m.name).generic;
    if (!grouped[cat.label].byName[nameKey]) grouped[cat.label].byName[nameKey] = [];
    grouped[cat.label].byName[nameKey].push(m);
  });
  /* 每个药名组内：在用优先，再按开始日期倒序 */
  Object.values(grouped).forEach(({ byName }) => {
    Object.values(byName).forEach(arr => arr.sort((a, b) => {
      if (a.ongoing !== b.ongoing) return b.ongoing ? 1 : -1;
      return (b.start_date || '').localeCompare(a.start_date || '');
    }));
  });
  const groups = Object.values(grouped);

  /* 摘要 chip 按不重复药名计数 */
  const catSummary = {};
  const seenNames = new Set();
  meds.forEach(m => {
    const nameKey = parseMedName(m.name).generic;
    if (seenNames.has(nameKey)) return;
    seenNames.add(nameKey);
    const { label, color } = getCatDisplay(m.category);
    if (!catSummary[label]) catSummary[label] = { color, count: 0 };
    catSummary[label].count++;
  });

  const toggleExpand = (nameKey) => setExpandedNames(prev => {
    const next = new Set(prev);
    next.has(nameKey) ? next.delete(nameKey) : next.add(nameKey);
    return next;
  });

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ fontFamily: 'Caveat, cursive', fontSize: 24, fontWeight: 700 }}>用药清单</div>
          <div style={{ display: 'flex', gap: 4 }}>
            {[['全部', meds.length], ['在用', active.length], ['已停', stopped.length]].map(([label, count]) => (
              <button key={label} onClick={() => setFilter(label)} style={{
                padding: '3px 9px', border: '1.5px solid var(--line)', borderRadius: 6,
                background: filter === label ? 'var(--ink)' : 'var(--paper)',
                color: filter === label ? 'var(--paper)' : 'var(--ink)',
                cursor: 'pointer', fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
              }}>{label} {count}</button>
            ))}
          </div>
        </div>
        <Btn primary onClick={onAdd}>+ 新增用药</Btn>
      </div>

      {visitOptions.length > 0 && (
        <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="mono" style={{ fontSize: 11, color: 'var(--ink-soft)' }}>按就诊筛选</span>
          <select
            value={selectedVisit || ''}
            onChange={(e) => setSelectedVisit(e.target.value ? Number(e.target.value) : null)}
            className="mono"
            style={{
              padding: '6px 12px',
              borderRadius: 8,
              border: '2px solid var(--line)',
              background: 'var(--paper)',
              color: 'var(--ink)',
              fontSize: 13,
              cursor: 'pointer',
              outline: 'none',
              maxWidth: 360,
              fontFamily: 'inherit'
            }}
          >
            <option value="">全部就诊记录</option>
            {visitOptions.map(v => (
              <option key={v.id} value={v.id}>
                {v.date} {v.hospital ? ` · ${v.hospital}` : ''}
              </option>
            ))}
          </select>
          {selectedVisit && (
            <button
              onClick={() => setSelectedVisit(null)}
              className="mono"
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--ink-soft)',
                textDecoration: 'underline',
                cursor: 'pointer',
                fontSize: 10
              }}
            >
              清除筛选
            </button>
          )}
        </div>
      )}


      {meds.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 18 }}>
          {Object.entries(catSummary).map(([label, { color, count }]) => (
            <Chip key={label} variant={color}>{label} · {count} 种</Chip>
          ))}
        </div>
      )}

      {displayed.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-soft)' }}>
          {filter === '在用' ? '暂无在用药物' : filter === '已停' ? '暂无停用历史' : '无用药记录'}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {groups.map(({ cat, byName }) => {
            const nameGroups = Object.entries(byName);
            return (
              <div key={cat.label}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, paddingBottom: 4, borderBottom: '2px solid var(--line)' }}>
                  <div style={{ width: 4, height: 16, background: 'var(--ink)', borderRadius: 2, flexShrink: 0 }} />
                  <span style={{ fontFamily: 'Caveat, cursive', fontSize: 20, fontWeight: 700 }}>{cat.label}</span>
                  <span className="mono" style={{ color: 'var(--ink-soft)', fontSize: 10 }}>{cat.desc}</span>
                  <span className="mono" style={{ color: 'var(--ink-soft)', marginLeft: 'auto', fontSize: 11 }}>{nameGroups.length} 种</span>
                </div>
                <div className="grid-2">
                  {nameGroups.map(([nameKey, items]) => (
                    <div key={nameKey}>
                      <MedCard
                        med={items[0]}
                        onEdit={onEdit} onStop={onStop} onDelete={onDelete}
                        historyCount={items.length - 1}
                        expanded={expandedNames.has(nameKey)}
                        onToggleHistory={() => toggleExpand(nameKey)}
                      />
                      {expandedNames.has(nameKey) && items.slice(1).map(m => (
                        <MedHistoryRow key={m.id} med={m} onEdit={onEdit} onDelete={onDelete} />
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

const TabAttachments = ({ reports, onOpen, onAddAttachment, onImport, onEditAttachment, onDeleteAttachment }) => {
  const stopCardAction = (event, action) => {
    event.stopPropagation();
    action();
  };
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <DashLabel right={`${reports.length} 份文件`}>附件库</DashLabel>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {onAddAttachment && <Btn onClick={onAddAttachment}>+ 添加附件</Btn>}
          {onImport && <Btn primary onClick={onImport}>+ 上传报告/附件</Btn>}
        </div>
      </div>
      <div className="mono" style={{ color: 'var(--ink-soft)', fontSize: 11, margin: '-2px 0 10px' }}>
“添加附件”只归档文件并新增附件记录；“上传报告/附件”会进入报告解析和结构化写入流程。移除记录默认保留磁盘文件，只有“删除记录+文件”会尝试删除当前数据目录内的原始归档文件。
      </div>
      <div className="attachment-grid">
        {reports.map(r => (
          <div key={r.id} className="attachment-card" onClick={() => onOpen && onOpen(r)}>
            <Placeholder label={r.file} h={90} tooltip={reportTooltip(r)} />
            <div className="attachment-card__title">{r.t}</div>
            <div className="attachment-card__date mono">{r.d}</div>
            {onDeleteAttachment && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                {onEditAttachment && <Btn ghost onClick={(event) => stopCardAction(event, () => onEditAttachment(r))}>编辑</Btn>}
                <Btn ghost onClick={(event) => stopCardAction(event, () => onDeleteAttachment(r, false))}>移除记录</Btn>
                <Btn ghost onClick={(event) => stopCardAction(event, () => onDeleteAttachment(r, true))}>删除记录+文件</Btn>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

const TabReminders = ({ items, onAdd, onEdit, onDone, onSkip, onDelete }) => (
  <div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <DashLabel right={`${items.length} 条`}>我的提醒</DashLabel>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {onAdd && <Btn primary onClick={onAdd}>+ 新增提醒</Btn>}
      </div>
    </div>
    {items.length === 0 ? (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-soft)' }}>无提醒</div>
    ) : (
      <div className="row-list reminders-row-list">
        {items.map(r => {
          const overdue = daysFromToday(r.date) < 0;
          return (
            <div key={r.id} className={`row reminder-row ${overdue ? 'is-overdue' : ''}`}>
              <span className="mono reminder-row__date">{r.date}</span>
              <div className="reminder-row__body">
                <div className="reminder-row__title">{r.title}</div>
                <div className="reminder-row__tags">
                  <Chip variant={r.kind === '宠物' || r.kind === '驱虫' ? 'accent-3' : r.kind === '就医' ? 'accent' : 'accent-2'}>{r.kind}</Chip>
                  {r.source === 'auto' && <Chip variant="accent-3">自动</Chip>}
                  {overdue && <Chip variant="danger">已过期</Chip>}
                </div>
              </div>
              <div className="reminder-row__actions">
                {onEdit && <Btn ghost onClick={() => onEdit(r)}>编辑</Btn>}
                {onDone && <Btn ghost onClick={() => onDone(r)}>完成</Btn>}
                {onSkip && r.source === 'auto' && overdue && <Btn ghost onClick={() => onSkip(r)}>下次再说</Btn>}
                {onDelete && <Btn ghost onClick={() => onDelete(r)}>删除</Btn>}
              </div>
            </div>
          );
        })}
      </div>
    )}
  </div>
);

const daysBetween = (date, base = todayIso()) => {
  if (!date) return null;
  const a = new Date(`${base}T00:00:00`);
  const b = new Date(`${date}T00:00:00`);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return null;
  return Math.round((b - a) / 86400000);
};

const relativeDueText = (date) => {
  const days = daysBetween(date);
  if (days === null) return '未定';
  if (days < 0) return `逾期 ${Math.abs(days)} 天`;
  if (days === 0) return '今天';
  if (days === 1) return '明天';
  return `${days} 天后`;
};

const petReminderVariant = (date) => {
  const days = daysBetween(date);
  if (days === null) return '';
  if (days < 0) return 'danger';
  if (days <= 7) return 'accent';
  return 'accent-3';
};

const recordKindVariant = (kind) => {
  if (kind === '就医' || kind === '体检') return 'accent';
  if (kind === '用药') return 'accent-2';
  if (kind === '体重') return 'accent-3';
  if (kind === '异常') return 'danger';
  return '';
};

const latestDateOf = (items, key = 'date') => items.reduce((latest, item) => {
  const date = item?.[key];
  return date && (!latest || date > latest) ? date : latest;
}, '');

const TabPetOverview = ({ member, labs, visits, meds, weights, reminders, attachments, onOpen }) => {
  const latestWeight = weights[weights.length - 1];
  const prevWeight = weights.length >= 2 ? weights[weights.length - 2] : null;
  const weightDelta = latestWeight && prevWeight ? latestWeight.weight_kg - prevWeight.weight_kg : null;
  const activeMeds = meds.filter(m => m.ongoing);
  const abnormalLabs = latestByName(labs).filter(l => ['high', 'low', 'abnormal'].includes(l.status));
  const openReminders = reminders
    .filter(r => !r.done)
    .sort((a, b) => (a.date || '').localeCompare(b.date || ''))
    .slice(0, 5);
  const primaryAttachmentByVisit = new Map();
  attachments.map(reportFromAttachment).forEach(a => {
    if (!a.visitId) return;
    const prev = primaryAttachmentByVisit.get(a.visitId);
    const isNewPdf = extOf(a.file) === 'pdf';
    const isOldMd = prev?.file.endsWith('.md');
    const isOldNotPdf = prev && extOf(prev.file) !== 'pdf';
    if (!prev || (isOldMd && !a.file.endsWith('.md')) || (isNewPdf && isOldNotPdf)) {
      primaryAttachmentByVisit.set(a.visitId, a);
    }
  });
  const visitRecords = visits.map(v => {
    const report = reportFromVisit(v, primaryAttachmentByVisit.get(v.id));
    return {
      id: `visit-${v.id}`,
      date: v.date,
      kind: report.tag || '就医',
      title: report.t,
      meta: report.org || '就诊记录',
      report,
    };
  });
  const weightRecords = weights.map(w => ({
    id: `weight-${w.id}`,
    date: w.date,
    kind: '体重',
    title: `${formatWeight(w.weight_kg)} kg`,
    meta: w.notes || '体重记录',
  }));
  const medRecords = meds.map(m => ({
    id: `med-${m.id}`,
    date: m.start_date || m.end_date || '',
    kind: '用药',
    title: m.name || '用药记录',
    meta: [m.dose, m.freq, m.ongoing ? '在用' : '已停'].filter(Boolean).join(' · '),
  }));
  const careRecords = reminders
    .filter(r => r.done)
    .map(r => ({
      id: `care-${r.id}`,
      date: r.date,
      kind: petKindLabel(r.kind, '记事'),
      title: r.title,
      meta: '记事记录',
    }))
    .filter(r => PET_CARE_KIND_SET.has(r.kind));
  const recentRecords = [...visitRecords, ...weightRecords.slice(-3), ...medRecords, ...careRecords]
    .filter(r => r.date)
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 6);
  const latestUpdate = latestDateOf(recentRecords);
  const recentCare = careRecords.filter(r => {
    const days = daysBetween(r.date);
    return days !== null && days <= 0 && days >= -30;
  });
  const careCounts = recentCare.reduce((acc, r) => {
    acc[r.kind] = (acc[r.kind] || 0) + 1;
    return acc;
  }, {});
  const careSummary = Object.entries(careCounts).map(([k, v]) => `${k} ${v} 次`).join(' · ');
  return (
    <div className="pet-overview">
      <div className="pet-overview__lead">
        <div className="sketch pet-status-card">
          <div className="sec-label">当前状态</div>
          <div className="mono" style={{ color: 'var(--ink-soft)' }}>
            分项记录 · 最近更新 {latestUpdate || latestWeight?.date || '暂无'}
          </div>
          <div className="pet-state-list">
            <div>
              <span>检验</span>
              <strong>{abnormalLabs.length ? `${abnormalLabs.length} 项异常` : '未见异常标记'}</strong>
            </div>
            <div>
              <span>用药</span>
              <strong>{activeMeds.length ? `${activeMeds.length} 项在用` : '无进行中用药'}</strong>
            </div>
            <div>
              <span>体重</span>
              <strong>{latestWeight ? `${formatWeight(latestWeight.weight_kg)} kg` : '未记录'}</strong>
              {weightDelta !== null && (
                <small className="mono" style={{ color: weightDelta > 0 ? 'var(--danger)' : 'var(--ok)' }}>
                  较上次 {weightDelta >= 0 ? '+' : ''}{weightDelta.toFixed(2)} kg
                </small>
              )}
            </div>
          </div>
        </div>

        <div className="sketch pet-reminders-card">
          <DashLabel right={`${openReminders.length} 条`}>近期事项</DashLabel>
          {openReminders.length === 0 ? (
            <div className="pet-empty">暂无待办，最近一次健康记录是 {latestUpdate || '暂无'}。</div>
          ) : (
            <div className="pet-task-list">
              {openReminders.map(r => (
                <div key={r.id} className="pet-task">
                  <Chip variant={petReminderVariant(r.date)}>{relativeDueText(r.date)}</Chip>
                  <div>
                    <strong>{r.title}</strong>
                    <span className="mono">{petKindLabel(r.kind)} · {r.date || '未定日期'}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <DashLabel right={`${recentRecords.length} 条`}>最近记录</DashLabel>
      {recentRecords.length === 0 ? (
        <div className="pet-empty sketch">暂无记录</div>
      ) : (
        <div className="pet-timeline">
          {recentRecords.map(r => (
            <div
              key={r.id}
              className={`pet-timeline__item ${r.report ? 'is-clickable' : ''}`}
              onClick={() => r.report && onOpen && onOpen(r.report)}
              title={r.report ? '打开记录详情' : ''}
            >
              <div className="mono pet-timeline__date">{r.date.slice(5, 10)}</div>
              <Chip variant={recordKindVariant(r.kind)}>{r.kind}</Chip>
              <div className="pet-timeline__body">
                <strong>{r.title}</strong>
                <span className="mono">{r.meta || '已记录'}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="pet-overview__bottom">
        <div className="sketch pet-trend-card">
          <DashLabel right={`${weights.length} 条`}>体重趋势</DashLabel>
          <div className="pet-trend-card__value">
            {latestWeight ? `${formatWeight(latestWeight.weight_kg)} kg` : '暂无'}
          </div>
          {weights.length ? (
            <LineChart
              points={weights.slice(-8).map(w => ({ date: w.date, value: w.weight_kg, notes: weightPointNote(member, w) }))}
              w={420}
              h={70}
              unit="kg"
              color="var(--accent)"
            />
          ) : (
            <div className="pet-empty">暂无体重趋势</div>
          )}
        </div>
        <div className="sketch pet-trend-card">
          <DashLabel>最近 30 天</DashLabel>
          <div className="pet-trend-card__value">{careSummary || '无记事'}</div>
          <div className="mono" style={{ color: 'var(--ink-soft)' }}>
            就医 {visitRecords.filter(r => {
              const days = daysBetween(r.date);
              return days !== null && days <= 0 && days >= -30;
            }).length} 次 · 附件 {attachments.length} 份
          </div>
        </div>
        <div className="sketch pet-archive-card">
          <DashLabel>档案</DashLabel>
          <div className="pet-archive-card__org">{member.doctor || '未录入医院'}</div>
          <div className="mono" style={{ color: 'var(--ink-soft)' }}>
            {[member.breed, member.home_date ? `到家 ${member.home_date}` : null].filter(Boolean).join(' · ') || '基础信息未录入'}
          </div>
          <div className="mono" style={{ color: 'var(--ink-soft)' }}>
            最近就诊 · {latestDateOf(visits) || '暂无'}
          </div>
          <div className="mono" style={{ color: 'var(--ink-soft)' }}>
            {member.notes || `已归档 ${attachments.length} 份文件`}
          </div>
        </div>
      </div>
    </div>
  );
};

const TabPetCare = ({ reminders, attachments, onAdd, onEdit, onDelete }) => {
  const [filter, setFilter] = React.useState('全部');
  const careReminders = reminders
    .filter(r => r.done)
    .map(r => ({ ...r, kind: r.kind || '记事' }))
    .filter(r => PET_CARE_KIND_SET.has(r.kind));
  const careAttachments = attachments
    .map(a => ({ id: `att-${a.id}`, date: a.date, title: a.title, kind: a.tag || '附件', done: true }))
    .filter(a => PET_CARE_KIND_SET.has(a.kind));
  const allItems = [...careReminders, ...careAttachments].sort((a, b) => (b.date || '').localeCompare(a.date || ''));
  const kinds = ['全部', ...new Set(allItems.map(x => x.kind))];
  const displayed = filter === '全部' ? allItems : allItems.filter(x => x.kind === filter);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <DashLabel right={`${displayed.length} 条`}>记事</DashLabel>
        {onAdd && <Btn primary onClick={onAdd}>+ 添加记事</Btn>}
      </div>
      {kinds.length > 2 && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>
          {kinds.map(k => (
            <button key={k} onClick={() => setFilter(k)} style={{
              padding: '2px 10px', border: '1.5px solid var(--line)', borderRadius: 6,
              background: filter === k ? 'var(--ink)' : 'var(--paper)',
              color: filter === k ? 'var(--paper)' : 'var(--ink)',
              cursor: 'pointer', fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
            }}>{k}</button>
          ))}
        </div>
      )}
      {displayed.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-soft)' }}>暂无记事记录</div>
      ) : (
        <div className="row-list reminders-row-list">
          {displayed.map(r => (
            <div key={r.id} className="row reminder-row care-row">
              <span className="mono reminder-row__date">{r.date}</span>
              <div className="reminder-row__body">
                <div className="reminder-row__title">{r.title}</div>
                <div className="reminder-row__tags">
                  <Chip variant="accent-3">{r.kind}</Chip>
                </div>
              </div>
              <div className="reminder-row__actions">
                {onEdit && typeof r.id === 'number' && <Btn ghost onClick={() => onEdit(r)}>编辑</Btn>}
                {onDelete && typeof r.id === 'number' && <Btn ghost onClick={() => onDelete(r)}>删除</Btn>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const TabVax = ({ labs, attachments, onAddLab }) => {
  const antibodyLabs = labs.filter(l => l.panel === '疫苗抗体');
  const vaccineFiles = attachments.filter(a => a.tag === '疫苗' || a.title.includes('免疫'));
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <DashLabel right={`${antibodyLabs.length} 项`}>疫苗与抗体</DashLabel>
        <Btn primary onClick={onAddLab}>+ 新增化验</Btn>
      </div>
      <div className="row-list">
        {antibodyLabs.map(l => (
          <div key={l.id} className="row" style={{ gridTemplateColumns: '110px 1fr 180px' }}>
            <span className="mono">{l.date}</span>
            <span style={{ fontFamily: 'Caveat, cursive', fontSize: 20, fontWeight: 700 }}>{l.test_name}</span>
            <Chip variant={l.status === 'normal' ? 'ok' : 'danger'} style={{ justifySelf: 'end' }}>{l.value}</Chip>
          </div>
        ))}
      </div>
      <DashLabel right={`${vaccineFiles.length} 份`}>相关附件</DashLabel>
      <TabAttachments reports={vaccineFiles.map(reportFromAttachment)} />
    </div>
  );
};

const TabPetWeight = ({ member, weights, onAdd, onDelete }) => {
  const [selectedWeightId, setSelectedWeightId] = React.useState(null);
  const chartPoints = weights.map(w => ({ ...w, value: w.weight_kg, notes: weightPointNote(member, w) }));
  const latest = weights[weights.length - 1];
  const prev = weights.length >= 2 ? weights[weights.length - 2] : null;
  const delta = latest && prev ? latest.weight_kg - prev.weight_kg : null;
  const selectedWeight = weights.find(w => String(w.id) === String(selectedWeightId));
  React.useEffect(() => {
    if (selectedWeightId && !weights.some(w => String(w.id) === String(selectedWeightId))) {
      setSelectedWeightId(null);
    }
  }, [weights, selectedWeightId]);
  return (
    <div>
      <div className="pet-weight-toolbar" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <DashLabel right={`${weights.length} 条`}>体重曲线</DashLabel>
        <Btn primary onClick={onAdd}>+ 记录体重</Btn>
      </div>
      <div className="sketch" style={{ padding: 18 }}>
        <div className="pet-weight-summary" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
          <div>
            <div style={{ fontFamily: 'Caveat, cursive', fontSize: 44, fontWeight: 700, lineHeight: 1 }}>{latest ? formatWeight(latest.weight_kg) : '—'} kg</div>
            {delta !== null && <span className="mono" style={{ color: delta > 0 ? 'var(--danger)' : 'var(--ok)' }}>{delta > 0 ? '↑' : '↓'} {Math.abs(delta).toFixed(2)} kg · 较上次</span>}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <Chip variant="accent-2">{member.name}</Chip>
            <Chip>{weights[0]?.date || '—'} 至 {latest?.date || '—'}</Chip>
          </div>
        </div>
        <EChartLine
          points={chartPoints}
          height={240}
          unit="kg"
          yName="体重"
          color="var(--accent)"
          emptyText="暂无体重记录"
          selectedKey={selectedWeightId}
          onPointClick={(point) => setSelectedWeightId(point.id)}
        />
        <div className="pet-weight-axis" style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
          {weights.slice(-12).map(w => <span key={w.id} className="mono" style={{ color: 'var(--ink-soft)' }}>{w.date.slice(2, 7)}</span>)}
        </div>
        {selectedWeight && (
          <div className="mono" style={{ marginTop: 8, color: 'var(--ink-soft)' }}>
            图中选中 · {selectedWeight.date} · {formatWeight(selectedWeight.weight_kg)} kg · {selectedWeight.notes || '体重记录'}
          </div>
        )}
      </div>
      {weights.length > 0 && (
        <div className="row-list" style={{ marginTop: 14 }}>
          {weights.slice().reverse().map(w => (
            <div
              key={w.id}
              className="row pet-weight-row"
              style={String(w.id) === String(selectedWeightId) ? { background: 'color-mix(in oklab, var(--accent) 18%, var(--paper))' } : {}}
            >
              <span className="mono">{w.date}</span>
              <div>{w.notes || '体重记录'}</div>
              <Chip style={{ justifySelf: 'end' }}>{formatWeight(w.weight_kg)} kg</Chip>
              <Btn ghost onClick={() => onDelete(w)}>删除</Btn>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

window.ScreenMember = ScreenMember;
