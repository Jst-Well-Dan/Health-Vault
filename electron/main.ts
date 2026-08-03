import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { copyFile, mkdir, readFile, rename, stat, unlink, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { basename, dirname, join, resolve } from "node:path";
import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, shell, Tray } from "electron";
import { HealthAgent } from "./agent.js";

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { void showOrCreateWindow(); });
}

let window: BrowserWindow | null = null;
let backend: ChildProcess | null = null;
let healthAgent: HealthAgent | null = null;
let backendUrl: string | null = null;
let quitting = false;
let stoppingBackendExpected = false;
let tray: Tray | null = null;
let deploySettings = { backgroundEnabled: false };
const selectedAttachmentFiles = new Map<string, string>();
const ATTACHMENT_EXTENSIONS = ["pdf", "png", "jpg", "jpeg", "webp", "bmp", "gif", "txt", "md", "csv", "json", "doc", "docx", "xls", "xlsx"];
const wait = (ms: number) => new Promise((resolveWait) => setTimeout(resolveWait, ms));

function appRoot() { return resolve(app.getAppPath()); }
function dataHome() { return app.isPackaged ? app.getPath("userData") : appRoot(); }
function agentCredentialPath() { return join(app.getPath("userData"), "agent-credentials.bin"); }
function agentSettingsPath() { return join(app.getPath("userData"), "agent-settings.json"); }
function activeDatabasePath() { return resolve(process.env.HEALTH_DB_PATH || join(dataHome(), "data", "health.db")); }
function deploySettingsPath() { return join(app.getPath("userData"), "deploy-settings.json"); }

async function loadDeploySettings() {
  try { deploySettings = { ...deploySettings, ...JSON.parse(await readFile(deploySettingsPath(), "utf8")) }; } catch {}
}

async function saveDeploySettings() {
  await writeFile(deploySettingsPath(), JSON.stringify(deploySettings, null, 2), "utf8");
}

function getTailscaleIp(): Promise<string | null> {
  return new Promise((resolveIp) => {
    let proc: ChildProcess;
    try { proc = spawn("tailscale", ["ip", "-4"], { windowsHide: true }); }
    catch { resolveIp(null); return; }
    let out = "";
    proc.stdout?.on("data", (chunk) => { out += String(chunk); });
    proc.once("error", () => resolveIp(null));
    proc.once("exit", (code) => resolveIp(code === 0 && out.trim() ? out.trim().split(/\s+/)[0] : null));
  });
}

async function freePort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") return reject(new Error("无法分配后端端口"));
      server.close(() => resolvePort(address.port));
    });
  });
}

async function startBackend(host: string): Promise<string> {
  const port = await freePort();
  const root = appRoot();
  const executable = app.isPackaged
    ? join(process.resourcesPath, "backend", "health-vault-backend.exe")
    : process.env.HEALTH_PYTHON || "python";
  const args = app.isPackaged ? [] : [join(root, "backend", "run_backend.py")];
  backend = spawn(executable, args, {
    cwd: app.isPackaged ? process.resourcesPath : root,
    windowsHide: true,
    stdio: app.isPackaged ? "ignore" : "inherit",
    env: {
      ...process.env,
      HEALTH_HOST: host,
      HEALTH_PORT: String(port),
      HEALTH_VAULT_HOME: dataHome(),
      HEALTH_FRONTEND_DIR: app.isPackaged ? join(process.resourcesPath, "frontend") : join(root, "frontend"),
      HEALTH_PUBLIC_DIR: app.isPackaged ? join(process.resourcesPath, "public") : join(root, "data", "public"),
    },
  });
  backend.once("exit", (code) => {
    if (!quitting && !stoppingBackendExpected) window?.webContents.send("agent:event", { type: "fatal", text: `后端已退出 (${code})` });
  });
  const baseUrl = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 80; attempt++) {
    try { if ((await fetch(`${baseUrl}/api/meta`)).ok) return baseUrl; } catch {}
    await wait(100);
  }
  throw new Error("健康档案后端启动超时");
}

async function initHealthAgent(baseUrl: string) {
  healthAgent?.stop();
  healthAgent = new HealthAgent(baseUrl, () => window?.webContents, agentCredentialPath(), agentSettingsPath());
  await healthAgent.init();
}

function currentHost() { return deploySettings.backgroundEnabled ? "0.0.0.0" : "127.0.0.1"; }

async function createWindow() {
  let baseUrl = backendUrl;
  if (!baseUrl) {
    baseUrl = await startBackend(currentHost());
    backendUrl = baseUrl;
  }
  window = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 900,
    minHeight: 640,
    backgroundColor: "#f5efe3",
    webPreferences: {
      preload: join(app.getAppPath(), "dist-electron", "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  await initHealthAgent(baseUrl);
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  window.on("close", (event) => {
    if (!quitting && deploySettings.backgroundEnabled) { event.preventDefault(); window?.hide(); }
  });
  await window.loadURL(baseUrl);
}

async function showOrCreateWindow() {
  if (window && !window.isDestroyed()) { window.show(); window.focus(); return; }
  await createWindow();
}

function createTray() {
  tray = new Tray(nativeImage.createEmpty());
  tray.setToolTip("家庭健康档案");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "打开主窗口", click: () => void showOrCreateWindow() },
    { type: "separator" },
    { label: "退出", click: () => app.quit() },
  ]));
  tray.on("click", () => void showOrCreateWindow());
}

async function deployStatusPayload() {
  return {
    backgroundEnabled: deploySettings.backgroundEnabled,
    autostart: app.getLoginItemSettings().openAtLogin,
    port: backendUrl ? new URL(backendUrl).port : null,
  };
}

async function setBackgroundMode(enabled: boolean) {
  if (deploySettings.backgroundEnabled === enabled) return;
  deploySettings.backgroundEnabled = enabled;
  await saveDeploySettings();
  if (!backendUrl) return;
  healthAgent?.stop();
  await stopBackend();
  const baseUrl = await startBackend(currentHost());
  backendUrl = baseUrl;
  await initHealthAgent(baseUrl);
  if (window && !window.isDestroyed()) await window.loadURL(baseUrl);
}

async function stopBackend() {
  const processToStop = backend;
  if (!processToStop?.pid) {
    backend = null;
    backendUrl = null;
    return;
  }
  backend = null;
  backendUrl = null;
  stoppingBackendExpected = true;
  await new Promise<void>((resolveStop) => {
    let resolved = false;
    const finish = () => {
      if (!resolved) {
        resolved = true;
        stoppingBackendExpected = false;
        resolveStop();
      }
    };
    processToStop.once("exit", finish);
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/pid", String(processToStop.pid), "/t", "/f"], { windowsHide: true, stdio: "ignore" });
    } else {
      processToStop.kill();
    }
    setTimeout(finish, 2500);
  });
}

ipcMain.handle("agent:send", (_event, message: string) => healthAgent?.send(message));
ipcMain.handle("agent:stop", () => healthAgent?.stop());
ipcMain.handle("agent:history", () => healthAgent?.history());
ipcMain.handle("agent:settings", (_event, provider) => healthAgent?.getSettings(provider));
ipcMain.handle("agent:save-settings", (_event, value) => healthAgent?.saveSettings(value));
ipcMain.handle("agent:login", (_event, value) => healthAgent?.login(value.provider, value.type, value.apiKey));
ipcMain.handle("agent:logout", (_event, provider) => healthAgent?.logout(provider));
ipcMain.on("agent:response", (_event, { id, value }) => healthAgent?.respond(id, value));

ipcMain.handle("deploy:status", () => deployStatusPayload());
ipcMain.handle("deploy:set-background", async (_event, enabled: boolean) => {
  await setBackgroundMode(Boolean(enabled));
  return deployStatusPayload();
});
ipcMain.handle("deploy:set-autostart", (_event, enabled: boolean) => {
  app.setLoginItemSettings({ openAtLogin: Boolean(enabled), openAsHidden: true, args: enabled ? ["--background"] : [] });
  return deployStatusPayload();
});
ipcMain.handle("deploy:check-tailscale", async () => ({ ip: await getTailscaleIp() }));

ipcMain.handle("report:select", async () => {
  if (!backendUrl) throw new Error("健康档案后端尚未就绪");
  const result = await dialog.showOpenDialog(window!, {
    title: "选择体检报告",
    properties: ["openFile"],
    filters: [{ name: "健康报告", extensions: ["pdf", "png", "jpg", "jpeg", "webp", "bmp"] }],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const filePath = result.filePaths[0];
  const content = await readFile(filePath);
  const form = new FormData();
  form.append("file", new Blob([content]), filePath.split(/[\\/]/).pop() || "report");
  const response = await fetch(`${backendUrl}/api/imports/stage`, { method: "POST", body: form });
  const text = await response.text();
  if (!response.ok) throw new Error(parseApiError(text) || "报告暂存失败");
  return JSON.parse(text);
});
ipcMain.handle("report:analyze", (_event, source, member) => healthAgent?.analyzeReport(source, member));
ipcMain.handle("report:dry-run", async (_event, proposal) => reportApi("/api/imports/dry-run", proposal));
ipcMain.handle("report:commit", async (_event, proposal) => reportApi("/api/imports/commit", proposal));

ipcMain.handle("backup:info", async () => backupApiJson("/api/backups/info", "GET"));
ipcMain.handle("backup:create", async () => backupApiJson("/api/backups", "POST"));
ipcMain.handle("backup:validate", async (_event, filename: string) => backupApiJson("/api/backups/validate", "POST", { filename: safeFilename(filename) }));
ipcMain.handle("backup:prepare-restore", async (_event, filename: string) => backupApiJson("/api/backups/prepare-restore", "POST", { filename: safeFilename(filename) }));
ipcMain.handle("backup:restore", async (_event, filename: string) => restoreDatabaseFromBackup(safeFilename(filename)));
ipcMain.handle("backup:open-folder", async () => {
  const info = await backupApiJson("/api/backups/info", "GET");
  if (!info?.backup_dir || typeof info.backup_dir !== "string") throw new Error("备份目录不可用");
  return shell.openPath(info.backup_dir);
});

ipcMain.handle("attachment:select", async () => {
  if (!backendUrl) throw new Error("健康档案后端尚未就绪");
  const result = await dialog.showOpenDialog(window!, {
    title: "选择附件文件",
    properties: ["openFile"],
    filters: [{ name: "健康档案附件", extensions: ATTACHMENT_EXTENSIONS }],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const token = randomUUID();
  selectedAttachmentFiles.set(token, result.filePaths[0]);
  return { token, filename: basename(result.filePaths[0]) };
});

ipcMain.handle("attachment:upload", async (_event, metadata: Record<string, unknown>) => {
  if (!backendUrl) throw new Error("健康档案后端尚未就绪");
  const token = typeof metadata?.file_token === "string" ? metadata.file_token : "";
  const filePath = selectedAttachmentFiles.get(token);
  if (!filePath) throw new Error("请先选择附件文件");
  try {
    const content = await readFile(filePath);
    const form = new FormData();
    form.append("file", new Blob([content]), basename(filePath));
    for (const [key, value] of Object.entries(metadata || {})) {
      if (key === "file_token" || value === undefined || value === null || value === "") continue;
      form.append(key, String(value));
    }
    const response = await fetch(`${backendUrl}/api/attachments/upload`, { method: "POST", body: form });
    const text = await response.text();
    if (!response.ok) throw new Error(parseApiError(text) || "附件上传失败");
    return JSON.parse(text);
  } finally {
    selectedAttachmentFiles.delete(token);
  }
});

async function reportApi(path: string, proposal: unknown) {
  if (!backendUrl) throw new Error("健康档案后端尚未就绪");
  const response = await fetch(`${backendUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(proposal),
  });
  const text = await response.text();
  if (!response.ok) throw new Error(parseApiError(text) || "报告写入失败");
  return JSON.parse(text);
}

async function backupApiJson(path: string, method: "GET" | "POST", body?: unknown) {
  if (!backendUrl) throw new Error("健康档案后端尚未就绪");
  const response = await fetch(`${backendUrl}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  if (!response.ok) throw new Error(parseApiError(text) || "备份操作失败");
  return JSON.parse(text);
}

async function restoreDatabaseFromBackup(filename: string) {
  let preRestoreFilename = "";
  try {
    const validated = await backupApiJson("/api/backups/validate", "POST", { filename });
    const confirmation = await dialog.showMessageBox(window!, {
      type: "warning",
      buttons: ["取消", "确认恢复"],
      defaultId: 0,
      cancelId: 0,
      title: "确认恢复数据库",
      message: `确认从备份「${validated.filename}」恢复数据库？`,
      detail: "恢复会关闭并重启后端，只恢复 SQLite 数据库，不回滚附件/报告文件。恢复前会自动备份当前数据库。",
    });
    if (confirmation.response !== 1) return { ok: false, cancelled: true };

    const prepared = await backupApiJson("/api/backups/prepare-restore", "POST", { filename });
    preRestoreFilename = prepared?.pre_restore_backup?.filename || "";
    return await replaceDatabaseWithPreparedBackup(prepared, preRestoreFilename);
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err), pre_restore_filename: preRestoreFilename };
  }
}

async function replaceDatabaseWithPreparedBackup(prepared: any, preRestoreFilename: string) {
  const selectedFilename = safeFilename(prepared?.selected_backup?.filename);
  const backupDir = resolve(String(prepared?.backup_dir || ""));
  const backupPath = safeResolveInDirectory(backupDir, selectedFilename);
  await stat(backupPath);

  const targetDb = activeDatabasePath();
  const preparedDb = resolve(String(prepared?.database_path || ""));
  if (preparedDb !== targetDb) throw new Error("后端数据库路径与桌面端预期不一致，已取消恢复");
  await mkdir(dirname(targetDb), { recursive: true });

  const timestamp = new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
  const tempDb = join(dirname(targetDb), `.health_restore_${timestamp}_${randomUUID()}.tmp`);
  const beforeDb = join(dirname(targetDb), `${basename(targetDb)}.before_restore_${timestamp}.db`);
  let movedCurrent = false;

  try {
    await copyFile(backupPath, tempDb);
    healthAgent?.stop();
    await stopBackend();
    await wait(500);

    try {
      await rename(targetDb, beforeDb);
      movedCurrent = true;
    } catch (err: any) {
      if (err?.code !== "ENOENT") throw err;
    }
    await moveSidecarFiles(targetDb, timestamp);
    await rename(tempDb, targetDb);

    const newUrl = await startBackend(currentHost());
    backendUrl = newUrl;
    await initHealthAgent(newUrl);
    if (window && !window.isDestroyed()) await window.loadURL(newUrl);
    return { ok: true, restored_filename: selectedFilename, pre_restore_filename: preRestoreFilename, before_restore_filename: basename(beforeDb) };
  } catch (err) {
    await rollbackRestore(targetDb, tempDb, beforeDb, movedCurrent);
    return { ok: false, error: err instanceof Error ? err.message : String(err), pre_restore_filename: preRestoreFilename };
  }
}

async function moveSidecarFiles(targetDb: string, timestamp: string) {
  const recoveryDir = join(dirname(targetDb), "restore-recovery");
  await mkdir(recoveryDir, { recursive: true });
  for (const suffix of ["-wal", "-shm"]) {
    const sidecar = `${targetDb}${suffix}`;
    try {
      await rename(sidecar, join(recoveryDir, `${basename(sidecar)}.before_restore_${timestamp}`));
    } catch (err: any) {
      if (err?.code !== "ENOENT") throw err;
    }
  }
}

async function rollbackRestore(targetDb: string, tempDb: string, beforeDb: string, movedCurrent: boolean) {
  try { await stopBackend(); } catch {}
  try { await unlink(tempDb); } catch {}
  if (movedCurrent) {
    try { await unlink(targetDb); } catch {}
    try { await rename(beforeDb, targetDb); } catch {}
  }
  try {
    const oldUrl = await startBackend(currentHost());
    backendUrl = oldUrl;
    await initHealthAgent(oldUrl);
    if (window && !window.isDestroyed()) await window.loadURL(oldUrl);
  } catch {}
}

function safeFilename(value: unknown) {
  const filename = typeof value === "string" ? value : "";
  if (!filename || basename(filename) !== filename || filename.includes("/") || filename.includes("\\") || filename.includes("..")) {
    throw new Error("备份文件名不合法");
  }
  if (!filename.toLowerCase().endsWith(".db")) throw new Error("只能选择 .db 备份文件");
  return filename;
}

function safeResolveInDirectory(directory: string, filename: string) {
  const resolvedDirectory = resolve(directory);
  const resolvedPath = resolve(resolvedDirectory, filename);
  if (dirname(resolvedPath) !== resolvedDirectory) throw new Error("备份文件不在备份目录内");
  return resolvedPath;
}

function parseApiError(text: string) {
  try {
    const detail = JSON.parse(text).detail;
    if (Array.isArray(detail)) return detail.map((item) => item.msg || JSON.stringify(item)).join("；");
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  } catch { return text; }
}

app.on("before-quit", () => { quitting = true; void stopBackend(); });
app.whenReady().then(async () => {
  await loadDeploySettings();
  createTray();
  if (process.argv.includes("--background")) {
    backendUrl = await startBackend(currentHost());
    await initHealthAgent(backendUrl);
  } else {
    await createWindow();
  }
}).catch((error) => {
  console.error(error);
  app.quit();
});
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
app.on("activate", () => { void showOrCreateWindow(); });
