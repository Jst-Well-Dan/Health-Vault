---
name: health-deploy
description: 配置家庭健康档案 Web 版的 Tailscale 手机访问和开机自启。
---

# 家庭健康档案 Web 版远程访问

仅在本机登录已验证后配置手机访问。此应用是单家庭共享密码服务，不是公共 Web 服务。

## 前置条件

1. 已执行 `npm install` 和 `python -m pip install -r backend\requirements.txt`。
2. 已把强密码写入用户环境变量 `HEALTH_APP_PASSWORD`。
3. 电脑和手机均登录同一个受信任 Tailscale 网络。

## 启动供手机访问

```powershell
$env:HEALTH_HOST = "0.0.0.0"
$env:HEALTH_APP_PASSWORD = "家庭共享密码"
npm start
```

从 `tailscale ip -4` 获取电脑 IP，在手机浏览器访问：

```text
http://<电脑的 Tailscale IP>:8000/
```

每台设备都必须登录应用；不要共享 Cookie，不要配置路由器端口映射、反向代理或公共互联网访问。

## 开机自启

先确保用户级 `HEALTH_APP_PASSWORD`（以及需要手机访问时的 `HEALTH_HOST=0.0.0.0`）已设置，再运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".codex\skills\health-deploy\scripts\setup_autostart.ps1" -ProjectPath "."
```

脚本将启动 `npm run start`，它会负责编译和拉起 Agent runtime。不要为 Agent 单独注册开机任务。

## 边界

- 仅使用 Tailscale 暴露受认证的 FastAPI 服务；Agent runtime 永远只绑定 loopback。
- 不处理报告导入或数据库恢复。
- 恢复只能在服务器本机停止服务后执行 `backend/scripts/restore_database.py <filename> --confirm`。
