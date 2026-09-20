import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { browserSpeech } from "@/lib/browser-speech";

type FakeUtterance = {
  text: string;
  lang: string;
  onend: ((event: Event) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
};

let fakeSynthesis: {
  speak: ReturnType<typeof vi.fn>;
  cancel: ReturnType<typeof vi.fn>;
  speaking: boolean;
  pending: boolean;
};
let FakeUtteranceClass: { new (text: string): FakeUtterance };
let utteranceInstances: FakeUtterance[];

function makeFakeSynthesis() {
  utteranceInstances = [];
  fakeSynthesis = {
    speak: vi.fn((utterance: FakeUtterance) => {
      utteranceInstances.push(utterance);
      fakeSynthesis.speaking = true;
      fakeSynthesis.pending = true;
    }),
    cancel: vi.fn(() => {
      fakeSynthesis.speaking = false;
      fakeSynthesis.pending = false;
    }),
    speaking: false,
    pending: false,
  };

  FakeUtteranceClass = class implements FakeUtterance {
    text: string;
    lang: string;
    onend: ((event: Event) => void) | null = null;
    onerror: ((event: { error: string }) => void) | null = null;

    constructor(text: string) {
      this.text = text;
      this.lang = "";
    }
  };

  (window as Window & { speechSynthesis?: unknown }).speechSynthesis = fakeSynthesis;
  (window as Window & { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance = FakeUtteranceClass;
  browserSpeech.reset();
}

function cleanupFakeApis() {
  delete (window as Window & { speechSynthesis?: unknown }).speechSynthesis;
  delete (window as Window & { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance;
  browserSpeech.reset();
  utteranceInstances = [];
}

beforeEach(() => {
  makeFakeSynthesis();
});

afterEach(() => {
  cleanupFakeApis();
});

describe("browserSpeech", () => {
  describe("supported", () => {
    test("returns false when no browser speech APIs exist", () => {
      cleanupFakeApis();
      expect(browserSpeech.supported()).toBe(false);
    });

    test("returns false when speechSynthesis is missing", () => {
      delete (window as Window & { speechSynthesis?: unknown }).speechSynthesis;
      expect(browserSpeech.supported()).toBe(false);
    });

    test("returns false when SpeechSynthesisUtterance is missing", () => {
      delete (window as Window & { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance;
      expect(browserSpeech.supported()).toBe(false);
    });

    test("returns true when all three APIs are present", () => {
      expect(browserSpeech.supported()).toBe(true);
    });
  });

  describe("speak", () => {
    test("returns false when unsupported", () => {
      cleanupFakeApis();
      expect(browserSpeech.speak("a", "text", vi.fn(), vi.fn())).toBe(false);
    });

    test("returns false when text is blank", () => {
      expect(browserSpeech.speak("a", "", vi.fn(), vi.fn())).toBe(false);
      expect(browserSpeech.speak("a", "   ", vi.fn(), vi.fn())).toBe(false);
    });

    test("creates utterance with zh-CN lang and the provided text", () => {
      const idle = vi.fn();
      const failure = vi.fn();
      browserSpeech.speak("answer-a", "第一段回答", idle, failure);

      expect(fakeSynthesis.speak).toHaveBeenCalledTimes(1);
      expect(utteranceInstances.length).toBe(1);
      expect(utteranceInstances[0].text).toBe("第一段回答");
      expect(utteranceInstances[0].lang).toBe("zh-CN");
      expect(fakeSynthesis.speaking).toBe(true);
    });

    test("replaces a prior utterance owned by a different owner", () => {
      const idleA = vi.fn();
      const failA = vi.fn();
      const idleB = vi.fn();
      const failB = vi.fn();

      browserSpeech.speak("answer-a", "第一段", idleA, failA);
      expect(utteranceInstances.length).toBe(1);

      browserSpeech.speak("answer-b", "第二段", idleB, failB);
      // cancel called once during replacement
      expect(fakeSynthesis.cancel).toHaveBeenCalledTimes(1);
      // idleA called during replacement
      expect(idleA).toHaveBeenCalledTimes(1);

      expect(utteranceInstances.length).toBe(2);
      expect(utteranceInstances[1].text).toBe("第二段");
    });

    test("calls onend only for the current utterance", () => {
      const idleA = vi.fn();
      const idleB = vi.fn();

      browserSpeech.speak("a", "第一段", idleA, vi.fn());
      browserSpeech.speak("b", "第二段", idleB, vi.fn());

      // Simulate first utterance ending (stale)
      if (utteranceInstances[0].onend) {
        utteranceInstances[0].onend(new Event("end"));
      }
      // idleA already called during replacement + should not be called again by stale onend
      expect(idleA).toHaveBeenCalledTimes(1);

      // Simulate second utterance ending (current)
      if (utteranceInstances[1].onend) {
        utteranceInstances[1].onend(new Event("end"));
      }
      expect(idleB).toHaveBeenCalledTimes(1);
    });

    test("onerror calls onFailure then onIdle for the current utterance", () => {
      const idle = vi.fn();
      const failure = vi.fn();

      browserSpeech.speak("answer-x", "测试", idle, failure);

      if (utteranceInstances[0].onerror) {
        utteranceInstances[0].onerror({ error: "audio-busy" });
      }

      expect(failure).toHaveBeenCalledTimes(1);
      expect(idle).toHaveBeenCalledTimes(1);
    });

    test("catches synchronous speak errors and returns false", () => {
      fakeSynthesis.speak.mockImplementation(() => {
        throw new Error("Synthesis unavailable");
      });

      const idle = vi.fn();
      const failure = vi.fn();
      const result = browserSpeech.speak("a", "测试", idle, failure);

      expect(result).toBe(false);
      expect(failure).toHaveBeenCalledTimes(1);
      expect(idle).toHaveBeenCalledTimes(1);
    });
  });

  describe("stop", () => {
    test("stops only the matching owner and calls its idle callback", () => {
      const idleA = vi.fn();
      const idleB = vi.fn();

      browserSpeech.speak("answer-a", "第一段", idleA, vi.fn());
      browserSpeech.speak("answer-b", "第二段", idleB, vi.fn());

      // idleA was called during replacement
      expect(idleA).toHaveBeenCalledTimes(1);

      browserSpeech.stop("answer-b");
      // cancel was called once for replace + once for stop
      expect(fakeSynthesis.cancel).toHaveBeenCalledTimes(2);
      expect(idleB).toHaveBeenCalledTimes(1);
    });

    test("does not cancel when owner does not match", () => {
      const idleB = vi.fn();

      browserSpeech.speak("answer-b", "第二段", idleB, vi.fn());

      const cancelCountBefore = fakeSynthesis.cancel.mock.calls.length;
      browserSpeech.stop("answer-x");
      expect(fakeSynthesis.cancel).toHaveBeenCalledTimes(cancelCountBefore);
      expect(idleB).not.toHaveBeenCalled();
    });

    test("is a no-op when nothing is currently speaking", () => {
      browserSpeech.stop("answer-nothing");
      expect(fakeSynthesis.cancel).not.toHaveBeenCalled();
    });
  });
});
