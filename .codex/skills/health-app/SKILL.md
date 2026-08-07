---
name: health-app
description: 管理家庭健康档案纯 Web 应用的安装、启动、停止和状态检查。
---

# 家庭健康档案 Web 版运行

应用由 FastAPI 和其自动启动的 loopback Node Agent runtime 组成。用户只启动一个入口；不要启动 Electron、打开桌面安装包或直接暴露 Agent runtime。

## 首次准备

```powershell
npm install
python -m pip install -r backend\requirements.txt
```

必须先设置家庭共享密码：

```powershell
$env:HEALTH_APP_PASSWORD = "设置一段长且独有的密码"
```

不要覆盖或重建已有 `data/health.db`。

## 启动

前台开发运行：

```powershell
npm start
```

这会编译 Agent runtime 后启动 Python Web 服务，默认地址为 `http://127.0.0.1:8000/`。

后台/开机自启运行前，请将 `HEALTH_APP_PASSWORD` 配置为用户环境变量；需要手机访问时另设 `HEALTH_HOST=0.0.0.0`，并只结合 Tailscale 使用。

## 停止与状态

Windows：

```powershell
cmd /c ".codex\skills\health-app\scripts\stop.bat"
netstat -ano | findstr ":8000"
```

## 边界

- 报告转换用 `mineru`，结构化写入用 `health-db-writer`。
- 手机/Tailscale 和开机自启参见 `health-deploy`。
- 不删除真实数据库、报告、备份、会话或 Agent 凭据文件。
