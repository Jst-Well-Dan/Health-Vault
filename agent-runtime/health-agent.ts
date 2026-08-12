import { createCipheriv, createDecipheriv, randomBytes, randomUUID } from "node:crypto";
import { chmod, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import {
  AgentHarness,
  DEFAULT_COMPACTION_SETTINGS,
  estimateContextTokens,
  JsonlSessionStorage,
  Session,
  shouldCompact,
  type AgentHarnessTool,
  type ToolCallEvent,
} from "@earendil-works/pi-agent-core";
import { NodeExecutionEnv } from "@earendil-works/pi-agent-core/node";
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
  private key?: Buffer;
  constructor(private readonly path: string, private readonly keyPath: string) {}

  async load() {
    try {
      const stored = JSON.parse(await readFile(this.path, "utf8")) as { iv: string; tag: string; ciphertext: string };
      const decipher = createDecipheriv("aes-256-gcm", await this.encryptionKey(), Buffer.from(stored.iv, "base64"));
      decipher.setAuthTag(Buffer.from(stored.tag, "base64"));
      this.values = JSON.parse(Buffer.concat([decipher.update(Buffer.from(stored.ciphertext, "base64")), decipher.final()]).toString("utf8"));
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
  private async encryptionKey() {
    if (this.key) return this.key;
    try {
      const key = await readFile(this.keyPath);
      if (key.length !== 32) throw new Error("invalid key length");
      this.key = key;
    } catch {
      this.key = randomBytes(32);
      await writeFile(this.keyPath, this.key, { mode: 0o600 });
      await chmod(this.keyPath, 0o600).catch(() => undefined);
    }
    return this.key;
  }
  private async save() {
    const iv = randomBytes(12);
    const cipher = createCipheriv("aes-256-gcm", await this.encryptionKey(), iv);
    const ciphertext = Buffer.concat([cipher.update(JSON.stringify(this.values), "utf8"), cipher.final()]);
    await writeFile(this.path, JSON.stringify({ iv: iv.toString("base64"), tag: cipher.getAuthTag().toString("base64"), ciphertext: ciphertext.toString("base64") }), { encoding: "utf8", mode: 0o600 });
    await chmod(this.path, 0o600).catch(() => undefined);
  }
}

export class HealthAgent {
  private readonly models;
  private readonly credentials;
  private agent?: AgentHarness;
  private session?: Session;
  private sessionEnv?: NodeExecutionEnv;
  private settings: Settings = { provider: "anthropic", model: "claude-sonnet-4-6" };
  private piDefault?: Pick<Settings, "provider" | "model">;
  private pending = new Map<string, PendingChange>();
  private responseText = "";
  private initialized = false;

  constructor(
    private readonly baseUrl: string,
    credentialPath: string,
    private readonly settingsPath: string,
    keyPath: string,
    private readonly runtimeSecret: string,
    private readonly emitEvent: (value: unknown) => void,
  ) {
    this.credentials = new EncryptedCredentialStore(credentialPath, keyPath);
    this.models = builtinModels({
      credentials: this.credentials,
      modelsStore: new PiModelsStore(join(homedir(), ".pi", "agent", "models-store.json")),
    });
  }

  async init() {
    await this.credentials.load();
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
    await this.openSession();
    this.createAgent();
    this.initialized = true;
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
    await this.maybeCompact();
    this.responseText = "";
    await this.api("/api/agent/messages", { method: "POST", body: { role: "user", content: text } });
    await this.agent.prompt(text);
  }

  private async maybeCompact() {
    if (!this.agent || !this.session) return;
    const model = this.models.getModel(this.settings.provider, this.settings.model);
    if (!model) return;
    const { messages } = await this.session.buildContext();
    const { tokens } = estimateContextTokens(messages);
    if (!shouldCompact(tokens, model.contextWindow, DEFAULT_COMPACTION_SETTINGS)) return;
    try {
      await this.agent.compact();
      this.emit({ type: "notice", text: "对话较长，已自动整理更早的历史记录以节省上下文。" });
    } catch (err) {
      this.emit({ type: "notice", text: `自动整理历史失败：${(err as Error).message}` });
    }
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
      "另外输出 patient_name_on_report 字段：如实抄录报告上写明的患者/受检者姓名（若有），用于核对是否与上面确认的成员一致；报告没有写姓名就填 null，绝不要猜测或套用成员姓名。",
      "JSON 必须符合：{patient_name_on_report:null|string,visit:{date:'YYYY-MM-DD',type:'体检'|'就医'|'复查'|'疫苗'|string,hospital:null|string,department:null|string,doctor:null|string,chief_complaint:null|string,severity:null|'严重'|'一般'|'轻微',diagnosis:string[],notes:null|string,note_full:null|string},labs:[{panel:string,test_name:string,value:null|string,unit:null|string,ref_low:null|string,ref_high:null|string,status:'normal'|'high'|'low'|'abnormal'|'unknown'}],attachment_title:null|string,attachment_tag:'体检报告'|string}。",
      "只录入报告明确列出的本次指标；不要把历史趋势、推测或未经明确参考范围支持的判断当作化验结果。",
      source.text ? `以下是 MinerU 从原始报告转换的 Markdown，请只根据其中明确内容提取：\n${source.text.slice(0, 100000)}` : "报告缺少 MinerU Markdown，无法解析。",
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

  private async openSession(fresh = false) {
    const userDataPath = dirname(this.settingsPath);
    const sessionPath = join(userDataPath, "sessions", "default.jsonl");
    this.sessionEnv = new NodeExecutionEnv({ cwd: userDataPath });
    const exists = await this.sessionEnv.exists(sessionPath);
    if (!exists.ok) throw exists.error;
    const storage = !fresh && exists.value
      ? await JsonlSessionStorage.open(this.sessionEnv, sessionPath)
      : await JsonlSessionStorage.create(this.sessionEnv, sessionPath, {
        cwd: userDataPath,
        sessionId: "default",
      });
    this.session = new Session(storage);
  }

  async resetContext() {
    this.responseText = "";
    this.pending.clear();
    this.agent?.abort();
    await this.api("/api/agent/messages", { method: "DELETE" });
    await this.openSession(true);
    this.createAgent();
    this.emit({ type: "reset" });
    return { ok: true };
  }

  private createAgent() {
    const model = this.models.getModel(this.settings.provider, this.settings.model);
    if (!model || !this.session) { this.agent = undefined; return; }
    const harness = new AgentHarness({
      session: this.session,
      models: this.models,
      systemPrompt: SYSTEM_PROMPT,
      model,
      tools: this.tools(),
    });
    harness.on("tool_call", (event) => this.confirmWrite(event));
    harness.subscribe(async (event) => {
      if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
        this.responseText += event.assistantMessageEvent.delta;
        this.emit({ type: "delta", text: event.assistantMessageEvent.delta });
      }
      if (event.type === "agent_end") {
        if (this.responseText.trim()) {
          await this.api("/api/agent/messages", { method: "POST", body: { role: "assistant", content: this.responseText } });
        }
        const failedMessage = event.messages.find((message) => message.role === "assistant" && "errorMessage" in message);
        const error = failedMessage && "errorMessage" in failedMessage ? failedMessage.errorMessage : undefined;
        this.emit({ type: "done", error });
      }
    });
    this.agent = harness;
  }

  private async confirmWrite(context: ToolCallEvent) {
    const spec = WRITE_SPECS[context.toolName];
    if (!spec) return;
    const args = context.input as Json;
    const rowId = spec.id?.(args);
    const before = rowId === undefined ? undefined : await this.api(`/api/agent/records/${spec.table}/${encodeURIComponent(rowId)}`);
    const approved = await this.request("approval", {
      tool: context.toolName,
      before: before || null,
      after: spec.action === "delete" ? null : { ...(before || {}), ...spec.body(args) },
    });
    if (!approved) return { block: true, reason: "用户拒绝了这次改动" };
    this.pending.set(context.toolCallId, { table_name: spec.table, row_id: rowId, action: spec.action, before });
  }

  private tools(): AgentHarnessTool<undefined>[] {
    const read = (name: string, description: string, parameters: TSchema, path: (a: Json) => string) => tool(name, description, parameters, async (_id, args, _signal, _onUpdate, _context) => this.api(path(args)));
    const write = (name: string, description: string, parameters: TSchema, method: string, path: (a: Json) => string, body: (a: Json) => Json = (a) => a) =>
      tool(name, description, parameters, async (callId, args, _signal, _onUpdate, _context) => {
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
      headers: { ...(options.body === undefined ? {} : { "Content-Type": "application/json" }), "X-Health-Agent-Secret": this.runtimeSecret },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const text = await response.text();
    if (!response.ok) throw new Error(parseError(text) || `${response.status} ${response.statusText}`);
    try { return JSON.parse(text); } catch { return text; }
  }

  private emit(value: unknown) { this.emitEvent(value); }
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

function tool(
  name: string,
  description: string,
  parameters: TSchema,
  execute: (id: string, args: Json, signal: AbortSignal | undefined, onUpdate: unknown, context: undefined) => Promise<unknown>,
): AgentHarnessTool<undefined> {
  return {
    name, label: name, description, parameters,
    execute: async (id, args, signal, onUpdate, context) => {
      const details = await execute(id, args as Json, signal, onUpdate, context);
      return { content: [{ type: "text", text: JSON.stringify(details, null, 2) }], details };
    },
  };
}
const q = (value: unknown) => encodeURIComponent(String(value));
const parseError = (text: string) => { try { return JSON.parse(text).detail; } catch { return text; } };
