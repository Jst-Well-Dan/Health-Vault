# 家庭健康档案桌面版：AI Agent 使用说明

本仓库是一个已经可用的 **Electron 单用户桌面应用**。本文件用于指导 AI agent 协助用户安装、运行、整理健康档案和保护本地数据；除非用户明确提出开发需求，不要默认进入开发模式。

## 开始前

当用户要求使用本项目时，依次阅读：

1. `README.md`
2. 本文件
3. `.codex/skills/` 中与任务相关的 `SKILL.md`

然后先识别用户的目标。若用户仅说“帮我用这个项目”，先询问其想运行应用、整理/导入报告、维护数据，还是处理桌面版故障。

## 项目定位与架构

应用用于在本机集中管理家人和宠物的：

- 就诊记录、体检报告、检验指标和附件
- 用药、提醒及体重记录
- 通过内置健康助手查询或维护档案

桌面版由 Electron 主进程启动 Python/FastAPI sidecar；sidecar 仅监听 `127.0.0.1` 的动态端口，仅供 Electron 窗口和内置健康助手使用，不是面向局域网或 Tailscale 的 Web 服务。

- 开发运行时，数据默认使用项目根目录下的 `data/`。
- 已安装的桌面版使用 Electron 的 `app.getPath("userData")` 作为数据根目录：数据库为 `<userData>/data/health.db`，报告、备份、导入文件和日志也在该目录的 `data/` 下。
- 不要假设用户数据位于安装目录，也不要在升级、重装、构建或排障时删除 Electron `userData` 目录。
- 健康助手的凭据和设置存于 `<userData>/agent-credentials.bin`、`<userData>/agent-settings.json`；不得读取、输出、提交或覆盖其中的敏感内容。
- 启动时，健康助手只读同步 `~/.pi/agent/auth.json`、`settings.json` 与 `models-store.json`：导入 Pi 凭据、可用模型缓存和默认 provider/model，但绝不写回、删除或上传 Pi 的配置；用户在桌面版“模型设置”保存选择后，桌面版优先使用该显式选择。

## 任务分流

优先按以下类别理解任务：

1. **桌面应用运行**：安装依赖、开发运行、打开/退出应用、排查 sidecar 启动。
2. **档案整理**：添加或整理家庭成员、宠物、报告和附件。
3. **报告转换**：将 PDF、图片、Word、网页转换为 Markdown。
4. **数据库写入**：校验导入 JSON、备份、dry-run、写入和验证 SQLite 数据。
5. **桌面版维护**：打包、安装包验证、数据迁移或恢复。

项目技能仍是资料转换和数据库导入的首选流程：

- `mineru`：转换 PDF、图片、Word、网页等原始报告为 Markdown。
- `health-db-writer`：生成/校验导入 JSON，执行备份、dry-run 和 SQLite 写入。
- `health-app`、`health-deploy` 中的旧 Web 服务和 Tailscale 脚本不适用于默认 Electron 桌面版；不要把它们的 `0.0.0.0:8000`、浏览器访问或开机启动服务流程用于桌面版，除非用户明确要求维护旧 Web 部署。

推荐顺序：先确保桌面应用可用；有原始报告先转换；要入库则严格按 `health-db-writer` 写入；最后在桌面应用中核验结果。

## 桌面版运行与维护

### 日常使用

已安装版本应由用户从开始菜单、桌面快捷方式或安装目录启动“家庭健康档案”。关闭窗口会退出应用（macOS 的窗口生命周期以 Electron 实际行为为准），并关闭其 Python sidecar。

不要要求用户另开浏览器访问 `127.0.0.1:8000`；端口由应用启动时自动分配，可能每次不同。

### 开发运行

开发机需要 Node.js 22.19+、Python 和后端依赖。按 `README.md` 执行：

```powershell
npm install
npm start
```

`npm start` 会先编译 Electron TypeScript，然后启动 Electron；主进程会拉起 `backend/run_backend.py`。若 Python 或后端依赖缺失，说明错误并按 `backend/requirements.txt` 安装依赖；不要为了修复启动问题而重置用户数据库。

常用验证命令：

```powershell
npm run check
npm test
npm run smoke
```

### 构建安装包

仅在用户明确要求打包或维护桌面应用时执行。Windows 构建依赖单独的构建 Python 环境：

```powershell
python -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r backend\requirements-build.txt
npm run build
```

`npm run build` 会编译 Electron、用 PyInstaller 打包 Python sidecar，并由 `electron-builder` 生成安装包。构建产物在 `dist/`；不要提交构建产物、依赖目录或真实健康数据。

### 远程和手机访问

当前桌面版的后端固定监听 loopback，**不支持手机、局域网或 Tailscale 直接访问**。用户提出此需求时，应说明该限制；不要建议暴露动态端口或将监听地址改成 `0.0.0.0`，除非用户明确要求设计、开发并评审一套独立的安全远程访问方案。

## 真实健康数据安全

`health.db`、报告附件、导入 JSON、备份、日志和模型凭据均为用户私密数据。始终保守处理。

- 不直接编辑 SQLite 数据库，除非用户明确要求；优先使用项目 API 或 `health-db-writer` 的项目脚本。
- 不删除、重建、重置、批量覆盖或迁移真实数据库，除非用户明确确认范围和影响。
- 写入体检、就诊、检验、用药、提醒、成员、体重或附件前，优先执行 dry-run；对真实库写入前必须创建时间戳备份。
- 不确定报告内容、成员身份、日期、单位或异常项时，先暂停并说明缺失信息，不要猜测写入。
- 原始报告先按 `health-db-writer` 规则归档到对应成员目录；不要只保存附件而遗漏结构化数据，也不要只写数据而丢失来源文件。
- 写入后报告 `visit_id`（如有）、影响行数、实际数据库路径和备份路径。
- 内置健康助手的写操作应展示字段前后对比并获得用户确认；用户输入 `/undo` 时，只撤销最近一项可撤销的 agent 改动，并先说明目标记录。

数据库 payload、字段规则、附件路径、验证方式，以以下文件为准（CLI 导入路径已归档，应用内导入以 Electron 桌面应用为准）：

- `archive/cli-import-path/health-db-writer-skill/SKILL.md`
- `archive/cli-import-path/health-db-writer-skill/references/database-write.md`

## 目录速览

- `electron/`：Electron 主进程、preload bridge、内置健康助手。
- `backend/`：FastAPI sidecar、SQLite 初始化、API 路由和导入脚本。
- `frontend/`：Electron 窗口内加载的前端页面和样式。
- `data/`：开发模式下的数据库、报告、导入文件、备份和公开静态资源；安装版对应内容位于 Electron `userData` 目录。
- `tests/`：后端与 Electron smoke tests。
- `dist-electron/`：TypeScript 编译产物（自动生成）。
- `dist/`、`build/`：打包过程生成的产物。
- `.codex/skills/`：供 AI agent 使用的项目技能。

## 沟通规则

- 保持“协助用户使用桌面应用”的语境；需求未明确时先澄清，不默认改代码。
- 先简要说明理解到的目标和下一步动作；涉及报告转换或数据库写入时，说明将使用的 skill。
- 涉及真实数据写入时，先展示计划或 dry-run 结果，获得用户确认后再写入。
- 排障时先收集错误信息、应用版本、运行方式（开发版/已安装版）和数据位置；不要先做破坏性操作。
- 若用户明确提出功能开发、打包或架构修改，再切换到开发语境，并在改动前评估对数据迁移、端口暴露、凭据和打包流程的影响。
