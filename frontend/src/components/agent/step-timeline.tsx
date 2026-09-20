import type { AgentStep } from "@/types/agent";

export default function StepTimeline({ steps }: { steps: AgentStep[] }) {
  return (
    <section style={{ marginTop: 24 }}>
      <h2>Steps</h2>
      <div style={{ display: "grid", gap: 12 }}>
        {steps.map((step) => (
          <div key={step.id} style={{ border: "1px solid #ddd", padding: 12, borderRadius: 8 }}>
            <div><strong>Step #{step.step_number}</strong> &middot; {step.action_type} &middot; {step.status}</div>
            <div style={{ marginTop: 8 }}>{step.thought_summary}</div>
            <details style={{ marginTop: 8 }}>
              <summary>Action payload</summary>
              <pre style={{ whiteSpace: "pre-wrap", overflowX: "auto" }}>{JSON.stringify(step.action_payload, null, 2)}</pre>
            </details>
            <details style={{ marginTop: 8 }}>
              <summary>Observation</summary>
              <pre style={{ whiteSpace: "pre-wrap", overflowX: "auto" }}>{JSON.stringify(step.observation, null, 2)}</pre>
            </details>
          </div>
        ))}
      </div>
    </section>
  );
}
