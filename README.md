# 家庭健康档案

一个本地优先的家庭健康档案 Web 应用：电脑和已加入同一 Tailscale 网络的手机可同时使用同一份数据。

- 健康记录、报告、附件和备份均保留在服务器本机 `data/` 目录
- 浏览器可上传报告和普通附件、创建/查看备份，并使用健康助手
- 使用一个家庭共享密码和 HttpOnly 会话保护所有页面、静态资源与 API
- 健康助手是独立的本机 Node 进程；浏览器只能经 FastAPI 的已认证代理访问它

> 请只将服务开放给受信任的本机或 Tailscale 网络。它不是公共互联网服务。

## 安装与启动

需要 Python、Node.js **22.19+** 和 npm。

```powershell
npm install
python -m pip install -r backend\requirements.txt
```

启动前必须设置家庭共享密码。以下 PowerShell 设置仅对当前窗口有效；要给开机自启使用，请在 Windows 用户环境变量中设置 `HEALTH_APP_PASSWORD`。

```powershell
$env:HEALTH_APP_PASSWORD = "请换成一段长且独有的家庭密码"
npm start
```

默认只监听 `127.0.0.1:8000`，在本机浏览器打开 `http://127.0.0.1:8000/` 并用该密码登录。

## 手机访问（Tailscale）

确认本机登录可用后，设置监听地址并重新启动：

```powershell
$env:HEALTH_HOST = "0.0.0.0"
$env:HEALTH_APP_PASSWORD = "同一段家庭密码"
npm start
```

在电脑和手机都登录同一 Tailscale 网络，然后通过 `http://<电脑的 Tailscale IP>:8000/` 访问。不要做端口映射、不要将此地址暴露到公网。

## 数据与安全

- 开发版数据库：`data/health.db`；报告、导入文件、备份和日志也在 `data/`。
- 应用首次启动会在数据目录创建会话签名密钥、Agent 进程密钥及加密凭据文件。这些文件已被 `.gitignore` 排除，不能复制、提交或共享。
- Agent 凭据使用 AES-256-GCM 加密；安全边界为本机文件系统权限，弱于 Electron/OS 密钥库。请保护运行服务的操作系统账户。
- 报告导入始终先暂存、核对、dry-run，再写入；写入会创建数据库备份。
- 浏览器只能创建和查看备份。恢复必须在保存数据的电脑上、停止 Web 服务后执行：

```powershell
python backend\scripts\restore_database.py <备份文件名.db> --confirm
```

恢复只回滚 SQLite 数据库，不回滚附件或报告文件。

## 验证

```powershell
npm test
npm run smoke
```

`npm run smoke` 会启动隔离的 Web 服务，验证登录保护、浏览器首页、备份 API 及 Agent HTTP 代理。
