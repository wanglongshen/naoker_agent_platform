import { describe, expect, it } from "vitest";
import { agentLoopSourceParity } from "./source-parity-manifest";

describe("sourceParityManifest", () => {
  it("records every copied Agent Loop Session source and only approved adaptations", () => {
    expect(agentLoopSourceParity.length).toBeGreaterThanOrEqual(9);
    for (const entry of agentLoopSourceParity) {
      expect(entry.copiedBeforeAdaptation).toBe(true);
      expect(entry.source).toContain("X:\\01_agent_loop");
      const allowed = ["import", "API envelope", "UUID", "ownership", "Cookie/CSRF", "succeeded", "attachment IDs", "/agent", "terminal refresh", "safe markdown"];
      expect(entry.adaptations.every((item) => allowed.some((a) => item.includes(a)))).toBe(true);
    }
  });
});
