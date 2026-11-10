import {
  CopilotRuntime,
  createCopilotRuntimeHandler,
  InMemoryAgentRunner,
} from "@copilotkit/runtime/v2";
import { HttpAgent } from "@ag-ui/client";
import { backendOwnerCheck, gateRoute } from "@/lib/copilotkit-access";
import { serverAuthHeaders } from "@/lib/api/auth-headers.server";

// The backend's AG-UI endpoint (FastAPI + LangGraphAGUIAgent).
// In docker compose this is http://backend:8000/agent.
const AGENT_URL = process.env.AGENT_URL || "http://localhost:8000/agent";
// Sangam Import is a second graph on the same backend. One env var still
// configures both: the importer hangs off /ingest where Ask hangs off /agent.
const INGEST_URL = AGENT_URL.replace(/\/agent$/, "/ingest");
// The proposal agent: one shared chat per proposal, beside its steps.
const PROPOSAL_URL = AGENT_URL.replace(/\/agent$/, "/proposal");
// connect and stop ask the backend's REST API whether the caller owns the thread.
const isOwner = backendOwnerCheck(AGENT_URL.replace(/\/agent$/, ""));

const callerAuth = (request: Request) => async () =>
  request.headers.get("authorization") ?? (await serverAuthHeaders()).Authorization;

const runtime = new CopilotRuntime({
  agents: {
    sangam_agent: new HttpAgent({ url: AGENT_URL }),
    sangam_ingest: new HttpAgent({ url: INGEST_URL }),
    sangam_proposal: new HttpAgent({ url: PROPOSAL_URL }),
  },
  runner: new InMemoryAgentRunner(),
});

const handler = createCopilotRuntimeHandler({
  runtime,
  basePath: "/api/copilotkit",
  hooks: {
    // The cookie covers a connect sent before the browser has handed the provider its token.
    onBeforeHandler: ({ route, request }) =>
      gateRoute(route, request, callerAuth(request), isOwner),
  },
});

// An Import turn streams for 15–20 minutes; must match backend/vercel.json (Pro's extended-duration beta).
export const maxDuration = 1800;

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const DELETE = handler;
