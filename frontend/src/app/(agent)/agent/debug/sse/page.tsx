"use client";

import { useEffect, useRef, useState } from "react";

type EventLog = { seq: number; delay: number; data: string; burst: boolean };

export default function SSEDebugPage() {
  const [logs, setLogs] = useState<EventLog[]>([]);
  const [status, setStatus] = useState("idle");
  const prevTime = useRef<number>(0);
  const firstTime = useRef<number>(0);

  const runTest = () => {
    setLogs([]);
    setStatus("connecting");
    prevTime.current = 0;
    firstTime.current = 0;

    const url = "http://localhost:8000/api/stream-debug";
    const es = new EventSource(url, { withCredentials: true });

    es.onopen = () => setStatus("open");
    es.onerror = () => setStatus("error");

    es.onmessage = (e) => {
      const now = performance.now();
      if (firstTime.current === 0) firstTime.current = now;
      const delay = now - firstTime.current;
      const sincePrev = prevTime.current ? now - prevTime.current : 0;
      const burst = sincePrev < 100;
      prevTime.current = now;

      try {
        const parsed = JSON.parse(e.data);
        setLogs((l) => [...l, { seq: parsed.seq ?? l.length + 1, delay: Math.round(delay), data: parsed.message ?? JSON.stringify(parsed), burst }]);
      } catch {
        setLogs((l) => [...l, { seq: l.length + 1, delay: Math.round(delay), data: e.data, burst }]);
      }
    };

    es.addEventListener("done", () => {
      es.close();
      setStatus("complete");
    });
  };

  return (
    <div style={{ padding: 20, maxWidth: 700, margin: "0 auto", fontFamily: "monospace" }}>
      <h2>SSE Streaming Diagnostic</h2>
      
      <div style={{ margin: "10px 0" }}>
        <label>Run ID: <input id="runId" type="text" defaultValue="00000000-0000-0000-0000-000000000000" style={{ width: 350, marginLeft: 10 }} /></label>
        <button onClick={() => {
          const id = (document.getElementById("runId") as HTMLInputElement).value;
          runTest();
        }} style={{ marginLeft: 10, padding: "6px 14px", cursor: "pointer" }}>
          Start Test
        </button>
      </div>

      <div style={{ margin: "10px 0" }}>
        Status: <strong>{status}</strong>
      </div>

      <div style={{ margin: "10px 0", fontSize: 12, color: "#666" }}>
        Expected: 5 events at ~500ms intervals. If all show 0-100ms → buffering confirmed.
        <br />If intervals are ~500ms → SSE streaming works.
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 10 }}>
        <thead>
          <tr style={{ background: "#f0f0f0" }}>
            <th style={{ padding: 8, textAlign: "left" }}>#</th>
            <th style={{ padding: 8, textAlign: "left" }}>Delay (ms)</th>
            <th style={{ padding: 8, textAlign: "left" }}>Burst?</th>
            <th style={{ padding: 8, textAlign: "left" }}>Data</th>
          </tr>
        </thead>
        <tbody>
          {logs.map((log) => (
            <tr key={log.seq} style={{ background: log.burst ? "#fff3cd" : "transparent", borderBottom: "1px solid #eee" }}>
              <td style={{ padding: 8 }}>{log.seq}</td>
              <td style={{ padding: 8 }}>{log.delay}</td>
              <td style={{ padding: 8 }}>{log.burst ? "⚠️ YES" : "✓ no"}</td>
              <td style={{ padding: 8, fontSize: 12 }}>{log.data}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {logs.length > 0 && (
        <div style={{ marginTop: 15, padding: 10, background: logs.every(l => !l.burst) && logs.length >= 5 ? "#d4edda" : "#f8d7da", borderRadius: 4 }}>
          <strong>Result:</strong>{" "}
          {logs.length < 5
            ? `Only ${logs.length}/5 events received — connection issue`
            : logs.every(l => !l.burst)
              ? "✓ Events arrived at regular intervals — SSE streaming OK"
              : "⚠️ Events arrived in burst — BUFFERING DETECTED"}
        </div>
      )}
    </div>
  );
}
