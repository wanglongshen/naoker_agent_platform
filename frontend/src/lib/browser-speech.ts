export type BrowserSpeechController = {
  supported: () => boolean;
  speak: (ownerId: string, text: string, onIdle: () => void, onFailure: () => void) => boolean;
  stop: (ownerId: string) => void;
  reset: () => void;
};

type CurrentEntry = {
  ownerId: string;
  utterance: SpeechSynthesisUtterance;
  onIdle: () => void;
  onFailure: () => void;
};

let current: CurrentEntry | null = null;

function supported(): boolean {
  return (
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    "SpeechSynthesisUtterance" in window
  );
}

function speak(
  ownerId: string,
  text: string,
  onIdle: () => void,
  onFailure: () => void,
): boolean {
  if (!supported()) return false;
  if (!text.trim()) return false;

  // Replace prior utterance
  if (current) {
    const prev = current;
    current = null;
    prev.onIdle();
    try {
      window.speechSynthesis.cancel();
    } catch {
      // speechSynthesis may be unavailable
    }
  }

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";

  const entry: CurrentEntry = { ownerId, utterance, onIdle, onFailure };
  current = entry;

  utterance.onend = () => {
    if (current?.ownerId !== ownerId || current.utterance !== utterance) return;
    current = null;
    onIdle();
  };

  utterance.onerror = () => {
    if (current?.ownerId !== ownerId || current.utterance !== utterance) return;
    current = null;
    onFailure();
    onIdle();
  };

  try {
    window.speechSynthesis.speak(utterance);
  } catch {
    if (current?.ownerId === ownerId && current.utterance === utterance) {
      current = null;
    }
    onFailure();
    onIdle();
    return false;
  }

  return true;
}

function stop(ownerId: string) {
  if (!current || current.ownerId !== ownerId) return;
  const prev = current;
  current = null;
  prev.onIdle();
  try {
    window.speechSynthesis.cancel();
  } catch {
    // speechSynthesis may be unavailable during cleanup
  }
}

function reset() {
  if (current) {
    current = null;
  }
}

export const browserSpeech: BrowserSpeechController = {
  supported,
  speak,
  stop,
  reset,
};
