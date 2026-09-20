export {};

declare global {
  interface SpeechRecognitionAlternative {
    transcript: string;
    confidence: number;
  }
  interface SpeechRecognitionResult {
    isFinal: boolean;
    length: number;
    [index: number]: SpeechRecognitionAlternative;
  }
  interface SpeechRecognitionEvent extends Event {
    resultIndex: number;
    results: { length: number; [index: number]: SpeechRecognitionResult };
  }
  interface SpeechRecognition extends EventTarget {
    lang: string;
    continuous: boolean;
    interimResults: boolean;
    start(): void;
    stop(): void;
    abort(): void;
    onresult: ((event: SpeechRecognitionEvent) => void) | null;
    onend: (() => void) | null;
    onerror: ((event: { error: string }) => void) | null;
  }
  type SpeechRecognitionConstructor = new () => SpeechRecognition;
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  }
}
