import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const temp = await mkdtemp(join(tmpdir(), "health-vault-web-"));
const port = await freePort();
const base = `http://127.0.0.1:${port}`;
const child = spawn(process.env.HEALTH_PYTHON || "python", ["backend/run_backend.py"], {
  cwd: root,
  env: { ...process.env, HEALTH_PORT: String(port), HEALTH_HOST: "127.0.0.1", HEALTH_VAULT_HOME: temp, HEALTH_DB_PATH: join(temp, "data", "health.db"), HEALTH_MOCK_MODE: "1", HEALTH_APP_PASSWORD: "smoke-family-password" },
  stdio: "ignore",
});

try {
  await waitFor(`${base}/api/auth/status`);
  const denied = await fetch(`${base}/api/meta`);
  if (denied.status !== 401) throw new Error(`未登录 API 应拒绝访问，实际为 ${denied.status}`);
  const login = await fetch(`${base}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: "smoke-family-password" }) });
  if (!login.ok) throw new Error(`登录失败：${login.status}`);
  const cookie = login.headers.get("set-cookie")?.split(";", 1)[0];
  if (!cookie) throw new Error("登录未签发会话 Cookie");
  const headers = { Cookie: cookie };
  const [page, meta, backup, settings] = await Promise.all([
    fetch(`${base}/`, { headers }).then(r => r.text()),
    fetch(`${base}/api/meta`, { headers }).then(r => r.json()),
    fetch(`${base}/api/backups/info`, { headers }).then(r => r.json()),
    fetch(`${base}/api/agent-runtime/agent/settings`, { headers }).then(async r => ({ status: r.status, body: await r.json() })),
  ]);
  if (!page.includes("家庭健康档案") || page.includes("window.healthAgent")) throw new Error("Web 首页未加载纯浏览器实现");
  if (!meta.mock_mode || typeof backup.database_path !== "string") throw new Error("已登录的 Web API 检查失败");
  if (settings.status !== 200 || !Array.isArray(settings.body.providers)) throw new Error(`Agent HTTP 代理检查失败：${JSON.stringify(settings)}`);
  console.log(JSON.stringify({ meta, providerCount: settings.body.providers.length, backupDir: backup.backup_dir }));
} finally {
  child.kill();
  await rm(temp, { recursive: true, force: true });
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
