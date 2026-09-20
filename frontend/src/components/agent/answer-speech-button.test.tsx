import React from "react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AnswerSpeechButton from "@/components/agent/answer-speech-button";
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

describe("AnswerSpeechButton", () => {
  test("renders nothing when browser speech is unsupported", () => {
    cleanupFakeApis();

    const { container } = render(<AnswerSpeechButton ownerId="a1" text="测试回答" />);
    expect(container).toBeEmptyDOMElement();
  });

  test("renders 朗读回答 idle button when supported", () => {
    render(<AnswerSpeechButton ownerId="a1" text="测试回答" />);

    const button = screen.getByRole("button", { name: "朗读回答" });
    expect(button).toBeVisible();
  });

  test("clicking starts speech and changes state to 停止朗读", async () => {
    const user = userEvent.setup();
    render(<AnswerSpeechButton ownerId="a1" text="测试回答" />);

    await user.click(screen.getByRole("button", { name: "朗读回答" }));

    expect(fakeSynthesis.speak).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "停止朗读" })).toBeVisible();
  });

  test("clicking during speech calls stop", async () => {
    const user = userEvent.setup();
    render(<AnswerSpeechButton ownerId="a1" text="测试回答" />);

    await user.click(screen.getByRole("button", { name: "朗读回答" }));
    expect(fakeSynthesis.speak).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "停止朗读" }));
    expect(fakeSynthesis.cancel).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "朗读回答" })).toBeVisible();
  });

  test("shows failure status message when synthesis fails", async () => {
    const user = userEvent.setup();
    render(<AnswerSpeechButton ownerId="a1" text="测试回答" />);

    await user.click(screen.getByRole("button", { name: "朗读回答" }));

    // Simulate error on the utterance within act
    act(() => {
      if (utteranceInstances[0]?.onerror) {
        utteranceInstances[0].onerror({ error: "audio-busy" });
      }
    });

    expect(screen.getByRole("status")).toHaveTextContent("朗读不可用，请检查浏览器语音设置。");
    expect(screen.getByRole("button", { name: "朗读回答" })).toBeVisible();
  });

  test("resets to 朗读回答 when speech ends naturally", async () => {
    const user = userEvent.setup();
    render(<AnswerSpeechButton ownerId="a1" text="测试回答" />);

    await user.click(screen.getByRole("button", { name: "朗读回答" }));
    expect(screen.getByRole("button", { name: "停止朗读" })).toBeVisible();

    // Simulate natural end within act
    act(() => {
      if (utteranceInstances[0]?.onend) {
        utteranceInstances[0].onend(new Event("end"));
      }
    });

    expect(screen.getByRole("button", { name: "朗读回答" })).toBeVisible();
  });

  test("unmounting stops the utterance", () => {
    const { unmount } = render(<AnswerSpeechButton ownerId="a1" text="测试回答" />);

    act(() => {
      browserSpeech.speak("a1", "测试回答", vi.fn(), vi.fn());
    });
    expect(fakeSynthesis.speak).toHaveBeenCalledTimes(1);

    unmount();
    expect(fakeSynthesis.cancel).toHaveBeenCalledTimes(1);
  });
});
