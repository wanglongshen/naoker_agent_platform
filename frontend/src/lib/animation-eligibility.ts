export function isActivelyStreamingRun(status: string, isLiveRun: boolean): boolean {
  return isLiveRun && status === "running";
}
