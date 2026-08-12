# Changelog

All notable changes are documented here.

## Unreleased

- 报告上传改用 MinerU OpenAPI CLI 转换：原始 PDF/图片先在本机转成 Markdown 再交给健康助手解析；Token 存入系统凭据库（Windows 凭据管理器 / macOS Keychain），支持 `flash-extract`（默认，10 MB / 20 页，无需 Token）与 `extract`（需 Token）两种模式，可设置 `HEALTH_MINERU_OPEN_API_CLI` / `HEALTH_MINERU_MODE` 覆盖。
- 成员头像新增「从预设库选择」：可从 `frontend/assets/avatars/` 预设头像库挑选图片并复制到成员头像存储（`GET /api/avatars/presets`、`GET /api/avatars/presets/{name}`、`POST /api/members/{key}/avatar/preset`），与自定义上传并存；预设目录可用 `HEALTH_AVATARS_DIR` 覆盖（默认随 `HEALTH_FRONTEND_DIR` 解析）。
- Initial public Web-first release preparation.
- Windows and macOS setup, Tailscale-only remote binding, and login-start scripts.
- Privacy disclosure for optional third-party AI services.
