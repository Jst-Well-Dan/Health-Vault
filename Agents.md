# 家庭健康档案 Web 版：AI Agent 使用说明

本仓库是一个本地优先的 **纯 Web 单家庭应用**。Python/FastAPI 提供唯一的浏览器入口；一个独立 Node Agent runtime 只监听 `127.0.0.1`，由 FastAPI 在完成鉴权后代理。不要恢复 Electron、IPC bridge、桌面安装包或动态端口外壳。

## 开始前

先阅读：

1. `README.md`
2. 本文件
3. 与任务相关的项目文档、脚本和测试（例如部署维护任务阅读 `docs/SETUP.md`）

仓库不再内置 `.codex/skills/`；不要假定任何外部技能或旧的 Electron 工作流仍然存在。

未明确需求时，先询问用户是要运行应用、整理/导入报告、维护数据，还是排查手机访问问题；不要默认改代码。

## 架构与数据

- `backend/`：FastAPI、SQLite、鉴权和 Agent runtime 反向代理。
- `agent-runtime/`：Node/TypeScript 健康助手；由 FastAPI 启动，始终只绑定 loopback。
- `frontend/`：同一份浏览器前端，电脑和手机都使用它；不得依赖 `window.health*` 或 Electron API。
- `data/`：开发版私有数据根目录。包括 `health.db`、报告、附件、导入内容、备份、日志和 Agent 密钥/凭据；不得提交、读取或输出敏感内容。

已运行服务的数据库路径可能由 `HEALTH_DB_PATH` / `HEALTH_VAULT_HOME` 决定。不要删除、重建、迁移或批量覆盖真实数据库，除非用户明确确认范围和影响。

## 登录与网络安全

- `HEALTH_APP_PASSWORD` 是必需的家庭共享密码。所有静态页面、`/api/*` 和 `/api/agent-runtime/*` 都必须保持受签名 HttpOnly session 保护。
- 登录失败必须维持速率限制；不要把密码、会话密钥、`agent-key.bin`、`agent-credentials.json`、`agent-runtime-secret.bin` 或任何健康数据写入日志、测试输出、git 或外部服务。
- 浏览器不应直连 Agent runtime；仅 FastAPI 可通过运行时私密请求头访问它。
- 默认监听 `127.0.0.1`。仅当用户明确配置受信任的 Tailscale 手机访问时，才以 `HEALTH_HOST=0.0.0.0` 启动。绝不建议端口映射或公共互联网暴露。

## 运行、验证与部署

开发运行需要 Node.js 22.19+、Python 和后端依赖：

```powershell
npm install
python -m pip install -r backend\requirements.txt
$env:HEALTH_APP_PASSWORD = "设置家庭密码"
npm start
```

常用验证：

```powershell
npm run check
npm test
npm run smoke
```

`npm start` 会先编译 `agent-runtime/` 到 `dist-server/`，再启动 Python 服务；FastAPI 会拉起 loopback Agent runtime。不要跳过编译后直接把 FastAPI 当成完整服务运行。

开机自启脚本必须使用这一入口，并要求用户级环境变量已包含 `HEALTH_APP_PASSWORD`。构建 `dist/`、Electron 安装包和 PyInstaller sidecar 均不再是本项目流程。

## 健康数据写入

涉及成员、报告、就诊、指标、用药、提醒、体重或附件写入时：

1. 有原始报告先按 `mineru` 转换；
2. 使用应用的导入流程，或经审查的专用脚本生成并校验数据；
3. 对真实库写入前先 dry-run 且创建时间戳备份；
4. 不确定成员、日期、单位或异常项时暂停询问，不要猜测；
5. 写入后报告 `visit_id`（如有）、影响行数、实际数据库路径与备份路径。

浏览器端只能创建、查看和校验备份；**不得**增加 Web 备份恢复入口。恢复只能由服务器本机、停止服务后运行 `backend/scripts/restore_database.py <filename> --confirm`。

健康助手的写入必须先展示字段前后对比并等用户确认。`/undo` 只能撤销最近一项可撤销的 Agent 改动，并先说明目标记录。
