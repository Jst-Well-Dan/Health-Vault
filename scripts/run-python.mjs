import { spawnSync } from "node:child_process";

const candidates = process.env.HEALTH_PYTHON
  ? [process.env.HEALTH_PYTHON]
  : process.platform === "win32"
    ? ["python", "py"]
    : ["python3", "python"];

for (const command of candidates) {
  const args = command === "py" ? ["-3", ...process.argv.slice(2)] : process.argv.slice(2);
  const result = spawnSync(command, args, { stdio: "inherit", env: process.env });
  if (result.error?.code === "ENOENT") continue;
  if (result.error) throw result.error;
  process.exit(result.status ?? 1);
}

console.error("未找到 Python。请安装 Python 3.10+，或设置 HEALTH_PYTHON 为 Python 可执行文件路径。");
process.exit(1);
