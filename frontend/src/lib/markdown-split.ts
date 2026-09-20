export function splitBlocks(text: string): { completed: string[]; active: string } {
  if (!text) return { completed: [], active: "" };

  const completed: string[] = [];
  let inFence = false;
  let fenceChar = "";
  let blockStart = 0;
  let i = 0;

  while (i < text.length) {
    // Check for fence start/end at current position
    if (!inFence) {
      if ((text[i] === "`" && text[i + 1] === "`" && text[i + 2] === "`") ||
          (text[i] === "~" && text[i + 1] === "~" && text[i + 2] === "~")) {
        inFence = true;
        fenceChar = text[i];
        i += 3;
        continue;
      }
    } else {
      if (text[i] === fenceChar && text[i + 1] === fenceChar && text[i + 2] === fenceChar) {
        inFence = false;
        fenceChar = "";
        i += 3;
        continue;
      }
    }

    // Check for block delimiter \n\n outside fences
    if (!inFence && text[i] === "\n" && text[i + 1] === "\n") {
      completed.push(text.slice(blockStart, i));
      i += 2;
      blockStart = i;
      continue;
    }

    i++;
  }

  const active = text.slice(blockStart);
  return { completed, active };
}

export function partitionInline(source: string): { stable: string; tail: string } {
  if (!source) return { stable: "", tail: "" };

  let lastBalanced = 0;
  let boldOpen = false;
  let italicOpen = false;
  let codeOpen = false;
  let linkBracketDepth = 0;
  let linkInParen = false;
  let linkParenCount = 0;
  let strikeOpen = false;
  let escapeActive = false;

  function allClosed(): boolean {
    return !boldOpen && !italicOpen && !codeOpen && linkBracketDepth === 0 && !linkInParen && !strikeOpen;
  }

  for (let i = 0; i < source.length; i++) {
    const ch = source[i];
    const next = source[i + 1] ?? "";
    const lookahead2 = source[i + 2] ?? "";

    if (escapeActive) {
      escapeActive = false;
      continue;
    }

    if (ch === "\\") {
      escapeActive = true;
      continue;
    }

    if (codeOpen) {
      if (ch === "`" && next !== "`") {
        codeOpen = false;
        if (allClosed()) lastBalanced = i + 1;
      }
      continue;
    }

    if (ch === "`") {
      codeOpen = true;
      continue;
    }

    // Bold: ** or __
    if (ch === "*" && next === "*" && lookahead2 !== "*" && !italicOpen) {
      boldOpen = !boldOpen;
      i++; // skip second *
      if (allClosed()) lastBalanced = i + 1;
      continue;
    }
    if (ch === "_" && next === "_" && lookahead2 !== "_" && !italicOpen) {
      boldOpen = !boldOpen;
      i++;
      if (allClosed()) lastBalanced = i + 1;
      continue;
    }

    // Italic: * or _ (not part of bold)
    if (ch === "*" && next !== "*" && !boldOpen) {
      italicOpen = !italicOpen;
      if (allClosed()) lastBalanced = i + 1;
      continue;
    }
    if (ch === "_" && next !== "_" && !boldOpen) {
      italicOpen = !italicOpen;
      if (allClosed()) lastBalanced = i + 1;
      continue;
    }

    // Strikethrough: ~~
    if (ch === "~" && next === "~") {
      strikeOpen = !strikeOpen;
      i++;
      if (allClosed()) lastBalanced = i + 1;
      continue;
    }

    // Link: [text](url)
    if (linkInParen) {
      if (ch === ")") {
        linkParenCount--;
        if (linkParenCount === 0) {
          linkInParen = false;
          if (allClosed()) lastBalanced = i + 1;
        }
      } else if (ch === "(") {
        linkParenCount++;
      }
      continue;
    }

    if (ch === "[") {
      linkBracketDepth++;
      continue;
    }

    if (ch === "]" && linkBracketDepth > 0) {
      if (next === "(") {
        linkBracketDepth--;
        linkInParen = true;
        linkParenCount = 1;
        i++; // skip '('
      } else {
        linkBracketDepth--;
        if (allClosed()) lastBalanced = i + 1;
      }
      continue;
    }

    // Plain text character
    if (allClosed()) lastBalanced = i + 1;
  }

  return {
    stable: source.slice(0, lastBalanced),
    tail: source.slice(lastBalanced),
  };
}

export function fastHash(s: string): number {
  let hash = 2166136261;
  for (let i = 0; i < s.length; i++) {
    hash ^= s.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
