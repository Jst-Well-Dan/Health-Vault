---
name: health-app
description: 管理家庭健康档案应用在本机的安装、初始化、启动、停止和状态检查。当用户说"启动健康档案"、"安装项目"、"初始化项目"、"停止服务"、"检查服务状态"、"本机运行"时触发此 skill。
---

# 家庭健康档案本机运行

这个 skill 只负责让项目在当前电脑上运行起来。手机访问、Tailscale 和开机自启交给 `health-deploy`。

**项目路径（默认）**：项目根目录  
**后端目录**：`backend/`  
**默认端口**：`8000`  
**本机访问地址**：`http://127.0.0.1:8000/`

## 子命令

### `/health-app setup` — 首次初始化

用于新克隆项目后的首次准备。

Windows:

```powershell
cd backend
pip install -r requirements.txt
```

macOS:

```bash
cd backend
python3.12 -m pip install --user --break-system-packages -r requirements.txt
```

2. 初始化成员数据：

Windows:

```powershell
python scripts/seed_members.py
```

macOS:

```bash
python3.12 scripts/seed_members.py
```

注意：

- 如果 `data/health.db` 已存在，不要覆盖或重建数据库。
- 初始化失败时先说明错误，不要删除真实数据库。

### `/health-app start` — 启动服务

前台启动，适合调试：

Windows:

```powershell
cmd /c ".codex\skills\health-app\scripts\start.bat"
```

macOS:

```bash
bash ".codex/skills/health-app/scripts/start_macos.sh"
```

启动后告诉用户：

```text
http://127.0.0.1:8000/
```

### `/health-app start-hidden` — 后台启动

后台静默启动，适合日常使用：

Windows:

```powershell
wscript ".codex\skills\health-app\scripts\start_hidden.vbs"
```

macOS:

```bash
bash ".codex/skills/health-app/scripts/start_hidden_macos.sh"
```

### `/health-app stop` — 停止服务

Windows:

```powershell
cmd /c ".codex\skills\health-app\scripts\stop.bat"
```

macOS:

```bash
bash ".codex/skills/health-app/scripts/stop_macos.sh"
```

### `/health-app status` — 检查服务状态

Windows:

```powershell
netstat -ano | findstr ":8000"
```

macOS:

```bash
bash ".codex/skills/health-app/scripts/status_macos.sh"
```

- 有 `LISTENING` 行：服务运行中，显示 PID。
- 无输出：服务未运行。

## 推荐流程

新用户首次使用：

1. `setup`
2. `start`
3. `status`
4. 告诉用户本机访问地址

已有项目：

1. `status`
2. 如未运行，执行 `start` 或 `start-hidden`
3. 告诉用户本机访问地址

## 边界

- 不处理报告导入；报告导入使用 `health-db-writer`。
- 不处理 MinerU 文档转换；文档转换使用 `mineru`。
- 不处理 Tailscale、手机访问或开机自启；这些使用 `health-deploy`。
- 不删除、重建或覆盖 `data/health.db`。
