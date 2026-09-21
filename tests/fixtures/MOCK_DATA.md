# 模拟数据与模拟模式

这套模拟数据只用于公开演示和前端调试，所有成员、就诊、检验、用药、提醒和附件文本均为虚构内容。

## 运行模拟模式

在 `backend` 目录启动服务时设置 `HEALTH_MOCK_MODE=1`：

```powershell
$env:HEALTH_MOCK_MODE='1'
python -m uvicorn main:app --reload
```

打开前端后，页面右上角会显示“模拟模式”。此时后端使用独立数据库：

```text
tests/fixtures/health_mock.db
```

真实数据库仍然默认使用：

```text
data/health.db
```

## 重新生成模拟数据

```powershell
cd backend
python scripts/seed_mock_data.py --reset
```

脚本会重建模拟库内容，并生成可预览的 Markdown 附件到：

```text
tests/fixtures/attachments/
```

## 自定义数据库路径

需要临时指定数据库文件时，可以设置 `HEALTH_DB_PATH`：

```powershell
$env:HEALTH_DB_PATH='E:\tmp\health_demo.db'
python -m uvicorn main:app --reload
```

`HEALTH_DB_PATH` 优先级高于默认真实库和默认模拟库路径。
