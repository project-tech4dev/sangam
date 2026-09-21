import {
  CopilotRuntime,
  createCopilotRuntimeHandler,
  InMemoryAgentRunner,
} from "@copilotkit/runtime/v2";
import { HttpAgent } from "@ag-ui/client";

// The backend's AG-UI endpoint (FastAPI + LangGraphAGUIAgent).
// In docker compose this is http://backend:8000/agent.
const runtime = new CopilotRuntime({
  agents: {
    sangam_agent: new HttpAgent({
      url: process.env.AGENT_URL || "http://localhost:8000/agent",
    }),
  },
  runner: new InMemoryAgentRunner(),
});

const handler = createCopilotRuntimeHandler({ runtime, basePath: "/api/copilotkit" });

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const DELETE = handler;
