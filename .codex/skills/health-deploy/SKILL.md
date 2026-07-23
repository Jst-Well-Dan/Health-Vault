---
name: health-deploy
description: 配置家庭健康档案的手机访问、Tailscale 远程访问和开机自启。当用户说"手机访问"、"配置 Tailscale"、"远程访问"、"开机自启"、"手机查看健康档案"时触发此 skill。
---

# 家庭健康档案远程访问

这个 skill 负责让已经能在本机运行的家庭健康档案被手机访问。安装依赖、初始化、启动、停止和状态检查由 `health-app` 负责。

**项目路径（默认）**：项目根目录  
**应用端口**：`8000`  
**本机访问地址**：`http://127.0.0.1:8000/`  
**手机访问地址**：`http://<电脑的 Tailscale IP>:8000/`

## 前置条件

配置手机访问前，先确认应用已经能在电脑本机访问：

Windows:

```powershell
netstat -ano | findstr ":8000"
```

macOS:

```bash
bash ".codex/skills/health-app/scripts/status_macos.sh"
```

如果服务未运行，先使用 `health-app`：

Windows:

```powershell
wscript ".codex\skills\health-app\scripts\start_hidden.vbs"
```

macOS:

```bash
bash ".codex/skills/health-app/scripts/start_hidden_macos.sh"
```

## 子命令

### `/health-deploy tailscale` — 配置手机访问

分步引导用户：

1. 电脑安装 Tailscale：`https://tailscale.com/download/windows`
   macOS: `https://tailscale.com/download/mac`
2. 电脑登录 Tailscale，确认出现 `100.x.x.x` 格式 IP。
3. 手机安装 Tailscale。
4. 手机使用同一个 Tailscale 账号登录。
5. 确认电脑和手机都显示 Connected。
6. 确认家庭健康档案服务已运行。
7. 让用户在手机浏览器访问：

```text
http://<电脑的 Tailscale IP>:8000/
```

提醒：

- 后端必须监听 `0.0.0.0`，`health-app` 的启动脚本已经这样配置。
- 手机打不开时，先检查 Tailscale 登录账号是否相同，再检查 `8000` 端口是否在监听。

### `/health-deploy autostart` — 配置开机自启

Windows:

注册 Windows 任务计划，登录后自动后台启动家庭健康档案：

```powershell
powershell -ExecutionPolicy Bypass -File ".codex\skills\health-deploy\scripts\setup_autostart.ps1" -ProjectPath "."
```

完成后可以立即触发验证：

```powershell
Start-ScheduledTask -TaskName "家庭健康档案"
```

macOS:

注册 LaunchAgent，登录后自动后台启动家庭健康档案：

```bash
bash ".codex/skills/health-deploy/scripts/setup_autostart_macos.sh"
```

完成后可以立即触发验证：

```bash
launchctl kickstart -k "gui/$(id -u)/com.health-vault-agent"
```

### `/health-deploy remove-autostart` — 移除开机自启

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File ".codex\skills\health-deploy\scripts\remove_autostart.ps1"
```

macOS:

```bash
bash ".codex/skills/health-deploy/scripts/remove_autostart_macos.sh"
```

## 推荐流程

当用户希望手机访问：

1. 使用 `health-app status` 或 `netstat` 确认服务运行。
2. 如未运行，使用 `health-app start-hidden` 启动。
3. 引导安装并登录 Tailscale。
4. 给出手机访问地址。
5. 用户需要时，再配置 `autostart`。

## 边界

- 不负责安装依赖、初始化数据库或普通启动停止；这些交给 `health-app`。
- 不负责报告导入；报告导入交给 `health-db-writer`。
- 不负责文档转换；文档转换交给 `mineru`。
