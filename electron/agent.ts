import { randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { Agent, type AgentTool, type BeforeToolCallContext } from "@earendil-works/pi-agent-core";
import {
  type AuthEvent,
  type AuthPrompt,
  type Credential,
  type CredentialInfo,
  type CredentialStore,
  type ModelsStore,
  type ModelsStoreEntry,
} from "@earendil-works/pi-ai";
import { builtinModels } from "@earendil-works/pi-ai/providers/all";
import { Type, type TSchema } from "typebox";
import { safeStorage, type WebContents } from "electron";

type Json = Record<string, any>;
type Settings = { provider: string; model: string; source?: "pi" | "desktop" };
type PendingChange = { table_name: string; row_id?: string | number; action: "create" | "update" | "delete"; before?: Json };
type ReportSource = { filename: string; text?: string; images?: Array<{ data: string; mime_type: string }> };
type ReportMember = { key: string; name: string };

const SYSTEM_PROMPT = `你是家庭健康档案助手。只根据工具返回的数据回答，不得编造健康记录。
读取操作可以直接执行。任何新增、修改、删除都必须调用对应工具，应用会先向用户展示字段 before/after 并取得确认。
信息不足时先询问，尤其是成员、日期、剂量、化验单位和参考范围。不要给出诊断，紧急情况建议联系医生。`;

class PiModelsStore implements ModelsStore {
  constructor(private readonly path: string) {}

  async read(providerId: string): Promise<ModelsStoreEntry | undefined> {
    try {
      const values = JSON.parse(await readFile(this.path, "utf8")) as Record<string, ModelsStoreEntry>;
      const entry = values[providerId];
      return entry && Array.isArray(entry.models) ? entry : undefined;
    } catch { return undefined; }
  }

  // The desktop app only reads Pi's model cache; it must not alter Pi configuration.
  async write(_providerId: string, _entry: ModelsStoreEntry): Promise<void> {}
  async delete(_providerId: string): Promise<void> {}
}

class EncryptedCredentialStore implements CredentialStore {
  private values: Record<string, Credential> = {};
  constructor(private readonly path: string) {}

  async load() {
    try {
      const stored = await readFile(this.path, "utf8");
      const [mode, payload] = stored.split(":", 2);
      const raw = mode === "safe"
        ? safeStorage.decryptString(Buffer.from(payload, "base64"))
        : Buffer.from(payload, "base64").toString("utf8");
      this.values = JSON.parse(raw);
    } catch { this.values = {}; }
  }
  async read(providerId: string) { return this.values[providerId]; }
  async list(): Promise<readonly CredentialInfo[]> {
    return Object.entries(this.values).map(([providerId, value]) => ({ providerId, type: value.type }));
  }
  async modify(providerId: string, fn: (current: Credential | undefined) => Promise<Credential | undefined>) {
    const next = await fn(this.values[providerId]);
    if (next) this.values[providerId] = next;
    await this.save();
    return next;
  }
  async delete(providerId: string) { delete this.values[providerId]; await this.save(); }
  private async save() {
    const raw = JSON.stringify(this.values);
    const encoded = safeStorage.isEncryptionAvailable()
      ? `safe:${safeStorage.encryptString(raw).toString("base64")}`
      : `plain:${Buffer.from(raw).toString("base64")}`;
    await writeFile(this.path, encoded, "utf8");
  }
}

export class HealthAgent {
  private readonly models;
  private readonly credentials;
  private agent?: Agent;
  private settings: Settings = { provider: "anthropic", model: "claude-sonnet-4-6" };
  private piDefault?: Pick<Settings, "provider" | "model">;
  private pending = new Map<string, PendingChange>();
  private responseText = "";
  private initialized = false;

  constructor(
    private readonly baseUrl: string,
    private readonly webContents: () => WebContents | undefined,
    credentialPath: string,
    private readonly settingsPath: string,
  ) {
    this.credentials = new EncryptedCredentialStore(credentialPath);
    this.models = builtinModels({
      credentials: this.credentials,
      modelsStore: new PiModelsStore(join(homedir(), ".pi", "agent", "models-store.json")),
    });
  }

  async init() {
    await this.credentials.load();
    await this.syncPiCliCredentials();
    await this.models.refresh({ allowNetwork: false });
    this.piDefault = await this.loadPiDefault();
    let desktopSettings: Settings | undefined;
    try { desktopSettings = JSON.parse(await readFile(this.settingsPath, "utf8")) as Settings; } catch {}
    if (desktopSettings?.source === "desktop" && this.models.getModel(desktopSettings.provider, desktopSettings.model)) {
      this.settings = desktopSettings;
    } else if (this.piDefault && this.models.getModel(this.piDefault.provider, this.piDefault.model)) {
      this.settings = { ...this.piDefault, source: "pi" };
    } else if (desktopSettings && this.models.getModel(desktopSettings.provider, desktopSettings.model)) {
      this.settings = desktopSettings;
    }
    this.createAgent();
    this.initialized = true;
  }

  private async syncPiCliCredentials() {
    try {
      const raw = await readFile(join(homedir(), ".pi", "agent", "auth.json"), "utf8");
      const entries = JSON.parse(raw) as Record<string, Credential>;
      for (const [providerId, credential] of Object.entries(entries)) {
        await this.credentials.modify(providerId, async () => credential);
      }
    } catch {}
  }

  private async loadPiDefault(): Promise<Pick<Settings, "provider" | "model"> | undefined> {
    try {
      const raw = await readFile(join(homedir(), ".pi", "agent", "settings.json"), "utf8");
      const value = JSON.parse(raw) as { defaultProvider?: string; defaultModel?: string };
      if (value.defaultProvider && value.defaultModel) return { provider: value.defaultProvider, model: value.defaultModel };
    } catch {}
    return undefined;
  }

  async getSettings(providerId = this.settings.provider) {
    const configured = await this.credentials.list();
    return {
      ...this.settings,
      piDefault: this.piDefault,
      providers: this.models.getProviders().map((provider) => ({
        id: provider.id,
        name: provider.name,
        auth: [provider.auth.apiKey && "api_key", provider.auth.oauth && "oauth"].filter(Boolean),
        configured: configured.some((item) => item.providerId === provider.id),
      })),
      models: this.models.getModels(providerId).map((model) => ({ id: model.id, name: model.name })),
    };
  }

  async saveSettings(value: Settings) {
    if (!this.models.getModel(value.provider, value.model)) throw new Error("模型不存在");
    this.settings = { ...value, source: "desktop" };
    await writeFile(this.settingsPath, JSON.stringify(this.settings, null, 2), "utf8");
    this.createAgent();
    return this.getSettings();
  }

  async login(provider: string, type: "api_key" | "oauth", apiKey?: string) {
    if (type === "api_key" && apiKey) {
      await this.credentials.modify(provider, async () => ({ type: "api_key", key: apiKey.trim() }));
    } else {
      await this.models.login(provider, type, {
        prompt: (prompt: AuthPrompt) => this.request("auth", prompt),
        notify: (event: AuthEvent) => this.emit({ type: "auth", event }),
      });
    }
    return this.getSettings();
  }

  async logout(provider: string) { await this.models.logout(provider); return this.getSettings(); }

  async history() { return this.api("/api/agent/messages"); }

  async send(message: string) {
    if (!this.initialized) await this.init();
    if (!this.agent) throw new Error("Agent 尚未初始化");
    const text = message.trim();
    if (!text) return;
    if (text === "/undo") return this.undo();
    this.responseText = "";
    await this.api("/api/agent/messages", { method: "POST", body: { role: "user", content: text } });
    await this.agent.prompt(text);
  }

  stop() { this.agent?.abort(); }

  async analyzeReport(source: ReportSource, member: ReportMember) {
    const model = this.models.getModel(this.settings.provider, this.settings.model);
    if (!model) throw new Error("请先在健康助手设置中配置可用模型");
    const images = source.images || [];
    if (images.length && !model.input.includes("image")) {
      throw new Error("当前模型不支持图片识别；请在健康助手设置中选择支持视觉输入的模型");
    }
    const text = [
      "你是健康报告信息提取器。请仅从提供的报告内容提取字段，无法确定时使用 null、[] 或 unknown，绝不猜测。",
      "这是一份私密健康报告；输出必须是纯 JSON，不要使用 Markdown 代码块或解释。",
      `成员已由用户确认：${member.name}（${member.key}）。不要输出 member_key。`,
      "JSON 必须符合：{visit:{date:'YYYY-MM-DD',type:'体检'|'就医'|'复查'|'疫苗'|string,hospital:null|string,department:null|string,doctor:null|string,chief_complaint:null|string,severity:null|'严重'|'一般'|'轻微',diagnosis:string[],notes:null|string,note_full:null|string},labs:[{panel:string,test_name:string,value:null|string,unit:null|string,ref_low:null|string,ref_high:null|string,status:'normal'|'high'|'low'|'abnormal'|'unknown'}],attachment_title:null|string,attachment_tag:'体检报告'|string}。",
      "只录入报告明确列出的本次指标；不要把历史趋势、推测或未经明确参考范围支持的判断当作化验结果。",
      source.text ? `PDF 可提取文本如下：\n${source.text.slice(0, 12000)}` : "报告没有可提取文本，请仔细阅读图片。",
    ].join("\n\n");
    const response = await this.models.complete(model, {
      messages: [{
        role: "user",
        content: [{ type: "text", text }, ...images.map((image) => ({ type: "image" as const, data: image.data, mimeType: image.mime_type }))],
        timestamp: Date.now(),
      }],
    });
    const raw = response.content.map((item) => item.type === "text" ? item.text : "").join("").trim();
    if (!raw) throw new Error(response.errorMessage || "模型没有返回报告解析结果");
    try {
      return JSON.parse(raw.replace(/^```(?:json)?\s*|\s*```$/g, ""));
    } catch {
      throw new Error("模型返回的报告解析格式无效，请重试或换用其他模型");
    }
  }

  respond(id: string, value: unknown) {
    const callback = this.responses.get(id);
    if (callback) { this.responses.delete(id); callback(value); }
  }

  private createAgent() {
    const model = this.models.getModel(this.settings.provider, this.settings.model);
    if (!model) { this.agent = undefined; return; }
    this.agent = new Agent({
      initialState: { systemPrompt: SYSTEM_PROMPT, model, tools: this.tools() },
      streamFn: this.models.streamSimple.bind(this.models),
      toolExecution: "sequential",
      beforeToolCall: (context) => this.confirmWrite(context),
    });
    this.agent.subscribe(async (event) => {
      if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
        this.responseText += event.assistantMessageEvent.delta;
        this.emit({ type: "delta", text: event.assistantMessageEvent.delta });
      }
      if (event.type === "agent_end") {
        if (this.responseText.trim()) {
          await this.api("/api/agent/messages", { method: "POST", body: { role: "assistant", content: this.responseText } });
        }
        this.emit({ type: "done", error: this.agent?.state.errorMessage });
      }
    });
  }

  private async confirmWrite(context: BeforeToolCallContext) {
    const spec = WRITE_SPECS[context.toolCall.name];
    if (!spec) return;
    const args = context.args as Json;
    const rowId = spec.id?.(args);
    const before = rowId === undefined ? undefined : await this.api(`/api/agent/records/${spec.table}/${encodeURIComponent(rowId)}`);
    const approved = await this.request("approval", {
      tool: context.toolCall.name,
      before: before || null,
      after: spec.action === "delete" ? null : { ...(before || {}), ...spec.body(args) },
    });
    if (!approved) return { block: true, reason: "用户拒绝了这次改动" };
    this.pending.set(context.toolCall.id, { table_name: spec.table, row_id: rowId, action: spec.action, before });
  }

  private tools(): AgentTool[] {
    const read = (name: string, description: string, parameters: TSchema, path: (a: Json) => string) => tool(name, description, parameters, async (_id, args) => this.api(path(args)));
    const write = (name: string, description: string, parameters: TSchema, method: string, path: (a: Json) => string, body: (a: Json) => Json = (a) => a) =>
      tool(name, description, parameters, async (callId, args) => {
        const result = await this.api(path(args), { method, body: method === "DELETE" ? undefined : body(args) });
        const change = this.pending.get(callId);
        if (change) {
          const rowId = change.row_id ?? result.id ?? result.key;
          await this.api("/api/agent/changes", { method: "POST", body: { tool: name, ...change, row_id: rowId, after: change.action === "delete" ? null : result } });
          this.pending.delete(callId);
        }
        this.emit({ type: "data-changed" });
        return result;
      });

    const member = Type.Object({ member: Type.String() });
    const id = Type.Object({ id: Type.Integer() });
    return [
      read("get_members", "列出家庭成员和宠物", Type.Object({}), () => "/api/members"),
      read("get_visits", "列出成员的就诊记录", Type.Object({ member: Type.String(), limit: Type.Optional(Type.Integer()) }), (a) => `/api/visits?member=${q(a.member)}&limit=${a.limit || 20}`),
      read("get_visit_detail", "读取一次就诊的完整详情", id, (a) => `/api/visits/${a.id}`),
      read("get_labs", "读取成员化验结果", Type.Object({ member: Type.String(), panel: Type.Optional(Type.String()) }), (a) => `/api/labs?member=${q(a.member)}${a.panel ? `&panel=${q(a.panel)}` : ""}`),
      read("get_lab_trend", "读取某个化验指标趋势", Type.Object({ member: Type.String(), test_name: Type.String() }), (a) => `/api/labs/trend?member=${q(a.member)}&test_name=${q(a.test_name)}`),
      read("get_meds", "读取成员用药", member, (a) => `/api/meds?member=${q(a.member)}`),
      read("get_weight", "读取成员体重", member, (a) => `/api/weight?member=${q(a.member)}`),
      read("get_reminders", "读取提醒", Type.Object({ member: Type.Optional(Type.String()), include_done: Type.Optional(Type.Boolean()) }), (a) => `/api/reminders?${a.member ? `member=${q(a.member)}&` : ""}include_done=${Boolean(a.include_done)}`),
      read("get_attachments", "读取成员附件元数据", member, (a) => `/api/attachments?member=${q(a.member)}`),
      read("read_attachment_text", "读取文本类附件内容", id, (a) => `/api/attachments/${a.id}/text`),
      read("get_activity", "读取首页最近动态", Type.Object({}), () => "/api/activity"),
      write("update_member", "修改成员资料", Type.Object({ key: Type.String(), changes: Type.Record(Type.String(), Type.Unknown()) }), "PATCH", (a) => `/api/members/${q(a.key)}`, (a) => a.changes),
      write("add_visit", "新增就诊记录", Type.Object({ data: Type.Record(Type.String(), Type.Unknown()) }), "POST", () => "/api/visits", (a) => a.data),
      write("update_visit", "修改就诊记录", Type.Object({ id: Type.Integer(), changes: Type.Record(Type.String(), Type.Unknown()) }), "PATCH", (a) => `/api/visits/${a.id}`, (a) => a.changes),
      write("delete_visit", "删除无关联项的就诊记录", id, "DELETE", (a) => `/api/visits/${a.id}`),
      write("add_lab", "新增化验结果", Type.Object({ data: Type.Record(Type.String(), Type.Unknown()) }), "POST", () => "/api/labs", (a) => a.data),
      write("update_lab", "修改化验结果", Type.Object({ id: Type.Integer(), changes: Type.Record(Type.String(), Type.Unknown()) }), "PATCH", (a) => `/api/labs/${a.id}`, (a) => a.changes),
      write("delete_lab", "删除化验结果", id, "DELETE", (a) => `/api/labs/${a.id}`),
      write("add_med", "新增用药", Type.Object({ data: Type.Record(Type.String(), Type.Unknown()) }), "POST", () => "/api/meds", (a) => a.data),
      write("update_med", "修改用药", Type.Object({ id: Type.Integer(), changes: Type.Record(Type.String(), Type.Unknown()) }), "PATCH", (a) => `/api/meds/${a.id}`, (a) => a.changes),
      write("delete_med", "删除用药", id, "DELETE", (a) => `/api/meds/${a.id}`),
      write("add_weight", "新增体重", Type.Object({ data: Type.Record(Type.String(), Type.Unknown()) }), "POST", () => "/api/weight", (a) => a.data),
      write("delete_weight", "删除体重", id, "DELETE", (a) => `/api/weight/${a.id}`),
      write("add_reminder", "新增提醒", Type.Object({ data: Type.Record(Type.String(), Type.Unknown()) }), "POST", () => "/api/reminders", (a) => a.data),
      write("update_reminder", "修改提醒", Type.Object({ id: Type.Integer(), changes: Type.Record(Type.String(), Type.Unknown()) }), "PATCH", (a) => `/api/reminders/${a.id}`, (a) => a.changes),
      write("delete_reminder", "删除提醒", id, "DELETE", (a) => `/api/reminders/${a.id}`),
      write("skip_reminder", "跳过自动提醒", id, "POST", (a) => `/api/reminders/${a.id}/skip`, () => ({})),
      write("add_attachment", "新增已落盘附件的元数据", Type.Object({ data: Type.Record(Type.String(), Type.Unknown()) }), "POST", () => "/api/attachments", (a) => a.data),
      write("update_attachment", "修改附件元数据或关联就诊", Type.Object({ id: Type.Integer(), changes: Type.Record(Type.String(), Type.Unknown()) }), "PATCH", (a) => `/api/attachments/${a.id}`, (a) => a.changes),
      write("delete_attachment", "删除附件元数据（不删除文件）", id, "DELETE", (a) => `/api/attachments/${a.id}`),
    ];
  }

  private async undo() {
    const approved = await this.request("approval", { tool: "undo", before: null, after: { action: "撤销最近一次 agent 改动" } });
    if (!approved) return;
    const result = await this.api("/api/agent/undo", { method: "POST", body: {} });
    this.emit({ type: "data-changed" });
    this.emit({ type: "delta", text: `已撤销 ${result.tool}。` });
    this.emit({ type: "done" });
  }

  private async api(path: string, options: { method?: string; body?: unknown } = {}) {
    const response = await fetch(this.baseUrl + path, {
      method: options.method || "GET",
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const text = await response.text();
    if (!response.ok) throw new Error(parseError(text) || `${response.status} ${response.statusText}`);
    try { return JSON.parse(text); } catch { return text; }
  }

  private emit(value: unknown) { this.webContents()?.send("agent:event", value); }
  private responses = new Map<string, (value: any) => void>();
  private request(kind: string, payload: AuthPrompt | Json): Promise<any> {
    const id = randomUUID();
    this.emit({ type: "request", kind, id, payload });
    return new Promise((resolve) => this.responses.set(id, resolve));
  }
}

const WRITE_SPECS: Record<string, { table: string; action: PendingChange["action"]; id?: (a: Json) => string | number; body: (a: Json) => Json }> = {
  update_member: { table: "members", action: "update", id: (a) => a.key, body: (a) => a.changes },
  add_visit: { table: "visits", action: "create", body: (a) => a.data },
  update_visit: { table: "visits", action: "update", id: (a) => a.id, body: (a) => a.changes },
  delete_visit: { table: "visits", action: "delete", id: (a) => a.id, body: () => ({}) },
  add_lab: { table: "lab_results", action: "create", body: (a) => a.data },
  update_lab: { table: "lab_results", action: "update", id: (a) => a.id, body: (a) => a.changes },
  delete_lab: { table: "lab_results", action: "delete", id: (a) => a.id, body: () => ({}) },
  add_med: { table: "meds", action: "create", body: (a) => a.data },
  update_med: { table: "meds", action: "update", id: (a) => a.id, body: (a) => a.changes },
  delete_med: { table: "meds", action: "delete", id: (a) => a.id, body: () => ({}) },
  add_weight: { table: "weight_log", action: "create", body: (a) => a.data },
  delete_weight: { table: "weight_log", action: "delete", id: (a) => a.id, body: () => ({}) },
  add_reminder: { table: "reminders", action: "create", body: (a) => a.data },
  update_reminder: { table: "reminders", action: "update", id: (a) => a.id, body: (a) => a.changes },
  delete_reminder: { table: "reminders", action: "delete", id: (a) => a.id, body: () => ({}) },
  skip_reminder: { table: "reminders", action: "update", id: (a) => a.id, body: () => ({ done: true }) },
  add_attachment: { table: "attachments", action: "create", body: (a) => a.data },
  update_attachment: { table: "attachments", action: "update", id: (a) => a.id, body: (a) => a.changes },
  delete_attachment: { table: "attachments", action: "delete", id: (a) => a.id, body: () => ({}) },
};

function tool(name: string, description: string, parameters: TSchema, execute: (id: string, args: Json) => Promise<unknown>): AgentTool {
  return {
    name, label: name, description, parameters,
    execute: async (id, args) => {
      const details = await execute(id, args as Json);
      return { content: [{ type: "text", text: JSON.stringify(details, null, 2) }], details };
    },
  };
}
const q = (value: unknown) => encodeURIComponent(String(value));
const parseError = (text: string) => { try { return JSON.parse(text).detail; } catch { return text; } };
