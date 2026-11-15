import { describe, expect, it } from "vitest";
import { GET, POST } from "@/app/api/copilotkit/[[...slug]]/route";

// The installed runtime, built exactly as the route builds it, called with no cookie or Authorization.
const call = (handler: typeof GET, path: string, method = "GET") =>
  handler(new Request(`http://localhost/api/copilotkit${path}`, { method }));

describe("/api/copilotkit", () => {
  it("serves info", async () => {
    expect((await call(GET, "/info")).status).toBe(200);
  });

  it.each([
    ["GET", "/threads"],
    ["GET", "/threads/t1/events"],
    ["GET", "/threads/t1/messages"],
    ["POST", "/threads/clear"],
  ])("404s %s %s", async (method, path) => {
    const handler = method === "GET" ? GET : POST;
    expect((await call(handler, path, method)).status).toBe(404);
  });
});
