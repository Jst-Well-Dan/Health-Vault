const { contextBridge, ipcRenderer } = require("electron") as typeof import("electron");

contextBridge.exposeInMainWorld("healthReport", {
  select: () => ipcRenderer.invoke("report:select"),
  analyze: (source: unknown, member: unknown) => ipcRenderer.invoke("report:analyze", source, member),
  dryRun: (proposal: unknown) => ipcRenderer.invoke("report:dry-run", proposal),
  commit: (proposal: unknown) => ipcRenderer.invoke("report:commit", proposal),
});

contextBridge.exposeInMainWorld("healthBackup", {
  info: () => ipcRenderer.invoke("backup:info"),
  create: () => ipcRenderer.invoke("backup:create"),
  validate: (filename: string) => ipcRenderer.invoke("backup:validate", filename),
  prepareRestore: (filename: string) => ipcRenderer.invoke("backup:prepare-restore", filename),
  restore: (filename: string) => ipcRenderer.invoke("backup:restore", filename),
  openFolder: () => ipcRenderer.invoke("backup:open-folder"),
});

contextBridge.exposeInMainWorld("healthAttachment", {
  select: () => ipcRenderer.invoke("attachment:select"),
  upload: (metadata: unknown) => ipcRenderer.invoke("attachment:upload", metadata),
});

contextBridge.exposeInMainWorld("healthDeploy", {
  status: () => ipcRenderer.invoke("deploy:status"),
  setBackground: (enabled: boolean) => ipcRenderer.invoke("deploy:set-background", enabled),
  setAutostart: (enabled: boolean) => ipcRenderer.invoke("deploy:set-autostart", enabled),
  checkTailscale: () => ipcRenderer.invoke("deploy:check-tailscale"),
});

contextBridge.exposeInMainWorld("healthAgent", {
  send: (message: string) => ipcRenderer.invoke("agent:send", message),
  stop: () => ipcRenderer.invoke("agent:stop"),
  getHistory: () => ipcRenderer.invoke("agent:history"),
  getSettings: (provider?: string) => ipcRenderer.invoke("agent:settings", provider),
  saveSettings: (settings: unknown) => ipcRenderer.invoke("agent:save-settings", settings),
  login: (provider: string, type: "api_key" | "oauth", apiKey?: string) =>
    ipcRenderer.invoke("agent:login", { provider, type, apiKey }),
  logout: (provider: string) => ipcRenderer.invoke("agent:logout", provider),
  respond: (id: string, value: unknown) => ipcRenderer.send("agent:response", { id, value }),
  onEvent: (callback: (event: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, value: unknown) => callback(value);
    ipcRenderer.on("agent:event", listener);
    return () => ipcRenderer.removeListener("agent:event", listener);
  },
});
