import {
  CopilotRuntime,
  createCopilotRuntimeHandler,
  InMemoryAgentRunner,
} from "@copilotkit/runtime/v2";
import { HttpAgent } from "@ag-ui/client";

// The backend's AG-UI endpoint (FastAPI + LangGraphAGUIAgent).
// In docker compose this is http://backend:8000/agent.
const AGENT_URL = process.env.AGENT_URL || "http://localhost:8000/agent";
// Sangam Import is a second graph on the same backend. One env var still
// configures both: the importer hangs off /ingest where Ask hangs off /agent.
const INGEST_URL = AGENT_URL.replace(/\/agent$/, "/ingest");

const runtime = new CopilotRuntime({
  agents: {
    sangam_agent: new HttpAgent({ url: AGENT_URL }),
    sangam_ingest: new HttpAgent({ url: INGEST_URL }),
  },
  runner: new InMemoryAgentRunner(),
});

// The runtime also serves its in-memory store of every thread (threads/*, memories/*, inspector/*) to any
// caller. Sangam reads history from the backend's /api/threads, so only what the chat client calls is served.
const SERVED = new Set(["info", "agent/run", "agent/connect", "agent/stop", "agent/suggest"]);

const handler = createCopilotRuntimeHandler({
  runtime,
  basePath: "/api/copilotkit",
  hooks: {
    onBeforeHandler: ({ route }) => {
      if (!SERVED.has(route.method)) throw new Response("Not found", { status: 404 });
    },
  },
});

// An Import turn streams for 15–20 minutes; must match backend/vercel.json (Pro's extended-duration beta).
export const maxDuration = 1800;

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const DELETE = handler;
