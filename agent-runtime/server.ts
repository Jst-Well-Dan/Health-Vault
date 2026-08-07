import { createHmac } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { HealthAgent } from "./health-agent.js";

type Json = Record<string, unknown>;

const port = Number(process.env.HEALTH_AGENT_PORT || 8123);
const apiUrl = required("HEALTH_API_URL");
const secret = required("HEALTH_AGENT_SECRET");
const dataHome = required("HEALTH_AGENT_DATA_HOME");
const clients = new Set<ServerResponse>();

function required(name: string) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function emit(event: unknown) {
  const payload = `data: ${JSON.stringify(event)}\n\n`;
  for (const client of clients) {
    try { client.write(payload); } catch { clients.delete(client); }
  }
}

const agent = new HealthAgent(
  apiUrl,
  join(dataHome, "agent-credentials.json"),
  join(dataHome, "agent-settings.json"),
  join(dataHome, "agent-key.bin"),
  secret,
  emit,
);

function sendJson(response: ServerResponse, status: number, value: unknown) {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  response.end(JSON.stringify(value));
}

async function readJson(request: IncomingMessage): Promise<Json> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 1024 * 1024) throw new Error("请求过大");
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as Json;
}

function authorized(request: IncomingMessage) {
  return request.headers["x-health-agent-secret"] === secret;
}

async function handler(request: IncomingMessage, response: ServerResponse) {
  const url = new URL(request.url || "/", "http://127.0.0.1");
  // Readiness is public only to loopback. The HMAC proves the responder received the secret through process env without disclosing it.
  if (request.method === "GET" && url.pathname === "/health") return sendJson(response, 200, { ok: true, proof: createHmac("sha256", secret).update("health").digest("hex") });
  if (!authorized(request)) return sendJson(response, 403, { detail: "仅允许本地应用代理访问 Agent 服务" });
  if (request.method === "GET" && url.pathname === "/agent/stream") {
    response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive", "X-Accel-Buffering": "no" });
    response.write(": connected\n\n");
    clients.add(response);
    request.once("close", () => clients.delete(response));
    return;
  }
  try {
    const body = request.method === "GET" ? {} : await readJson(request);
    let value: unknown;
    if (request.method === "POST" && url.pathname === "/agent/send") value = await agent.send(String(body.message || ""));
    else if (request.method === "POST" && url.pathname === "/agent/stop") value = agent.stop();
    else if (request.method === "GET" && url.pathname === "/agent/history") value = await agent.history();
    else if (request.method === "GET" && url.pathname === "/agent/settings") value = await agent.getSettings(url.searchParams.get("provider") || undefined);
    else if (request.method === "POST" && url.pathname === "/agent/settings") value = await agent.saveSettings(body as { provider: string; model: string });
    else if (request.method === "POST" && url.pathname === "/agent/login") value = await agent.login(String(body.provider), body.type as "api_key" | "oauth", typeof body.apiKey === "string" ? body.apiKey : undefined);
    else if (request.method === "POST" && url.pathname === "/agent/logout") value = await agent.logout(String(body.provider));
    else if (request.method === "POST" && url.pathname === "/agent/respond") value = agent.respond(String(body.id), body.value);
    else if (request.method === "POST" && url.pathname === "/report/analyze") value = await agent.analyzeReport(body.source as any, body.member as any);
    else return sendJson(response, 404, { detail: "未知 Agent 路由" });
    sendJson(response, 200, value ?? { ok: true });
  } catch (error) {
    sendJson(response, 400, { detail: error instanceof Error ? error.message : String(error) });
  }
}

await mkdir(dataHome, { recursive: true });
await agent.init();
const server = createServer((request, response) => { void handler(request, response); });
server.listen(port, "127.0.0.1", () => console.log(`Health Agent runtime listening on ${port}`));
for (const signal of ["SIGINT", "SIGTERM"] as const) process.on(signal, () => server.close(() => process.exit(0)));
