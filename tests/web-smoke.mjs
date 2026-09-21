import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const temp = await mkdtemp(join(tmpdir(), "health-vault-web-"));
const port = await freePort();
const base = `http://127.0.0.1:${port}`;
const venvPython = process.platform === "win32" ? join(root, ".venv", "Scripts", "python.exe") : join(root, ".venv", "bin", "python");
const python = process.env.HEALTH_PYTHON || (existsSync(venvPython) ? venvPython : "python");
const child = spawn(python, ["backend/run_backend.py"], {
  cwd: root,
  env: { ...process.env, HEALTH_PORT: String(port), HEALTH_HOST: "127.0.0.1", HEALTH_VAULT_HOME: temp, HEALTH_DB_PATH: join(temp, "data", "health.db"), HEALTH_MOCK_MODE: "1" },
  stdio: "ignore",
});

try {
  await waitFor(`${base}/api/meta`);
  const [page, meta, backup, agentGone] = await Promise.all([
    fetch(`${base}/`).then(r => r.text()),
    fetch(`${base}/api/meta`).then(r => r.json()),
    fetch(`${base}/api/backups/info`).then(r => r.json()),
    fetch(`${base}/api/agent/status`).then(r => r.status),
  ]);
  if (!page.includes("家庭健康档案") || page.includes("window.healthAgent")) throw new Error("Web 首页未加载纯浏览器实现");
  if (!meta.mock_mode || typeof backup.database_path !== "string") throw new Error("Web API 检查失败（本机直连应无需登录）");
  if (agentGone !== 404) throw new Error(`Agent 接口应已移除，实际为 ${agentGone}`);
  const login = await fetch(`${base}/api/auth/status`);
  if (login.status !== 404) throw new Error(`登录接口应已移除，实际为 ${login.status}`);
  console.log(JSON.stringify({ meta, agentRemoved: agentGone === 404, backupDir: backup.backup_dir }));
} finally {
  // Windows 下 child.kill() 不会杀掉子进程树，而 run_backend 会拉起 node agent runtime；
  // 不清理就会留下孤儿 runtime 共享同一份 data/agent-* 文件。
  killTree(child);
  await rm(temp, { recursive: true, force: true });
}

function killTree(child) {
  if (!child.pid) return;
  if (process.platform === "win32") {
    try { spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" }); } catch (_) { /* ignore */ }
  }
  try { child.kill(); } catch (_) { /* ignore */ }
}

function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => { const address = server.address(); server.close(() => typeof address === "object" && address ? resolvePort(address.port) : reject(new Error("无法获取端口"))); });
  });
}
async function waitFor(url) {
  for (let i = 0; i < 100; i++) { try { if ((await fetch(url)).ok) return; } catch (_) {} await new Promise(resolveWait => setTimeout(resolveWait, 100)); }
  throw new Error("Web 服务启动超时");
}
