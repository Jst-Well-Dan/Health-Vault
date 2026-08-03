(function () {
  const originalFetch = window.fetch.bind(window);
  const dataUrl = new URL('data/static-data.json', document.currentScript.src).toString();
  let dataPromise = null;

  const loadData = () => {
    if (!dataPromise) {
      dataPromise = originalFetch(dataUrl).then((res) => {
        if (!res.ok) throw new Error(`static-data.json · ${res.status}`);
        return res.json();
      });
    }
    return dataPromise;
  };

  const jsonResponse = (value, status = 200) => new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });

  const textResponse = (value, status = 200) => new Response(value || '', {
    status,
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });

  const boolOut = (item, key) => ({ ...item, [key]: Boolean(item[key]) });

  const byMember = (items, member) => items.filter((item) => !member || item.member_key === member);

  const latestLabTrend = (labs, member, testName) => {
    const rows = labs
      .filter((item) => item.member_key === member && item.test_name === testName)
      .sort((a, b) => (a.date || '').localeCompare(b.date || '') || (a.id || 0) - (b.id || 0));
    const last = rows[rows.length - 1] || {};
    return {
      test_name: testName,
      unit: last.unit || null,
      ref_low: last.ref_low || null,
      ref_high: last.ref_high || null,
      points: rows
        .map((row) => ({
          date: row.date,
          value: Number.parseFloat(row.value),
          status: row.status,
          visit_id: row.visit_id,
        }))
        .filter((point) => Number.isFinite(point.value)),
    };
  };

  const handleApi = async (url, options) => {
    const method = String(options?.method || 'GET').toUpperCase();
    if (method !== 'GET') {
      return jsonResponse({ detail: '静态预览为只读模式，不支持写入。' }, 405);
    }

    const data = await loadData();
    const path = url.pathname;
    const params = url.searchParams;
    const member = params.get('member');

    if (path === '/api/meta') {
      return jsonResponse({ mock_mode: true, static_preview: true, db_path: 'data/mock/health_mock.db' });
    }

    if (path === '/api/backups/info') {
      return jsonResponse({ database_path: 'data/mock/health_mock.db', backup_dir: 'data/mock/backups', exists: false, backups: [] });
    }

    if (path === '/api/members') {
      const members = params.get('include_archived') === 'true'
        ? data.members
        : data.members.filter((row) => !row.archived_at);
      return jsonResponse(members);
    }

    if (path.startsWith('/api/members/')) {
      const key = decodeURIComponent(path.slice('/api/members/'.length));
      const item = data.members.find((row) => row.key === key);
      return item ? jsonResponse(item) : jsonResponse({ detail: '成员不存在' }, 404);
    }

    if (path === '/api/visits') {
      const limit = Math.max(1, Math.min(Number(params.get('limit') || 20), 100));
      const offset = Math.max(0, Number(params.get('offset') || 0));
      const items = byMember(data.visits, member)
        .slice()
        .sort((a, b) => (b.date || '').localeCompare(a.date || '') || (b.id || 0) - (a.id || 0));
      return jsonResponse({ total: items.length, items: items.slice(offset, offset + limit) });
    }

    if (path.startsWith('/api/visits/')) {
      const id = Number(path.slice('/api/visits/'.length));
      const visit = data.visits.find((row) => row.id === id);
      if (!visit) return jsonResponse({ detail: '就诊记录不存在' }, 404);
      return jsonResponse({
        visit,
        labs: data.labs.filter((row) => row.visit_id === id),
        meds: data.meds.filter((row) => row.visit_id === id).map((row) => boolOut(row, 'ongoing')),
        attachments: data.attachments.filter((row) => row.visit_id === id),
      });
    }

    if (path === '/api/labs/trend') {
      return jsonResponse(latestLabTrend(data.labs, member, params.get('test_name') || ''));
    }

    if (path === '/api/labs') {
      const panel = params.get('panel');
      const visitId = params.has('visit_id') ? Number(params.get('visit_id')) : null;
      const items = byMember(data.labs, member)
        .filter((row) => !panel || row.panel === panel)
        .filter((row) => visitId === null || row.visit_id === visitId)
        .slice()
        .sort((a, b) => (b.date || '').localeCompare(a.date || '') || (b.id || 0) - (a.id || 0));
      return jsonResponse(items);
    }

    if (path === '/api/meds') {
      const items = byMember(data.meds, member)
        .map((row) => boolOut(row, 'ongoing'))
        .sort((a, b) => Number(b.ongoing) - Number(a.ongoing) || (b.start_date || '').localeCompare(a.start_date || '') || (b.id || 0) - (a.id || 0));
      return jsonResponse(items);
    }

    if (path === '/api/weight') {
      const items = byMember(data.weights, member)
        .slice()
        .sort((a, b) => (a.date || '').localeCompare(b.date || '') || (a.id || 0) - (b.id || 0));
      return jsonResponse(items);
    }

    if (path === '/api/reminders') {
      const includeDone = params.get('include_done') === 'true';
      const items = byMember(data.reminders, member)
        .filter((row) => includeDone || !row.done)
        .map((row) => boolOut(row, 'done'))
        .sort((a, b) => (a.date || '').localeCompare(b.date || '') || (a.id || 0) - (b.id || 0));
      return jsonResponse(items);
    }

    if (path === '/api/attachments') {
      const items = byMember(data.attachments, member)
        .slice()
        .sort((a, b) => (b.date || '').localeCompare(a.date || '') || (b.id || 0) - (a.id || 0));
      return jsonResponse(items);
    }

    if (path === '/api/attachments/recent') {
      const limit = Math.max(1, Math.min(Number(params.get('limit') || 8), 50));
      return jsonResponse(data.attachments.slice().sort((a, b) => (b.id || 0) - (a.id || 0)).slice(0, limit));
    }

    const textMatch = path.match(/^\/api\/attachments\/(\d+)\/text$/);
    if (textMatch) {
      const id = textMatch[1];
      return textResponse(data.attachment_text[id] || '', data.attachment_text[id] ? 200 : 404);
    }

    return jsonResponse({ detail: '静态预览未包含该接口。' }, 404);
  };

  window.fetch = (input, options) => {
    const rawUrl = typeof input === 'string' ? input : input?.url;
    if (!rawUrl) return originalFetch(input, options);
    const url = new URL(rawUrl, window.location.href);
    if (url.pathname.startsWith('/api/')) {
      return handleApi(url, options);
    }
    return originalFetch(input, options);
  };
}());
