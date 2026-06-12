(() => {
  if (window.__meetCapture) return;

  const chunks = [];
  const speakerLog = [];
  const t0 = Date.now();
  let lastAudioTs = 0;
  let mediaRecorder = null;
  let meterInterval = null;
  let audioCtx = null;
  let analyser = null;

  const RMS_VOICE_THRESHOLD = 0.01;

  function readActiveSpeakers() {
    const SEL = [
      '[data-self-name][data-speaking="true"]',
      'div[class*="speaking"i] [data-self-name]',
      'div[jscontroller][data-participant-id][class*="active"i]',
    ];
    const names = new Set();
    for (const sel of SEL) {
      document.querySelectorAll(sel).forEach((el) => {
        const name = el.getAttribute('data-self-name')
          || el.textContent?.trim().split('\n')[0];
        if (name) names.add(name.slice(0, 80));
      });
      if (names.size) break;
    }
    return [...names];
  }

  function startMeter(stream) {
    audioCtx = new AudioContext();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    const source = audioCtx.createMediaStreamSource(stream);
    source.connect(analyser);
    const buf = new Float32Array(analyser.fftSize);

    meterInterval = setInterval(() => {
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
  }

  function buildRecorder(stream) {
    startMeter(stream);
    mediaRecorder = new MediaRecorder(stream, {
      mimeType: 'audio/webm;codecs=opus',
      audioBitsPerSecond: 128000,
    });
    mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };
    mediaRecorder.start(2000);
  }

  function buildAPI(sources) {
    window.__meetCapture = {
      _error: null,
      stop: () => new Promise((resolve, reject) => {
        clearInterval(meterInterval);
        if (audioCtx) audioCtx.close();
        mediaRecorder.onstop = () => {
          const blob = new Blob(chunks, { type: 'audio/webm' });
          const reader = new FileReader();
          reader.onloadend = () => resolve(String(reader.result).split(',')[1] || '');
          reader.onerror = () => reject(new Error('Falha ao ler blob'));
          reader.readAsDataURL(blob);
        };
        try { mediaRecorder.stop(); } catch (e) { reject(e); }
      }),
      getSpeakerLog: () => speakerLog,
      getLastAudioTs: () => lastAudioTs,
      getState: () => ({
        recording: mediaRecorder ? mediaRecorder.state === 'recording' : false,
        chunks: chunks.length,
        audioTracks: mediaRecorder ? 1 : 0,
        sources,
      }),
      _resume: () => { if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume(); },
    };
  }

  // Caminho 1 — tracks WebRTC interceptadas antes do Meet inicializar
  function initFromRTC() {
    const tracks = (window.__rtcAudioTracks || []).filter(t => t.readyState === 'live');
    if (!tracks.length) return false;
    buildRecorder(new MediaStream(tracks));
    buildAPI({ rtc: tracks.length, srcObject: 0, dom: 0 });
    console.log('[meetCapture] via RTC: ' + tracks.length + ' track(s)');
    return true;
  }

  // Caminho 2 — getDisplayMedia com áudio do sistema
  async function initFromDisplay() {
    try {
      const ds = await navigator.mediaDevices.getDisplayMedia({
        audio: true, video: { width: 1, height: 1, frameRate: 1 },
      });
      const track = ds.getAudioTracks()[0];
      if (!track) return false;
      buildRecorder(new MediaStream([track]));
      buildAPI({ rtc: 0, srcObject: 1, dom: 0 });
      console.log('[meetCapture] via DisplayMedia');
      return true;
    } catch (e) {
      console.warn('[meetCapture] getDisplayMedia falhou:', e.message);
      return false;
    }
  }

  // Caminho 3 — hook em elementos <audio> do DOM
  function initFallback() {
    const ctx = new AudioContext();
    const dest = ctx.createMediaStreamDestination();
    let hooked = 0;
    function hook(el) {
      try { ctx.createMediaElementSource(el).connect(dest); hooked++; } catch (_) {}
    }
    document.querySelectorAll('audio').forEach(hook);
    new MutationObserver((m) => {
      for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        if (n.tagName === 'AUDIO') hook(n);
        else if (n.querySelectorAll) n.querySelectorAll('audio').forEach(hook);
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
    ctx.resume();
    if (hooked === 0 && !document.querySelectorAll('audio').length) {
      window.__meetCapture = { _error: 'No audio elements found - Aba do Meet sem áudio' };
      return;
    }
    buildRecorder(dest.stream);
    buildAPI({ rtc: 0, srcObject: 0, dom: hooked });
    console.log('[meetCapture] via DOM fallback: ' + hooked + ' elemento(s)');
  }

  async function init() {
    // Tenta RTC imediatamente
    if (initFromRTC()) return;

    // Aguarda 3s — negociação WebRTC pode ainda estar em andamento
    await new Promise(r => setTimeout(r, 3000));
    if (initFromRTC()) return;

    // Tenta captura de tela com áudio do sistema
    if (await initFromDisplay()) return;

    // Último recurso: elementos <audio> do DOM
    initFallback();
  }

  init();
})();