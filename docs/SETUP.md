# 安装与维护指南

本文面向负责安装和维护家庭健康档案的人。当前正式支持 **Windows 10/11** 和 **macOS**；不承诺 Linux、NAS、Docker、公共云服务器或公网部署。

> 健康资料很敏感。请仅在自己控制的电脑和受信任的 Tailscale 网络中运行本应用；不要做端口映射或把服务公开到互联网。

## 1. 安装前确认

需要：

- Node.js **22.19+**（含 npm）；
- Python **3.10+**；
- Git；
- 可选：Tailscale，用于手机访问。

应用数据默认位于项目目录的 `data/`。若设置 `HEALTH_VAULT_HOME`，数据则位于该目录的 `data/` 下。**代码目录和数据目录都应放在受本机账户保护的磁盘中。**

健康档案本身默认只存本机。健康助手和 AI 报告解析是例外：它们会将你输入的消息、报告内容/图片及必要的成员信息发送至你在应用内配置的第三方模型服务。使用前请确认该服务的隐私、保留、地区合规与收费政策。

## 2. 首次安装

克隆公开仓库后进入项目目录。

### Windows（PowerShell）

```powershell
git clone <公开仓库地址> Health-Vault
cd Health-Vault
npm ci
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
$env:HEALTH_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe)
$env:HEALTH_APP_PASSWORD = "设置一个仅供家人使用的密码"
npm start
```

如果 `python` 不可用，可改用 Windows Python Launcher：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
$env:HEALTH_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe)
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
export HEALTH_APP_PASSWORD="设置一个仅供家人使用的密码"
npm start
```

首次启动会创建空数据库、会话签名密钥和 Agent 本地凭据目录。随后在本机浏览器打开 <http://127.0.0.1:8000/>，使用家庭密码登录。

`HEALTH_APP_PASSWORD` 不能为空。请使用长且独有的密码；不要将它写入 Git、截图、聊天记录或共享脚本。

## 3. 日常启动与停止

启动前，使用与首次安装相同的虚拟环境和密码环境变量，然后运行：

```powershell
# Windows
$env:HEALTH_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe)
$env:HEALTH_APP_PASSWORD = "家庭密码"
npm start
```

```bash
# macOS
export HEALTH_APP_PASSWORD="家庭密码"
export HEALTH_PYTHON="$PWD/.venv/bin/python"
npm start
```

在终端按 `Ctrl+C` 可停止服务。停止服务后才可执行数据库恢复或升级操作。

如端口 8000 已被占用，可设置 `HEALTH_PORT` 后再启动，例如 Windows：

```powershell
$env:HEALTH_PORT = "8100"
npm start
```

## 4. 手机访问（Tailscale）

1. 先确认电脑本机登录正常。
2. 在电脑和手机安装 Tailscale，并登录同一个受信任的 tailnet。
3. 在应用的 **设置 → 远程访问 (Tailscale)** 中确认状态为“已连接”。
4. 点击“允许 Tailscale 访问”，然后重启应用。
5. 用设置页面显示的 Tailscale IP 和端口从手机访问，例如 `http://100.x.y.z:8000/`。

网页设置只会绑定检测到的 Tailscale `100.x` IPv4 地址；Tailscale 未连接时不能启用。不要手动把 `HEALTH_HOST` 设为 `0.0.0.0`，也不要配置路由器端口映射或公共反向代理。

每台设备都需要独立登录；不要分享浏览器 Cookie。

## 5. 登录自启

自启只应在本机登录、确认数据目录可访问后配置。它启动的仍是 `npm start`，会编译 Agent runtime 并由 FastAPI 管理它；不要单独为 Agent 创建服务。

### Windows

先把家庭密码设为**当前 Windows 用户**的环境变量，再注册任务：

```powershell
[Environment]::SetEnvironmentVariable("HEALTH_APP_PASSWORD", "家庭密码", "User")
powershell -ExecutionPolicy Bypass -File .\scripts\windows\setup-autostart.ps1
```

关闭自启：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\remove-autostart.ps1
```

任务名为 `HealthVaultWeb`。修改用户环境变量后请注销再登录，或重新注册任务。

### macOS

脚本会提示输入密码（或使用当前 `HEALTH_APP_PASSWORD`），并把它保存到当前用户的 macOS Keychain，不会写入 LaunchAgent plist：

```bash
bash scripts/macos/setup-autostart.sh
```

关闭自启并删除 Keychain 中保存的密码：

```bash
bash scripts/macos/remove-autostart.sh
```

日志位于 `~/Library/Logs/HealthVaultWeb/`。

## 6. 备份与恢复

### 日常备份

应用设置页可以创建 SQLite 数据库备份。它们保存在当前数据库旁的 `data/backups/` 中，**不包含**报告、附件、头像或设置文件。

建议至少每月一次，在服务停止后将整个 `data/` 目录复制到加密的外接硬盘或另一个受保护的位置；同时保留多份历史副本。不要只依赖同一磁盘中的 `data/backups/`。

### 恢复数据库

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

恢复前会自动再创建一份数据库备份。恢复只替换 SQLite 数据库，**不会**回滚或删除附件、报告文件；恢复后请在本机登录并核对记录。

## 7. 升级

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

## 8. 卸载或迁移到新电脑

1. 停止服务并关闭登录自启；
2. 复制整个 `data/` 目录到加密存储；
3. 在新电脑完成安装后，将备份的 `data/` 放入新项目目录，或设置相同的 `HEALTH_VAULT_HOME`；
4. 启动并核对成员、附件和最近备份后，再删除旧电脑副本。

只要保留 `data/`，就可以删除代码目录和 Python/Node 依赖；删除 `data/` 会永久删除档案和本地凭据。

## 9. 故障排查

| 现象 | 处理方式 |
| --- | --- |
| `未找到 Python` | 安装 Python 3.10+；Windows 设置 `HEALTH_PYTHON` 为 `.venv\\Scripts\\python.exe`，macOS 设置为 `.venv/bin/python`。 |
| `Agent runtime 尚未编译` | 在项目根目录执行 `npm run compile`，并确认 Node.js 为 22.19+。 |
| 端口被占用 | 停止占用 8000 的旧服务，或设置 `HEALTH_PORT` 使用其他端口。 |
| 手机无法访问 | 确认两台设备已登录同一 Tailscale 网络；在设置中重新检测并重启服务。 |
| 登录密码失效 | 确认当前终端或自启环境使用的 `HEALTH_APP_PASSWORD`；不要混用多个环境变量来源。 |
| AI 不可用 | 在设置 → AI 配置中主动登录或填写自己的 API Key；AI 功能需要联网和第三方服务账号。 |

## 10. 开发验证

安装完成后可运行：

```bash
npm test
npm run smoke
```

`npm run smoke` 会用临时数据库启动隔离服务，验证登录保护、首页、备份 API 和 Agent HTTP 代理；不会读取或写入你的真实档案。
