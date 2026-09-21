# 安装与维护指南

本文面向负责安装和维护家庭健康档案的人。当前正式支持 **Windows 10/11** 和 **macOS**；不承诺 Linux、NAS、Docker、公共云服务器或公网部署。

> 健康资料很敏感。请仅在自己控制的电脑和受信任的 Tailscale 网络中运行本应用；不要做端口映射或把服务公开到互联网。

## 1. 安装前确认

需要：

- Node.js **22.19+**（含 npm；只用来跑 `npm start` 等脚本）；
- Python **3.10+**；
- Git；
- **pi CLI**：健康助手（应用内只读问答）与终端导入报告都需要。`npm install -g @earendil-works/pi-coding-agent` 后执行一次 `pi login`；应用不保存任何 API Key；
- **MinerU OpenAPI CLI**：导入报告时需要。原始 PDF 或图片先发给 MinerU 转换为 Markdown，助手再结合扫描件原图与 Markdown 整理字段；
- 可选：Tailscale，用于手机访问。

安装 MinerU OpenAPI CLI 并确认命令可用：

```powershell
# Windows（PowerShell）
irm https://cdn-mineru.openxlab.org.cn/open-api-cli/install.ps1 | iex
mineru-open-api version
```

```bash
# macOS
curl -fsSL https://cdn-mineru.openxlab.org.cn/open-api-cli/install.sh | sh
mineru-open-api version
```

默认使用不需要 Token 的 `flash-extract`，单份限制为 **10 MB / 20 页**。若报告超过限制，或希望使用表格/公式识别，请在 **设置 → MinerU 报告转换** 选择“精确解析”，并输入 MinerU Token；任何已登录的浏览器（含手机端）都可以保存、修改或删除该 Token。Token 仅保存到当前 Windows Credential Manager 或 macOS Keychain；不会写入健康档案、`settings.json`、日志或命令行，保存后也不会在页面中再次显示。也可选择在本机终端运行 `mineru-open-api auth` 配置 Token。应用不会回退到直接 PDF/图片解析：若 MinerU 不可用或转换失败，报告不会送往健康助手模型。若 CLI 不在 `PATH`，可设置 `HEALTH_MINERU_OPEN_API_CLI` 为其可执行文件的绝对路径。

应用数据默认位于项目目录的 `data/`。若设置 `HEALTH_VAULT_HOME`，数据则位于该目录的 `data/` 下。**代码目录和数据目录都应放在受本机账户保护的磁盘中。**

健康档案本身默认只存本机。健康助手和 AI 报告解析是例外：原始报告会先发送至你配置的 MinerU 服务以转换为 Markdown；随后，健康助手会将你输入的消息、该 Markdown、扫描件原图与必要的成员信息发送至本机 `pi` 登录的模型服务。使用前请确认这两类服务的隐私、保留、地区合规与收费政策。

## 2. 首次安装

克隆公开仓库后进入项目目录。

### Windows（PowerShell）

```powershell
git clone <公开仓库地址> Health-Vault
cd Health-Vault
npm ci
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
npm start
```

`npm start` 会自动优先使用项目里的 `.venv`（Windows：`.venv\Scripts\python.exe`，macOS：`.venv/bin/python`），所以**不需要先设置 `HEALTH_PYTHON`**。只有把虚拟环境建在别处或名字不同时，才需要 `$env:HEALTH_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe)`。

如果 `python` 不可用，可改用 Windows Python Launcher：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
npm start
```

### macOS（Terminal）

```bash
git clone <公开仓库地址> Health-Vault
cd Health-Vault
npm ci
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
export HEALTH_PYTHON="$PWD/.venv/bin/python"
npm start
```

首次启动会创建空数据库和 Agent 本地凭据目录。随后在本机浏览器打开 <http://127.0.0.1:8000/>：**不需要密码、不需要任何环境变量**，打开即用。

> ⚠️ 本版本**没有登录鉴权**，因此只允许监听 `127.0.0.1`；绑定到其他地址会拒绝启动。同机上运行的其他程序可以读写这份健康档案，请自行保证这台电脑的账户安全。

## 3. 日常启动与停止

启动前只需保证使用与首次安装相同的虚拟环境（`npm start` 会自动选中项目 `.venv`，一般不需要任何环境变量）：

```powershell
# Windows
npm start
```

```bash
# macOS
npm start
```

在终端按 `Ctrl+C` 可停止服务。停止服务后才可执行数据库恢复或升级操作。不需要任何环境变量；`HEALTH_PYTHON`、`HEALTH_PORT` 都是可选的。

如端口 8000 已被占用，可设置 `HEALTH_PORT` 后再启动，例如 Windows：

```powershell
$env:HEALTH_PORT = "8100"
npm start
```

## 4. 导入报告（终端 pi + skill）

应用不提供上传入口；报告导入由本机 `pi` 按项目 skill 完成，全程需要你确认：

1. 把体检 PDF 或扫描件图片放进仓库根目录的 `incoming/`（该目录已在 `.gitignore` 中，不会被提交）；
2. 在项目目录运行 `pi`（会自动加载 `.pi/skills/`），说一句“处理 incoming 里的报告”；
3. 助手会：读原图/MinerU 转换 → 归档到 `data/reports/<成员>/{pdf,md,images,mineru}/` → 生成 payload JSON 到 `data/imports/<成员>/` → 跑 `--dry-run` 并把字段摘要给你看；
4. 你确认后它才执行 `python backend/scripts/import_visit_json.py --file <payload> --write`，自动备份并回报 `visit_id`、影响行数与备份路径；
5. 处理完用 `python backend/scripts/check_incoming.py --delete-archived` 清掉 `incoming/` 里已归档的原件（按 md5 比对，未归档的不删）。

不想开交互会话时，可一次性执行：

```powershell
pi --skill .pi/skills/health-report-import -p "处理 incoming 里的报告，先 dry-run 给我看"
```

同一天已有就诊记录时脚本会拒绝写入，确认不是重复后加 `--allow-duplicate`。

## 5. 手机访问（Tailscale）【已停用】

> 当前版本仅支持本机 `127.0.0.1` 访问：设置页的远程访问入口已隐藏，`/settings/host` 开远程会直接拒绝。Tailscale 检测代码保留在 `backend/services/system_settings.py`，将来如需恢复，按 git 历史中的本节配置；**但恢复前必须先重新引入登录鉴权**，因为现在绑定非本机地址会被直接拒绝。

以下为历史步骤（已停用，保留备查）：

1. 先确认电脑本机访问正常。
2. 在电脑和手机安装 Tailscale，并登录同一个受信任的 tailnet。
3. 在应用的 **设置 → 远程访问 (Tailscale)** 中确认状态为“已连接”。
4. 点击“允许 Tailscale 访问”，然后**点击“立即重启”**：应用会自动重启并重新绑定新地址（约 10 秒，页面会自动跳转），无需手动重启服务。
5. 重启完成后，用设置页面显示的 Tailscale IP 和端口从手机访问，例如 `http://100.x.y.z:8000/`。

网页设置只会绑定检测到的 Tailscale `100.x` IPv4 地址；Tailscale 未连接时不能启用。不要手动把 `HEALTH_HOST` 设为 `0.0.0.0`，也不要配置路由器端口映射或公共反向代理。

启动时会自动校验 Tailscale 地址：若 IP 已变化会自动更新配置并继续监听；若 Tailscale 尚未连接（如开机时自启先于 Tailscale），会暂以本机模式启动并在页面顶部提示，连接 Tailscale 后点“立即重启”即可恢复手机访问。

每台设备直接访问即可，无需登录。

## 6. 开机自启

自启只应在本机确认数据目录可访问后配置。它启动的仍是 `npm start`（Python 服务），健康助手由该服务按需调用本机 `pi`。

### Windows

自启不需要任何环境变量：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\setup-autostart.ps1
```

关闭自启：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\remove-autostart.ps1
```

任务名为 `HealthVaultWeb`。若修改了用户环境变量，请注销再登录，或重新注册任务。

### macOS

脚本不会写入任何密码或环境变量，也不会修改 LaunchAgent plist：

```bash
bash scripts/macos/setup-autostart.sh
```

关闭自启：

```bash
bash scripts/macos/remove-autostart.sh
```

日志位于 `~/Library/Logs/HealthVaultWeb/`。

## 7. 备份与恢复

### 日常备份

应用设置页可以创建 SQLite 数据库备份。它们保存在当前数据库旁的 `data/backups/` 中，**不包含**报告、附件、头像或设置文件。

建议至少每月一次，在服务停止后将整个 `data/` 目录复制到加密的外接硬盘或另一个受保护的位置；同时保留多份历史副本。不要只依赖同一磁盘中的 `data/backups/`。

### 恢复数据库

两种方式任选其一。

**方式一：网页导入（推荐，服务运行中即可）**

1. 打开 **设置 → 数据备份**；
2. 在“导入备份文件”选择要恢复的 `.db` 文件（可来自其它电脑/手机的导出），勾选确认；
3. 导入前系统会自动校验文件并创建当前库的预备份；成功后请重启应用。

**方式二：本机脚本（服务停止后）**

1. 停止服务；
2. 在设置页核对要恢复的备份文件；
3. 在保存数据的电脑、同一数据根目录下执行：

```powershell
# Windows
.\.venv\Scripts\python backend\scripts\restore_database.py <备份文件名.db> --confirm
```

```bash
# macOS
.venv/bin/python backend/scripts/restore_database.py <备份文件名.db> --confirm
```

恢复前会自动再创建一份数据库备份。恢复只替换 SQLite 数据库，**不会**回滚或删除附件、报告文件；恢复后请在本机打开应用核对记录。

## 8. 升级

升级前请先做一次完整 `data/` 异盘备份，然后停止服务：

```bash
git pull --ff-only
npm ci
```

Windows：

```powershell
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
npm test
npm run smoke
```

macOS：

```bash
.venv/bin/python -m pip install -r backend/requirements.txt
HEALTH_PYTHON="$PWD/.venv/bin/python" npm test
HEALTH_PYTHON="$PWD/.venv/bin/python" npm run smoke
```

启动新版本时，如果发现已有数据库的架构版本低于应用要求，会先创建 `health_preupgrade_*.db` 数据库备份，再执行迁移。该备份仍不包含附件和报告，所以完整 `data/` 备份不可省略。

如果升级失败：停止服务，恢复上一个代码版本，再按“恢复数据库”章节恢复升级前备份。不要删除原数据库来尝试解决问题。

## 9. 卸载或迁移到新电脑

1. 停止服务并关闭开机自启；
2. 复制整个 `data/` 目录到加密存储；
3. 在新电脑完成安装后，将备份的 `data/` 放入新项目目录，或设置相同的 `HEALTH_VAULT_HOME`；
4. 启动并核对成员、附件和最近备份后，再删除旧电脑副本。

只要保留 `data/`，就可以删除代码目录和 Python/Node 依赖；删除 `data/` 会永久删除档案和本地凭据。

## 10. 故障排查

| 现象 | 处理方式 |
| --- | --- |
| `未找到 Python` 或 `No module named 'uvicorn'` | `npm start` 会优先用项目 `.venv`；若仍报错，说明依赖没装在 `.venv` 里：`.venv\Scripts\python -m pip install -r backend\requirements.txt`（macOS：`.venv/bin/python -m pip install -r backend/requirements.txt`），或用 `HEALTH_PYTHON` 指定解释器。 |
| `未找到 pi CLI` | 执行 `npm install -g @earendil-works/pi-coding-agent` 并 `pi login`；也可用 `HEALTH_PI_BIN` 指定可执行文件路径。 |
| 助手回答很慢 | 助手用 pi 的默认模型；可在 `~/.pi/agent/settings.json` 改 `defaultProvider/defaultModel`，或用 `HEALTH_PI_MODEL=provider/model` 只给本应用换一个更快的模型。 |
| 端口被占用 | 停止占用 8000 的旧服务，或设置 `HEALTH_PORT` 使用其他端口。 |
| 手机无法访问 | 本版本已停用远程访问：只允许本机 `127.0.0.1`，绑定其他地址会拒绝启动。 |
| 页面直接打开且无登录 | 本版本已取消登录鉴权；这是预期行为，安全边界靠“只监听 127.0.0.1”。 |
| AI 不可用 | 在本机终端确认 `pi login` 已登录、`pi --list-models` 可选到模型；应用不再单独配置模型或 API Key。 |

## 11. 开发验证

安装完成后可运行：

```bash
npm test
npm run smoke
```

`npm run smoke` 会用临时数据库启动隔离服务，验证本机免登录直连、首页、备份 API 和 Agent HTTP 代理；不会读取或写入你的真实档案。
