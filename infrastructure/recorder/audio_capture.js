/**
 * audio_capture.js — Captura de áudio da reunião no Google Meet
 * ---------------------------------------------------------------
 * Corrige o Bug S2: em vez de getUserMedia (microfone LOCAL da máquina
 * do bot), intercepta os elementos <audio> que o Meet cria para tocar
 * o áudio dos participantes remotos e grava ESSE stream.
 *
 * Também implementa:
 *   - S7: log temporal de atividade de voz (alimenta BlockBasedTranscriber)
 *   - Sinal de silêncio para S4 (detecção de fim de reunião)
 *
 * API exposta em window.__meetCapture:
 *   .stop()            -> Promise<string>  (base64 do .webm final)
 *   .getSpeakerLog()   -> Array<{t, rms, speakers}>
 *   .getLastAudioTs()  -> number (epoch ms do último áudio audível)
 *   .getState()        -> {recording, hookedElements, chunks}
 *
 * Injetar via page.evaluate() DEPOIS do clique em "Participar"
 * (a autoplay policy exige gesto do usuário para o AudioContext rodar).
 */
(() => {
  if (window.__meetCapture) return;

  const ctx = new AudioContext();
  const destination = ctx.createMediaStreamDestination();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 2048;

  const connected = new WeakSet();
  const chunks = [];
  const speakerLog = [];
  const t0 = Date.now();
  let lastAudioTs = Date.now();

  let hookedCount = 0;

  function hook(el) {
    if (connected.has(el)) return;
    try {
      const source = ctx.createMediaElementSource(el);
      source.connect(destination);
      source.connect(ctx.destination);
      connected.add(el);
      hookedCount++;
    } catch (e) {
      // Elemento já consumido por outro MediaElementSource
    }
  }

  document.querySelectorAll('audio').forEach(hook);

  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType !== 1) continue;
        if (node.tagName === 'AUDIO') hook(node);
        else if (node.querySelectorAll) node.querySelectorAll('audio').forEach(hook);
      }
    }
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  destination.stream.getAudioTracks().forEach(() => {});
  const recorder = new MediaRecorder(destination.stream, {
    mimeType: 'audio/webm;codecs=opus',
    audioBitsPerSecond: 128000,
  });
  recorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunks.push(e.data); };
  recorder.start(2000);

  const tapSource = ctx.createMediaStreamSource(destination.stream);
  tapSource.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);

  const RMS_VOICE_THRESHOLD = 0.01;

  function readActiveSpeakers() {
    const SPEAKING_SELECTORS = [
      '[data-self-name][data-speaking="true"]',
      'div[class*="speaking"i] [data-self-name]',
      'div[jscontroller][data-participant-id][class*="active"i]',
    ];
    const names = new Set();
    for (const sel of SPEAKING_SELECTORS) {
      document.querySelectorAll(sel).forEach((el) => {
        const name = el.getAttribute('data-self-name')
          || el.textContent?.trim().split('\n')[0];
        if (name) names.add(name.slice(0, 80));
      });
      if (names.size) break;
    }
    return [...names];
  }

  const meter = setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);

    if (rms > RMS_VOICE_THRESHOLD) {
      lastAudioTs = Date.now();
      speakerLog.push({
        t: (Date.now() - t0) / 1000,
        rms: Number(rms.toFixed(4)),
        speakers: readActiveSpeakers(),
      });
    }
  }, 500);

  window.__meetCapture = {
    stop: () => new Promise((resolve, reject) => {
      clearInterval(meter);
      observer.disconnect();
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: 'audio/webm' });
        const reader = new FileReader();
        reader.onloadend = () => resolve(String(reader.result).split(',')[1]);
        reader.onerror = () => reject(new Error('Falha ao ler blob de áudio'));
        reader.readAsDataURL(blob);
      };
      try { recorder.stop(); } catch (e) { reject(e); }
    }),
    getSpeakerLog: () => speakerLog,
    getLastAudioTs: () => lastAudioTs,
    getState: () => ({
      recording: recorder.state === 'recording',
      hookedElements: hookedCount,
      chunks: chunks.length,
      audioContextState: ctx.state,
    }),
    _resume: () => ctx.resume(),
  };

  ctx.resume();
})();
