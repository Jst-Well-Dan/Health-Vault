function SettingsPanel({ onClose, onSelect, agentAvailable = false }) {
  const items = [
    {
      key: 'backup',
      label: '数据备份',
      description: '创建、校验和恢复本地健康档案数据库备份。',
    },
    {
      key: 'remote',
      label: '远程访问 (Tailscale)',
      description: '检测 Tailscale、配置手机访问、修改密码、设置开机自启。',
    },
    {
      key: 'ai',
      label: 'AI 配置',
      description: '选择健康助手使用的模型，并管理登录方式。',
    },
  ];

  return (
    <div className="modal-backdrop">
      <div className="daily-modal sketch shadow app-settings-panel" style={{ maxWidth: 620 }}>
        <div className="app-settings-panel__head">
          <div>
            <div className="sec-label">应用管理</div>
            <div className="app-settings-panel__title">设置</div>
          </div>
          <Btn ghost onClick={onClose}>关闭</Btn>
        </div>

        <div className="app-settings-panel__list">
          {items.map(item => {
            const unavailable = item.key !== 'backup' && item.key !== 'remote' && !agentAvailable;
            return (
              <button
                key={item.key}
                className="app-settings-panel__item sketch"
                disabled={unavailable}
                onClick={() => onSelect(item.key)}
              >
                <span>
                  <strong>{item.label}</strong>
                  <small>{unavailable ? '健康助手不可用' : item.description}</small>
                </span>
                <b aria-hidden="true">→</b>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

window.SettingsPanel = SettingsPanel;
