/**
 * Voice input (Web Speech API) and audio output (AudioContext) for JARVIS.
 */

// ---------------------------------------------------------------------------
// Speech Recognition
// ---------------------------------------------------------------------------

export interface VoiceInput {
  start(): void;
  stop(): void;
  pause(): void;
  resume(): void;
  isListening(): boolean;
  onStatusChange(cb: (isListening: boolean) => void): void;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const webkitSpeechRecognition: any;

export function createVoiceInput(
  onTranscript: (text: string) => void,
  onError: (msg: string) => void
): VoiceInput {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const SR = (window as any).SpeechRecognition || (typeof webkitSpeechRecognition !== "undefined" ? webkitSpeechRecognition : null);
  
  if (!SR) {
    console.warn("[voice] SpeechRecognition is NOT supported. Switching to Whisper STT fallback.");
    return createWhisperVoiceInput(onTranscript, onError);
  }

  // Check for secure context (required for microphone on mobile)
  if (window.location.protocol !== "https:" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
    console.warn("[voice] Microphone access is restricted to HTTPS or localhost on most mobile browsers.");
  }

  const recognition = new SR();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "vi-VN";

  let shouldListen = false;
  let paused = false;
  let isActuallyListening = false;
  let statusChangeCb: ((val: boolean) => void) | null = null;

  const setActuallyListening = (val: boolean) => {
    if (isActuallyListening !== val) {
      isActuallyListening = val;
      statusChangeCb?.(val);
    }
  };

  recognition.onstart = () => setActuallyListening(true);
  recognition.onend = () => {
    setActuallyListening(false);
    if (shouldListen && !paused) {
      try {
        recognition.start();
      } catch {
        // Already started
      }
    }
  };

  recognition.onresult = (event: any) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        const text = event.results[i][0].transcript.trim();
        if (text) onTranscript(text);
      }
    }
  };

  recognition.onerror = (event: any) => {
    if (event.error === "not-allowed") {
      onError("Microphone access denied. Please allow microphone access.");
      shouldListen = false;
    } else if (event.error === "no-speech") {
      // Normal, just restart
    } else if (event.error === "aborted") {
      // Expected during pause
    } else {
      console.warn("[voice] recognition error:", event.error);
    }
    setActuallyListening(false);
  };

  return {
    start() {
      shouldListen = true;
      paused = false;
      try {
        recognition.start();
      } catch {
        // Already started
      }
    },
    stop() {
      shouldListen = false;
      paused = false;
      recognition.stop();
    },
    pause() {
      paused = true;
      recognition.stop();
    },
    resume() {
      paused = false;
      if (shouldListen) {
        try {
          recognition.start();
        } catch {
          // Already started
        }
      }
    },
    isListening() {
      return isActuallyListening;
    },
    onStatusChange(cb) {
      statusChangeCb = cb;
    },
  };
}

function createWhisperVoiceInput(
  onTranscript: (text: string) => void,
  onError: (msg: string) => void
): VoiceInput {
  let mediaRecorder: MediaRecorder | null = null;
  let audioChunks: Blob[] = [];
  let isListening = false;
  let statusChangeCb: ((val: boolean) => void) | null = null;
  let stream: MediaStream | null = null;

  async function startRecording() {
    try {
      // navigator.mediaDevices only exists in a secure context (HTTPS or localhost).
      // Over plain HTTP (e.g. http://<tailscale-ip>:5173) it is undefined and the
      // browser disables microphone access entirely.
      if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
        const origin = window.location.origin;
        onError(
          "Không thể truy cập micrô: trình duyệt đang ở chế độ HTTP không an toàn, nên API microphone bị vô hiệu hóa. " +
          "Vui lòng truy cập JARVIS bằng HTTPS hoặc localhost (hiện tại: " + origin + ")."
        );
        console.warn("[voice] navigator.mediaDevices unavailable (insecure context):", {
          origin,
          isSecureContext: window.isSecureContext,
          protocol: window.location.protocol,
        });
        return;
      }
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunks.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunks, { type: "audio/wav" });
        if (audioBlob.size > 1000) {
          const formData = new FormData();
          formData.append("file", audioBlob, "speech.wav");
          try {
            const res = await fetch("/api/stt", {
              method: "POST",
              body: formData,
            });
            const data = await res.json();
            if (data.success && data.text) {
              onTranscript(data.text);
            } else if (data.error) {
              console.error("Whisper error response:", data.error);
            }
          } catch (err) {
            console.error("Whisper connection failed:", err);
          }
        }
      };

      mediaRecorder.start();
      isListening = true;
      statusChangeCb?.(true);
    } catch (err: any) {
      onError("Không thể kết nối micrô cho Whisper STT: " + err.message);
    }
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    if (stream) {
      stream.getTracks().forEach(track => track.stop());
    }
    isListening = false;
    statusChangeCb?.(false);
  }

  return {
    start() {
      startRecording();
    },
    stop() {
      stopRecording();
    },
    pause() {
      stopRecording();
    },
    resume() {
      startRecording();
    },
    isListening() {
      return isListening;
    },
    onStatusChange(cb) {
      statusChangeCb = cb;
    }
  };
}

// ---------------------------------------------------------------------------
// Audio Player
// ---------------------------------------------------------------------------

export interface AudioPlayer {
  enqueue(base64: string): Promise<void>;
  enqueueRaw(buffer: ArrayBuffer): Promise<void>;
  /** VieNeu: PCM16 mono đến từng đoạn nhỏ, phát liền mạch (edge dùng enqueue/enqueueRaw). */
  enqueuePcm(base64: string, sampleRate: number, gapMs: number): void;
  /** Call from a user gesture: lets the browser start audio later. The context idles suspended until something plays. */
  unlock(): Promise<void>;
  stop(): void;
  getAnalyser(): AnalyserNode;
  isPlaying(): boolean;
  onFinished(cb: () => void): void;
  onStarted(cb: () => void): void;
}

export function createAudioPlayer(): AudioPlayer {
  const audioCtx = new AudioContext();
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = 0.8;

  const gainNode = audioCtx.createGain();
  gainNode.gain.value = 1.3; // +30% volume boost

  analyser.connect(gainNode);
  gainNode.connect(audioCtx.destination);

  const queue: AudioBuffer[] = [];
  let isPlaying = false;
  let isProcessing = false;
  let playbackGeneration = 0;
  let currentSource: AudioBufferSourceNode | null = null;
  // Nhánh PCM (VieNeu): các đoạn được xếp lịch trên đồng hồ AudioContext để nối không hở.
  const pcmSources = new Set<AudioBufferSourceNode>();
  let pcmNextTime = 0;
  let finishedCallback: (() => void) | null = null;
  let startedCallback: (() => void) | null = null;

  // A running AudioContext keeps the OS audio thread awake even when nothing plays (power and heat on a phone).
  // Suspend it a moment after the last sound; the next enqueue resumes it.
  let idleTimer = 0;
  const IDLE_SUSPEND_MS = 2500;
  function suspendSoon() {
    clearTimeout(idleTimer);
    idleTimer = window.setTimeout(() => {
      if (!isPlaying && queue.length === 0 && pcmSources.size === 0 && !isProcessing && audioCtx.state === "running") void audioCtx.suspend();
    }, IDLE_SUSPEND_MS);
  }
  function finished() {
    finishedCallback?.();
    suspendSoon();
  }

  function playNext() {
    if (queue.length === 0) {
      isPlaying = false;
      currentSource = null;
      finished();
      return;
    }

    // Chỉ báo "started" khi chuyển từ im lặng sang phát (đầu 1 lượt nói),
    // không báo lại cho từng chunk kế tiếp trong cùng 1 lượt đang phát.
    const wasPlaying = isPlaying;
    isPlaying = true;
    const buffer = queue.shift()!;
    const source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(analyser);
    currentSource = source;

    source.onended = () => {
      if (currentSource === source) {
        playNext();
      }
    };

    if (!wasPlaying) startedCallback?.();
    source.start();
  }

  return {
    async enqueue(base64: string) {
      clearTimeout(idleTimer);
      const generation = playbackGeneration;
      isProcessing = true;
      // Resume audio context (browser autoplay policy)
      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }

      try {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
        }
        const audioBuffer = await audioCtx.decodeAudioData(bytes.buffer.slice(0));
        if (generation !== playbackGeneration) return;
        queue.push(audioBuffer);
        isProcessing = false;
        if (!isPlaying) playNext();
      } catch (err) {
        console.error("[audio] decode error:", err);
        isProcessing = false;
        // Skip bad audio, continue
        if (!isPlaying && queue.length > 0) playNext();
      }
    },

    async enqueueRaw(buffer: ArrayBuffer) {
      clearTimeout(idleTimer);
      const generation = playbackGeneration;
      isProcessing = true;
      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }
      try {
        const audioBuffer = await audioCtx.decodeAudioData(buffer.slice(0));
        if (generation !== playbackGeneration) return;
        queue.push(audioBuffer);
        isProcessing = false;
        if (!isPlaying) playNext();
      } catch (err) {
        console.error("[audio] decode error:", err);
        isProcessing = false;
        if (!isPlaying && queue.length > 0) playNext();
      }
    },

    enqueuePcm(base64: string, sampleRate: number, gapMs: number) {
      clearTimeout(idleTimer);
      if (audioCtx.state === "suspended") void audioCtx.resume();
      const binary = atob(base64);
      const samples = binary.length >> 1;
      if (samples === 0) return;
      const buffer = audioCtx.createBuffer(1, samples, sampleRate);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < samples; i++) {
        let v = binary.charCodeAt(2 * i) | (binary.charCodeAt(2 * i + 1) << 8);
        if (v >= 0x8000) v -= 0x10000;
        channel[i] = v / 32768;
      }
      const source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(analyser);

      const now = audioCtx.currentTime;
      const continuing = pcmNextTime > now;
      let startAt = continuing ? pcmNextTime : now + 0.45; // đệm 450ms: VieNeu khuyên 150-300ms, log cho thấy GPU có lúc chậm nên lấy cao hơn
      if (continuing && gapMs > 0) startAt += gapMs / 1000; // nghỉ giữa hai câu
      pcmNextTime = startAt + buffer.duration;

      if (pcmSources.size === 0 && !isPlaying) {
        isPlaying = true;
        startedCallback?.();
      }
      pcmSources.add(source);
      source.onended = () => {
        pcmSources.delete(source);
        if (pcmSources.size === 0 && queue.length === 0) {
          isPlaying = false;
          finished();
        }
      };
      source.start(startAt);
    },

    stop() {
      playbackGeneration++;
      queue.length = 0;
      for (const source of pcmSources) {
        source.onended = null;
        try {
          source.stop();
        } catch {
          // Already stopped
        }
      }
      pcmSources.clear();
      pcmNextTime = 0;
      if (currentSource) {
        try {
          currentSource.stop();
        } catch {
          // Already stopped
        }
        currentSource = null;
      }
      isPlaying = false;
      isProcessing = false;
      finished();
    },

    async unlock() {
      if (audioCtx.state === "suspended") await audioCtx.resume();
      suspendSoon();
    },

    getAnalyser() {
      return analyser;
    },

    isPlaying() {
      return isPlaying || queue.length > 0 || isProcessing;
    },

    onFinished(cb: () => void) {
      finishedCallback = cb;
    },

    onStarted(cb: () => void) {
      startedCallback = cb;
    },
  };
}

// ---------------------------------------------------------------------------
// Barge-in detector (lightweight VAD)
// ---------------------------------------------------------------------------
//
// Phát hiện người dùng bắt đầu nói trong lúc JARVIS đang nói, sớm hơn nhiều so
// với việc chờ STT (Web Speech API / Whisper) trả về transcript cuối cùng —
// STT chỉ dùng để biết NÓI GÌ, còn việc NGẮT LỜI dựa vào tín hiệu âm lượng mic
// độc lập, tách rời khỏi vòng đời start/pause của voiceInput.

export interface InterruptDetector {
  start(): void;
  stop(): void;
}

export function createInterruptDetector(onInterrupt: () => void): InterruptDetector {
  let stream: MediaStream | null = null;
  let detectorCtx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let dataArray: Uint8Array<ArrayBuffer> | null = null;
  let rafId: number | null = null;
  let active = false;
  let aboveThresholdSince: number | null = null;
  let startSeq = 0;

  // RMS (0-255 scale quanh mốc im lặng 128) và thời gian phải nghe liên tục
  // vượt ngưỡng trước khi coi là "người dùng đang nói thật" — giảm khả năng
  // kích hoạt nhầm do tạp âm ngắn hoặc dội tiếng còn sót lại từ loa dù đã có
  // echoCancellation.
  const THRESHOLD = 30;
  const SUSTAIN_MS = 220;

  async function ensureStream(): Promise<boolean> {
    if (stream) return true;
    if (!navigator.mediaDevices?.getUserMedia) return false;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      detectorCtx = new AudioContext();
      const source = detectorCtx.createMediaStreamSource(stream);
      analyser = detectorCtx.createAnalyser();
      analyser.fftSize = 512;
      dataArray = new Uint8Array(analyser.fftSize);
      source.connect(analyser);
      return true;
    } catch (err) {
      console.warn("[interrupt-detector] Không lấy được mic để theo dõi ngắt lời:", err);
      return false;
    }
  }

  function tick() {
    if (!active || !analyser || !dataArray) return;
    analyser.getByteTimeDomainData(dataArray);

    let sumSquares = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const v = dataArray[i] - 128;
      sumSquares += v * v;
    }
    const rms = Math.sqrt(sumSquares / dataArray.length);
    const now = performance.now();

    if (rms > THRESHOLD) {
      if (aboveThresholdSince === null) {
        aboveThresholdSince = now;
      } else if (now - aboveThresholdSince >= SUSTAIN_MS) {
        active = false; // one-shot cho tới lần start() kế tiếp
        onInterrupt();
        return;
      }
    } else {
      aboveThresholdSince = null;
    }

    rafId = requestAnimationFrame(tick);
  }

  return {
    start() {
      if (active) return;
      const seq = ++startSeq;
      ensureStream().then((ok) => {
        // Bỏ qua nếu đã stop() (hoặc start() lại) trong lúc đang chờ getUserMedia
        if (!ok || seq !== startSeq) return;
        active = true;
        aboveThresholdSince = null;
        rafId = requestAnimationFrame(tick);
      });
    },
    stop() {
      startSeq++;
      active = false;
      aboveThresholdSince = null;
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      // Release the microphone. Only the animation frame was cancelled before,
      // so the mic stayed captured (recording indicator lit, device held) and a
      // second AudioContext lived alongside the player's for the whole session.
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
        stream = null;
      }
      analyser = null;
      if (detectorCtx) {
        const ctx = detectorCtx;
        detectorCtx = null;
        void ctx.close().catch(() => { /* already closed */ });
      }
    },
  };
}
