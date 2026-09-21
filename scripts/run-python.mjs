// 选择 Python 解释器：优先项目虚拟环境，其次 HEALTH_PYTHON，最后 PATH。
// 这样零环境变量也能 `npm start`，不会因为用到缺少依赖的系统 Python 而报 No module named 'uvicorn'。
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const venvCandidates = process.platform === "win32"
  ? [join(root, ".venv", "Scripts", "python.exe"), join(root, "venv", "Scripts", "python.exe")]
  : [join(root, ".venv", "bin", "python"), join(root, "venv", "bin", "python")];
const pathCandidates = process.platform === "win32" ? ["python", "py"] : ["python3", "python"];

const configured = process.env.HEALTH_PYTHON;
const ordered = [configured, ...venvCandidates.filter(existsSync), ...pathCandidates].filter(Boolean);

const probeArgs = (command) => (command === "py" ? ["-3"] : []);
const hasDependencies = (command) => {
  const probe = spawnSync(command, [...probeArgs(command), "-c", "import fastapi, uvicorn"], { stdio: "ignore", env: process.env });
  if (probe.error?.code === "ENOENT") return false;
  return probe.status === 0;
};

const chosen = configured || ordered.find((command) => hasDependencies(command));
if (!chosen) {
  console.error([
    "未能找到已安装后端依赖的 Python。",
    "请在项目根目录创建虚拟环境并安装依赖：",
    "  python -m venv .venv",
    process.platform === "win32" ? "  .\\.venv\\Scripts\\python -m pip install -r backend\\requirements.txt" : "  .venv/bin/python -m pip install -r backend/requirements.txt",
    "也可以用 HEALTH_PYTHON 指定其他解释器路径。",
  ].join("\n"));
  process.exit(1);
}

const args = chosen === "py" ? ["-3", ...process.argv.slice(2)] : process.argv.slice(2);
const result = spawnSync(chosen, args, { stdio: "inherit", env: process.env });
if (result.error?.code === "ENOENT") {
  console.error(`未找到 Python 解释器：${chosen}。请设置 HEALTH_PYTHON 指向可用路径。`);
  process.exit(1);
}
if (result.error) throw result.error;
process.exit(result.status ?? 1);
