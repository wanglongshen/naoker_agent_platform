interface PerfState {
  firstEventAt: number;
  eventCount: number;
  frameCount: number;
  reconnectCount: number;
  lastAnswerLen: number;
  connStart: number;
}

interface Window {
  __perf?: PerfState;
}
