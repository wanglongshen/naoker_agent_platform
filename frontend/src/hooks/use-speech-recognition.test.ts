import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

let latestInstance: any = null;

function FakeSpeechRecognition(this: any) {
  this.lang = "";
  this.continuous = false;
  this.interimResults = false;
  this.start = vi.fn();
  this.stop = vi.fn();
  this.abort = vi.fn();
  this.onresult = null;
  this.onend = null;
  this.onerror = null;

  const self = this;
  this.emitResult = function (event: any) {
    if (self.onresult) self.onresult(event);
  };
  this.emitEnd = function () {
    if (self.onend) self.onend();
  };
  this.emitError = function (error: string) {
    if (self.onerror) self.onerror({ error });
  };

  latestInstance = this;
}

function finalResult(text: string) {
  return {
    isFinal: true,
    length: 1,
    0: { transcript: text, confidence: 0.95 },
  };
}

function interimResult(text: string) {
  return {
    isFinal: false,
    length: 1,
    0: { transcript: text, confidence: 0.7 },
  };
}

import { useSpeechRecognition } from "@/hooks/use-speech-recognition";

describe("useSpeechRecognition", () => {
  let onFinalTranscript: ReturnType<typeof vi.fn>;
  const savedAddEventListener = document.addEventListener;
  const savedRemoveEventListener = document.removeEventListener;
  const savedWindowAddEventListener = window.addEventListener;
  const savedWindowRemoveEventListener = window.removeEventListener;
  let docListeners: Map<string, Array<(...args: any[]) => void>>;
  let winListeners: Map<string, Array<(...args: any[]) => void>>;
  const savedSpeechRecognition = (window as any).SpeechRecognition;
  const savedWebkitSpeechRecognition = (window as any).webkitSpeechRecognition;

  beforeEach(() => {
    latestInstance = null;
    onFinalTranscript = vi.fn();
    docListeners = new Map();
    winListeners = new Map();

    document.addEventListener = vi.fn((type: string, listener: any) => {
      if (!docListeners.has(type)) docListeners.set(type, []);
      docListeners.get(type)!.push(listener);
    }) as any;
    document.removeEventListener = vi.fn((type: string, listener: any) => {
      const arr = docListeners.get(type);
      if (arr) {
        const idx = arr.indexOf(listener);
        if (idx !== -1) arr.splice(idx, 1);
      }
    }) as any;

    window.addEventListener = vi.fn((type: string, listener: any) => {
      if (!winListeners.has(type)) winListeners.set(type, []);
      winListeners.get(type)!.push(listener);
    }) as any;
    window.removeEventListener = vi.fn((type: string, listener: any) => {
      const arr = winListeners.get(type);
      if (arr) {
        const idx = arr.indexOf(listener);
        if (idx !== -1) arr.splice(idx, 1);
      }
    }) as any;

    (window as any).isSecureContext = true;
    (window as any).SpeechRecognition = FakeSpeechRecognition;
    (window as any).webkitSpeechRecognition = FakeSpeechRecognition;

    vi.useFakeTimers();
  });

  afterEach(() => {
    document.addEventListener = savedAddEventListener;
    document.removeEventListener = savedRemoveEventListener;
    window.addEventListener = savedWindowAddEventListener;
    window.removeEventListener = savedWindowRemoveEventListener;
    (window as any).SpeechRecognition = savedSpeechRecognition;
    (window as any).webkitSpeechRecognition = savedWebkitSpeechRecognition;
    vi.useRealTimers();
  });

  test("returns unsupported state when no SpeechRecognition constructor exists", () => {
    delete (window as any).SpeechRecognition;
    delete (window as any).webkitSpeechRecognition;

    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    expect(result.current.state).toBe("unsupported");
    expect(result.current.supported).toBe(false);
  });

  test("returns unsupported state when isSecureContext is false", () => {
    (window as any).isSecureContext = false;

    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    expect(result.current.state).toBe("unsupported");
    expect(result.current.supported).toBe(false);
  });

  test("configures recognition with zh-CN, continuous false, and interimResults true on start", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    const inst = latestInstance;
    expect(inst.lang).toBe("zh-CN");
    expect(inst.continuous).toBe(false);
    expect(inst.interimResults).toBe(true);
    expect(inst.start).toHaveBeenCalledTimes(1);
    expect(result.current.state).toBe("listening");
  });

  test("sets interimText when interim results arrive", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    act(() => {
      latestInstance.emitResult({
        resultIndex: 0,
        results: [interimResult("正在测试")],
      });
    });

    expect(result.current.interimText).toBe("正在测试");
  });

  test("clears interimText on final result and calls onFinalTranscript", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    act(() => {
      latestInstance.emitResult({
        resultIndex: 0,
        results: [interimResult("临时的"), finalResult("最终的")],
      });
    });

    expect(result.current.interimText).toBe("");
    expect(onFinalTranscript).toHaveBeenCalledTimes(1);
    const appendFn = onFinalTranscript.mock.calls[0][0];
    expect(appendFn("已有内容")).toBe("已有内容 最终的");
  });

  test("deduplicates final results with same generation:resultIndex:transcript key", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    // First emission: index 0, result "第一句"
    act(() => {
      latestInstance.emitResult({
        resultIndex: 0,
        results: [finalResult("第一句")],
      });
    });

    expect(onFinalTranscript).toHaveBeenCalledTimes(1);

    // Re-emission of same index 0 with same transcript - should be deduplicated
    act(() => {
      latestInstance.emitResult({
        resultIndex: 0,
        results: [finalResult("第一句")],
      });
    });

    expect(onFinalTranscript).toHaveBeenCalledTimes(1);

    // Different index should be processed
    act(() => {
      latestInstance.emitResult({
        resultIndex: 1,
        results: [finalResult("第一句"), finalResult("第二句")],
      });
    });

    expect(onFinalTranscript).toHaveBeenCalledTimes(2);
  });

  test("ignores late results after stop()", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    const inst = latestInstance;

    act(() => {
      result.current.stop();
    });

    expect(result.current.state).toBe("idle");

    act(() => {
      inst.emitResult({
        resultIndex: 0,
        results: [finalResult("延迟的结果")],
      });
    });

    expect(onFinalTranscript).not.toHaveBeenCalled();
  });

  test("ignores late results after unmount", () => {
    const { result, unmount } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    const inst = latestInstance;

    unmount();

    act(() => {
      inst.emitResult({
        resultIndex: 0,
        results: [finalResult("卸载后的结果")],
      });
    });

    expect(onFinalTranscript).not.toHaveBeenCalled();
  });

  test("resets generation on second start making old results stale", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    const firstInst = latestInstance;

    act(() => {
      result.current.start();
    });

    expect(firstInst.stop).toHaveBeenCalled();
    expect(result.current.state).toBe("listening");
  });

  test("dispose invalidates recognition with abort and sets idle", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    const inst = latestInstance;

    act(() => {
      result.current.dispose();
    });

    expect(inst.abort).toHaveBeenCalled();
    expect(result.current.state).toBe("idle");
  });

  test("maps not-allowed error to Chinese message", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    act(() => {
      latestInstance.emitError("not-allowed");
    });

    expect(result.current.state).toBe("error");
    expect(result.current.message).toBe("浏览器未授予麦克风权限。");
  });

  test("maps service-not-allowed error to Chinese message", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    act(() => {
      latestInstance.emitError("service-not-allowed");
    });

    expect(result.current.message).toBe("浏览器语音服务不可用。");
  });

  test("maps audio-capture error to Chinese message", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    act(() => {
      latestInstance.emitError("audio-capture");
    });

    expect(result.current.message).toBe("未检测到可用麦克风。");
  });

  test("maps network error to Chinese message", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    act(() => {
      latestInstance.emitError("network");
    });

    expect(result.current.message).toBe("语音服务连接失败，请稍后重试。");
  });

  test("maps no-speech error to Chinese message", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    act(() => {
      latestInstance.emitError("no-speech");
    });

    expect(result.current.message).toBe("未识别到语音，请再试一次。");
  });

  test("preserves error message after subsequent end event", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    act(() => {
      latestInstance.emitError("not-allowed");
    });

    expect(result.current.message).toBe("浏览器未授予麦克风权限。");

    act(() => {
      latestInstance.emitEnd();
    });

    expect(result.current.state).toBe("idle");
    expect(result.current.message).toBe("浏览器未授予麦克风权限。");
  });

  test("transitions to idle on normal end event", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    act(() => {
      latestInstance.emitEnd();
    });

    expect(result.current.state).toBe("idle");
    expect(result.current.interimText).toBe("");
  });

  test("does not start when disabled is true", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: true }),
    );

    act(() => {
      result.current.start();
    });

    expect(result.current.state).toBe("idle");
    expect(latestInstance).toBeNull();
  });

  test("does not start when state is unsupported", () => {
    delete (window as any).SpeechRecognition;
    delete (window as any).webkitSpeechRecognition;

    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    expect(result.current.state).toBe("unsupported");
  });

  test("aborts recognition on visibilitychange to hidden", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    const inst = latestInstance;
    expect(result.current.state).toBe("listening");

    const visibilityListeners = docListeners.get("visibilitychange") || [];
    expect(visibilityListeners.length).toBeGreaterThan(0);

    Object.defineProperty(document, "hidden", {
      value: true,
      writable: true,
      configurable: true,
    });

    act(() => {
      visibilityListeners[0]();
    });

    expect(inst.abort).toHaveBeenCalled();
  });

  test("aborts recognition on pagehide", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    const inst = latestInstance;

    const pagehideListeners = winListeners.get("pagehide") || [];
    expect(pagehideListeners.length).toBeGreaterThan(0);

    act(() => {
      pagehideListeners[0]();
    });

    expect(inst.abort).toHaveBeenCalled();
  });

  test("stops recognition (not abort) on normal stop call", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    const inst = latestInstance;

    act(() => {
      result.current.stop();
    });

    expect(inst.stop).toHaveBeenCalled();
    expect(inst.abort).not.toHaveBeenCalled();
  });

  test("does not double-up interim text when intermittent interim results arrive", () => {
    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    act(() => {
      latestInstance.emitResult({
        resultIndex: 0,
        results: [interimResult("你好")],
      });
    });

    expect(result.current.interimText).toBe("你好");

    act(() => {
      latestInstance.emitResult({
        resultIndex: 0,
        results: [interimResult("你好世界")],
      });
    });

    expect(result.current.interimText).toBe("你好世界");
  });

  test("catches synchronous constructor/start errors and maps to recovered message", () => {
    const ErrorCtor = function (this: any) {
      throw new Error("Constructor failed");
    };

    (window as any).SpeechRecognition = ErrorCtor;
    delete (window as any).webkitSpeechRecognition;

    const { result } = renderHook(() =>
      useSpeechRecognition({ onFinalTranscript, disabled: false }),
    );

    act(() => {
      result.current.start();
    });

    expect(result.current.state).toBe("error");
    expect(result.current.message).toBeTruthy();
  });
});
