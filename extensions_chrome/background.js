/**
 * background.js — Service Worker da extensão Meet Agent.
 *
 * Responsabilidades:
 *   1. Ouvir eventos MEET_STARTED / MEET_ENDED do content.js
 *   2. Iniciar captura de áudio da aba via chrome.tabCapture
 *   3. Gravar em memória com MediaRecorder
 *   4. Ao encerrar, montar o arquivo e enviar ao servidor (FastAPI)
 *   5. Persistir estado no chrome.storage para o popup.js ler
 *
 * Fluxo:
 *   content.js → sendMessage(MEET_STARTED)
 *     → background captura aba → MediaRecorder grava chunks
 *   content.js → sendMessage(MEET_ENDED)
 *     → MediaRecorder para → blob → fetch POST /meetings/upload
 *     → salva meetingId no storage → notifica usuário
 */

"use strict";

// ── Configuração ──────────────────────────────────────────────────────────
// Configurações padrão da extensão

/** URL padrão do servidor FastAPI para upload de reuniões */
const DEFAULT_SERVER_URL = "http://localhost:8000";

/** Chave para armazenar configurações do usuário (chrome.storage.sync) */
const STORAGE_KEY_CONFIG = "meetAgentConfig";

/** Chave para armazenar estado atual da gravação (chrome.storage.local) */
const STORAGE_KEY_STATE  = "meetAgentState";

// ── Estado em memória do service worker ───────────────────────────────────
// Variáveis que mantêm o estado da gravação durante a vida do service worker

/** Instância do MediaRecorder que grava o stream de áudio */
let _mediaRecorder = null;

/** Array que acumula os chunks de áudio captados durante a gravação */
let _audioChunks   = [];

/** ID da aba do navegador onde está o Google Meet sendo gravado */
let _currentTabId  = null;

/** Título da reunião atual (extraído do DOM do Meet) */
let _currentTitle  = "Reunião";

/** Stream de áudio capturado via chrome.tabCapture */
let _stream        = null;

// ── Helpers de storage ────────────────────────────────────────────────────
// Funções auxiliares para gerenciar dados persistentes e estado

/**
 * Obtém as configurações do usuário do armazenamento sincronizado do Chrome
 * @async
 * @returns {Promise<Object>} Objeto com serverUrl, autoRecord, etc.
 */
async function getConfig() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(STORAGE_KEY_CONFIG, (data) => {
      resolve({
        serverUrl: DEFAULT_SERVER_URL,
        autoRecord: true,
        ...data[STORAGE_KEY_CONFIG],
      });
    });
  });
}

/**
 * Salva o estado atual da gravação no armazenamento local do Chrome
 * Pode conter: status (recording/uploading/done/error), title, meetingId, etc.
 * @async
 * @param {Object} state - Objeto com o estado da reunião atual
 */
async function setState(state) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [STORAGE_KEY_STATE]: state }, resolve);
  });
}

/**
 * Recupera o estado atual da gravação do armazenamento local
 * @async
 * @returns {Promise<Object>} Objeto com status e metadados da reunião
 */
async function getState() {
  return new Promise((resolve) => {
    chrome.storage.local.get(STORAGE_KEY_STATE, (data) => {
      resolve(data[STORAGE_KEY_STATE] || { status: "idle" });
    });
  });
}

// ── Gravação ──────────────────────────────────────────────────────────────
// Funções para iniciar, gerenciar e parar a gravação de áudio do Meet

/**
 * Inicia a captura e gravação de áudio da aba do Google Meet
 * Usa chrome.tabCapture para obter o stream de áudio e MediaRecorder para gravar
 * 
 * @async
 * @param {number} tabId - ID da aba do navegador
 * @param {string} title - Título da reunião (extraído do DOM)
 */
async function startRecording(tabId, title) {
  const config = await getConfig();
  if (!config.autoRecord) return; // Se autoRecord está desativado, não grava

  try {
    // Captura o stream de áudio da aba do Meet via API chrome.tabCapture
    // Essa API requer permissão "tabCapture" no manifest.json
    const stream = await new Promise((resolve, reject) => {
      chrome.tabCapture.capture(
        { audio: true, video: false }, // Captura APENAS áudio, sem vídeo
        (capturedStream) => {
          if (chrome.runtime.lastError || !capturedStream) {
            reject(new Error(chrome.runtime.lastError?.message || "Falha na captura"));
          } else {
            resolve(capturedStream);
          }
        }
      );
    });

    // Armazena o stream e inicializa as variáveis de estado
    _stream       = stream;
    _audioChunks  = []; // Limpa chunks anteriores
    _currentTabId = tabId;
    _currentTitle = title;

    // Cria a instância do MediaRecorder com codec opus em contêiner WebM
    _mediaRecorder = new MediaRecorder(stream, {
      mimeType: "audio/webm;codecs=opus",
    });

    // Callback executado periodicamente quando um chunk está pronto
    _mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) _audioChunks.push(e.data); // Acumula chunk no array
    };

    // Inicia a gravação, coletando chunks a cada 5 segundos
    _mediaRecorder.start(5000);

    // Atualiza o estado no armazenamento para que o popup.js possa ler
    await setState({
      status:    "recording",      // Status: gravando
      title,                       // Título da reunião
      startedAt: Date.now(),       // Timestamp de início
      meetingId: null,             // Será preenchido após upload
    });

    console.log("[MeetAgent] Gravação iniciada:", title);

  } catch (err) {
    // Se algo deu errado (ex: usuário negou permissão), notifica o erro
    console.error("[MeetAgent] Erro ao iniciar gravação:", err);
    await setState({ status: "error", error: err.message });
    notify("Erro ao iniciar gravação", err.message);
  }
}

/**
 * Para a gravação e envia o arquivo de áudio ao servidor
 * Monta o blob do áudio a partir dos chunks, libera o stream, e faz upload via FormData
 * 
 * @async
 * @returns {Promise<string|null>} Meeting ID retornado pelo servidor, ou null se falhar
 */
async function stopRecordingAndUpload() {
  // Segue sem fazer nada se não há gravação ativa
  if (!_mediaRecorder || _mediaRecorder.state === "inactive") return;

  return new Promise((resolve) => {
    _mediaRecorder.onstop = async () => {
      // Combina todos os chunks em um único blob de áudio
      const blob = new Blob(_audioChunks, { type: "audio/webm" });
      _audioChunks = []; // Limpa array de chunks

      // Importante: libera o stream de áudio para evitar vazamento de recurso
      _stream?.getTracks().forEach((t) => t.stop());
      _stream = null;

      // Atualiza estado para "uploading" enquanto envia ao servidor
      await setState({ status: "uploading", title: _currentTitle });

      // Tenta enviar o áudio ao servidor
      const meetingId = await uploadAudio(blob, _currentTitle);

      if (meetingId) {
        // Upload bem-sucedido! Atualiza estado e notifica usuário
        await setState({
          status:    "done",         // Processamento concluído
          title:     _currentTitle,
          meetingId,                 // ID gerado pelo servidor
          finishedAt: Date.now(),
        });
        // Notifica o usuário que a reunião foi processada com sucesso
        notify(
          "Reunião processada ✅",
          `"${_currentTitle}" está pronta. Abra o Meet Agent para ver o resumo.`
        );
      } else {
        // Upload falhou - armazena erro e notifica usuário
        await setState({ status: "error", error: "Falha no upload" });
        notify("Erro no upload", "Não foi possível enviar o áudio ao servidor.");
      }

      resolve(meetingId);
    };

    _mediaRecorder.stop();
  });
}

// ── Upload ────────────────────────────────────────────────────────────────
// Função para enviar o arquivo de áudio gravado ao servidor FastAPI

/**
 * Envia o arquivo de áudio ao servidor via multipart/form-data (FormData)
 * O servidor espera um POST em /meetings/upload com 'file' e 'title'
 * 
 * @async
 * @param {Blob} blob - Blob de áudio em formato WebM
 * @param {string} title - Título da reunião
 * @returns {Promise<string|null>} Meeting ID retornado pelo servidor, ou null se falhar
 */
async function uploadAudio(blob, title) {
  const config = await getConfig();
  const form   = new FormData();

  // Monta o FormData com arquivo e metadados
  form.append("file",  blob, `recording_${Date.now()}.webm`);
  form.append("title", title);

  try {
    // Faz POST para o servidor FastAPI
    const res = await fetch(`${config.serverUrl}/meetings/upload`, {
      method: "POST",
      body:   form, // FormData é automaticamente convertida para multipart
    });

    if (!res.ok) {
      // Status HTTP indicando erro (4xx ou 5xx)
      console.error("[MeetAgent] Upload falhou:", res.status, await res.text());
      return null;
    }

    // Extrai a resposta JSON do servidor
    const data = await res.json();
    console.log("[MeetAgent] Upload concluído. Meeting ID:", data.meeting_id);
    return data.meeting_id; // Retorna o ID gerado pelo servidor

  } catch (err) {
    // Erro de rede (ex: servidor offline, erro de conexão)
    console.error("[MeetAgent] Erro de rede no upload:", err);
    return null;
  }
}

// ── Notificações ──────────────────────────────────────────────────────────
// Função para exibir notificações ao usuário via Chrome Notifications API

/**
 * Exibe uma notificação ao usuário do navegador
 * A notificação aparece no canto inferior direito (desktop)
 * 
 * @param {string} title - Título da notificação
 * @param {string} message - Corpo da mensagem
 */
function notify(title, message) {
  chrome.notifications.create({
    type:    "basic",        // Tipo: notificação básica com ícone
    iconUrl: "icons/icon48.png",
    title,
    message,
  });
}

// ── Listener de mensagens do content.js ───────────────────────────────────
// Recebe eventos: MEET_STARTED, MEET_ENDED, MEET_TITLE_UPDATED, GET_STATE, STOP_RECORDING

/**
 * Handler que escuta mensagens vindas do content.js
 * O content.js envia eventos sobre entrada/saída da reunião e alterações de título
 */
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const tabId = sender.tab?.id;

  // Processa diferentes tipos de mensagens
  switch (msg.type) {

    case "MEET_STARTED":
      // Content.js detectou entrada em uma sala de reunião
      console.log("[MeetAgent] Meet detectado:", msg.payload);
      startRecording(tabId, msg.payload.title || "Reunião sem título");
      sendResponse({ ok: true });
      break;

    case "MEET_TITLE_UPDATED":
      // Content.js capturou o título real da reunião (pode demorar)
      _currentTitle = msg.payload.title;
      sendResponse({ ok: true });
      break;

    case "MEET_ENDED":
      // Content.js detectou saída da reunião (botão Sair ou navegação)
      console.log("[MeetAgent] Meet encerrado");
      stopRecordingAndUpload();
      sendResponse({ ok: true });
      break;

    case "GET_STATE":
      // Popup.js ou outra aba pede o estado atual da gravação
      getState().then(sendResponse);
      return true; // Indica resposta assíncrona

    case "STOP_RECORDING":
      // Popup.js pede para parar gravação manualmente
      stopRecordingAndUpload().then(() => sendResponse({ ok: true }));
      return true;

    default:
      console.warn("[MeetAgent] Mensagem desconhecida:", msg.type);
  }
});

// ── Limpeza ao fechar a aba do Meet ──────────────────────────────────────
// Listener que detecta quando a aba do Meet é fechada

/**
 * Se o usuário fechar a aba do Meet enquanto está gravando,
 * para a gravação e tenta fazer upload do áudio parcial
 */
chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === _currentTabId && _mediaRecorder?.state === "recording") {
    console.log("[MeetAgent] Aba fechada durante gravação — encerrando.");
    stopRecordingAndUpload();
  }
});