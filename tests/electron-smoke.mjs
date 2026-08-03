import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const packaged = process.env.HEALTH_ELECTRON_EXE;
const electron = packaged || join(root, "node_modules", "electron", "dist", "electron.exe");
const temp = await mkdtemp(join(tmpdir(), "health-vault-electron-"));
const port = await freePort();
let nextCdpId = 1;
const args = [`--remote-debugging-port=${port}`, `--user-data-dir=${temp}`];
if (!packaged) args.push(".");
const child = spawn(electron, args, {
  cwd: root,
  env: { ...process.env, HEALTH_DB_PATH: join(temp, "health.db"), HEALTH_MOCK_MODE: "1" },
  stdio: "ignore",
});

try {
  const target = await waitForTarget(port);
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolveOpen, reject) => {
    socket.addEventListener("open", resolveOpen, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  const result = await waitForPage(socket);
  const ipc = await evaluate(socket, `(async () => {
    const waitFor = async (predicate, timeout = 4000) => {
      const started = Date.now();
      while (Date.now() - started < timeout) {
        const value = predicate();
        if (value) return value;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      return predicate();
    };
    const settings = await window.healthAgent.getSettings();
    const history = await window.healthAgent.getHistory();
    const backupInfo = await window.healthBackup.info();
    const backupButton = await waitFor(() => Array.from(document.querySelectorAll('button')).find(button => button.textContent?.includes('数据备份')));
    backupButton?.click();
    await waitFor(() => document.body.textContent?.includes('用户可控恢复'));
    const backupPanelText = document.body.textContent || '';
    Array.from(document.querySelectorAll('button')).find(button => button.textContent?.trim() === '关闭')?.click();
    document.querySelectorAll('.screen-tab')[1]?.click();
    const importButton = await waitFor(() => Array.from(document.querySelectorAll('button')).find(button => button.textContent?.includes('上传报告/附件')));
    importButton?.click();
    await new Promise(resolve => setTimeout(resolve, 50));
    const importModal = Boolean(document.querySelector('.report-import-modal'));
    document.querySelector('.report-import-close')?.click();
    Array.from(document.querySelectorAll('.tabs-row .t')).find(tab => tab.textContent?.trim() === '附件库')?.click();
    const attachmentAddButton = await waitFor(() => Array.from(document.querySelectorAll('.member-content button')).find(button => button.textContent?.includes('添加附件')));
    attachmentAddButton?.click();
    await new Promise(resolve => setTimeout(resolve, 50));
    const attachmentUploadModal = document.body.textContent?.includes('添加普通附件');
    Array.from(document.querySelectorAll('button')).find(button => button.textContent?.trim() === '关闭')?.click();
    await new Promise(resolve => setTimeout(resolve, 50));
    const attachmentImportButton = await waitFor(() => Array.from(document.querySelectorAll('.member-content button')).find(button => button.textContent?.includes('上传报告/附件')));
    attachmentImportButton?.click();
    await new Promise(resolve => setTimeout(resolve, 50));
    return {
      providers: settings.providers.length,
      models: settings.models.length,
      history: Array.isArray(history),
      reportBridge: typeof window.healthReport === 'object',
      backupBridge: typeof window.healthBackup === 'object',
      backupRestoreBridge: typeof window.healthBackup.validate === 'function' && typeof window.healthBackup.prepareRestore === 'function' && typeof window.healthBackup.restore === 'function',
      attachmentBridge: typeof window.healthAttachment === 'object',
      backupInfo: typeof backupInfo?.database_path === 'string' && typeof backupInfo?.backup_dir === 'string',
      backupButton: Boolean(backupButton),
      backupRestoreText: backupPanelText.includes('只恢复数据库') && backupPanelText.includes('恢复前会校验备份'),
      attachmentAddButton: Boolean(attachmentAddButton),
      attachmentUploadModal: Boolean(attachmentUploadModal),
      importButton: Boolean(importButton),
      importModal,
      attachmentImportButton: Boolean(attachmentImportButton),
      attachmentImportModal: Boolean(document.querySelector('.report-import-modal')),
    };
  })()`);
  Object.assign(result, ipc);
  if (result.title !== "家庭健康档案" || !result.bridge || result.agentButton !== 1 || !result.rootText || !result.providers || !result.models || !result.history || !result.reportBridge || !result.backupBridge || !result.backupRestoreBridge || !result.attachmentBridge || !result.backupInfo || !result.backupButton || !result.backupRestoreText || !result.attachmentAddButton || !result.attachmentUploadModal || !result.importButton || !result.importModal || !result.attachmentImportButton || !result.attachmentImportModal) {
    throw new Error(`Electron 页面检查失败: ${JSON.stringify(result)}`);
  }
  console.log(JSON.stringify(result));
  socket.send(JSON.stringify({ id: 2, method: "Page.close" }));
  socket.close();
} finally {
  if (child.exitCode === null) {
    await Promise.race([
      new Promise((resolveExit) => child.once("exit", resolveExit)),
      new Promise((resolveWait) => setTimeout(resolveWait, 3000)),
    ]);
  }
  if (child.exitCode === null) {
    child.kill();
    await Promise.race([
      new Promise((resolveExit) => child.once("exit", resolveExit)),
      new Promise((resolveWait) => setTimeout(resolveWait, 3000)),
    ]);
  }
  await rmWithRetries(temp);
}

async function rmWithRetries(path) {
  for (let attempt = 0; attempt < 8; attempt++) {
    try {
      await rm(path, { recursive: true, force: true });
      return;
    } catch (err) {
      if (!['EBUSY', 'ENOTEMPTY', 'EPERM'].includes(err?.code) || attempt === 7) throw err;
      await new Promise((resolveWait) => setTimeout(resolveWait, 250 * (attempt + 1)));
    }
  }
}

async function waitForPage(socket) {
  for (let attempt = 0; attempt < 80; attempt++) {
    const result = await evaluate(socket, `({
      title: document.title,
      bridge: typeof window.healthAgent === 'object',
      agentButton: document.querySelectorAll('.agent-fab').length,
      rootText: document.querySelector('#root')?.textContent?.includes('家庭健康档案')
    })`);
    if (result.title && result.agentButton) return result;
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error("Electron 页面渲染超时");
}

function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => typeof address === "object" && address ? resolvePort(address.port) : reject(new Error("无可用端口")));
    });
  });
}

async function waitForTarget(port) {
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = targets.find((item) => item.type === "page" && item.url.startsWith("http://127.0.0.1:"));
      if (page) return page;
    } catch {}
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error("Electron 页面启动超时");
}

function evaluate(socket, expression) {
  const id = nextCdpId++;
  socket.send(JSON.stringify({ id, method: "Runtime.evaluate", params: { expression, returnByValue: true, awaitPromise: true } }));
  return new Promise((resolveValue, reject) => {
    const timeout = setTimeout(() => reject(new Error("CDP 检查超时")), 15000);
    socket.addEventListener("message", function listener(event) {
      const message = JSON.parse(event.data);
      if (message.id !== id) return;
      socket.removeEventListener("message", listener);
      clearTimeout(timeout);
      if (message.result?.exceptionDetails) reject(new Error(message.result.exceptionDetails.text));
      else resolveValue(message.result.result.value);
    });
  });
}
