export type TypingAnimationState = {
  displayedText: string;
  remainingMs: number | null;
};

const PUNCTUATION_PAUSE_MS = 60;
export function getTypingAnimationDelayMs(character: string, msPerCharacter: number = 50): number {
  if ([".", "!", "?", ",", ";", ":", "。", "！", "？", "，", "；", "："].includes(character)) {
    return msPerCharacter + PUNCTUATION_PAUSE_MS;
  }
  return msPerCharacter;
}

export function createTypingAnimationState(): TypingAnimationState {
  return {
    displayedText: "",
    remainingMs: null,
  };
}

export function advanceTypingAnimation(
  state: TypingAnimationState,
  targetText: string,
  elapsedMs: number,
  msPerCharacter: number,
): TypingAnimationState {
  if (!targetText) {
    return createTypingAnimationState();
  }

  const previousText = state.displayedText;
  const targetShrank = !targetText.startsWith(previousText);
  const startingText = targetShrank ? "" : previousText;
  let remainingMs = targetShrank
    ? msPerCharacter
    : state.remainingMs === null ? msPerCharacter : state.remainingMs;
  let displayedCount = startingText.length;
  let budgetMs = Math.max(elapsedMs, 0);

  while (budgetMs >= remainingMs && displayedCount < targetText.length) {
    budgetMs -= remainingMs;
    displayedCount += 1;
    const lastCharacter = targetText.charAt(displayedCount - 1);
    remainingMs = getTypingAnimationDelayMs(lastCharacter, msPerCharacter);
  }

  const displayedText = targetText.slice(0, displayedCount);

  if (displayedText === targetText) {
    return { displayedText, remainingMs: null };
  }

  return { displayedText, remainingMs: remainingMs - budgetMs };
}
