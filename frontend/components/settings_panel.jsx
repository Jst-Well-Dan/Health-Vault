function SettingsPanel({ onClose, onSelect }) {
  const items = [
    {
      key: 'backup',
      label: '数据备份',
      description: '创建、校验和恢复本地健康档案数据库备份。',
    },
    {
      key: 'remote',
      label: '本机与自启',
      description: '切本机/Tailscale 监听地址、设置开机自启（只放 100.x）。',
    },
    {
      key: 'mineru',
      label: 'MinerU 报告转换',
      description: '查看转换模式、保存或删除 Token；不会显示已保存的 Token 内容。',
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
            return (
              <button
                key={item.key}
                className="app-settings-panel__item sketch"
                onClick={() => onSelect(item.key)}
              >
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
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
