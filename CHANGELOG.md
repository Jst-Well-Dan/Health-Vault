# Changelog

All notable changes are documented here.

## Unreleased

- 远程访问设置不再需要手动重启：保存监听地址后可在网页端一键自重启（自动拉起新进程重新绑定并接管端口，Windows 下保留同一终端、Ctrl+C 仍可停止），页面常驻提示条引导并自动跳转到新地址。
- 启动时自动校验 Tailscale 地址：IP 变化自动更新配置并继续监听；Tailscale 未连接时暂以本机模式启动并提示，连接后可一键重启恢复手机访问。
- 报告上传改用 MinerU OpenAPI CLI 转换：原始 PDF/图片先在本机转成 Markdown 再交给健康助手解析；Token 存入系统凭据库（Windows 凭据管理器 / macOS Keychain），支持 `flash-extract`（默认，10 MB / 20 页，无需 Token）与 `extract`（需 Token）两种模式，可设置 `HEALTH_MINERU_OPEN_API_CLI` / `HEALTH_MINERU_MODE` 覆盖。
- 成员头像新增「从预设库选择」：可从 `frontend/assets/avatars/` 预设头像库挑选图片并复制到成员头像存储（`GET /api/avatars/presets`、`GET /api/avatars/presets/{name}`、`POST /api/members/{key}/avatar/preset`），与自定义上传并存；预设目录可用 `HEALTH_AVATARS_DIR` 覆盖（默认随 `HEALTH_FRONTEND_DIR` 解析）。
- Initial public Web-first release preparation.
- Windows and macOS setup, Tailscale-only remote binding, and login-start scripts.
- Privacy disclosure for optional third-party AI services.
