"use strict";

// Elementos do DOM 
// Referências aos elementos HTML que serão manipulados por JavaScript

/** Badge que exibe o status atual (Ocioso, Gravando, Enviando, etc) */
const statusBadge      = document.getElementById("statusBadge");

/** Nome/título da reunião atual */
const meetingName      = document.getElementById("meetingName");

/** Duração da gravação em tempo real (MM:SS) */
const meetingDuration  = document.getElementById("meetingDuration");

/** Indicador visual com ponto pulsante quando gravando */
const recIndicator     = document.getElementById("recIndicator");

/** Seção que contém o ID da reunião (aparece após sucesso) */
const meetingIdSection = document.getElementById("meetingIdSection");

/** Valor do ID da reunião para copiar */
const meetingIdValue   = document.getElementById("meetingIdValue");

/** Botão para copiar o ID da reunião */
const copyBtn          = document.getElementById("copyBtn");

/** Botão para parar manualmente a gravação */
const stopBtn          = document.getElementById("stopBtn");

/** Botão para abrir a app Streamlit */
const openBtn          = document.getElementById("openBtn");

/** Checkbox para habilitar/desabilitar gravação automática */
const autoRecord       = document.getElementById("autoRecord");

/** Input para configurar URL do servidor */
const serverUrl        = document.getElementById("serverUrl");

/** Botão para salvar configurações */
const saveBtn          = document.getElementById("saveBtn");

/** Mensagem de confirmação após salvar */
const savedMsg         = document.getElementById("savedMsg");

// Status map 
// Configuração para cada estado da gravação
// Define como renderizar a UI para cada status

const STATUS_CONFIG = {
  // Nenhuma reunião em andamento
  idle: {
    label: "Ocioso",
    badgeClass: "badge-idle",
    showRec: false,        // Não mostra indicador de gravação
    enableStop: false,     // Botão stop desativado
  },
  // Gravação ativa
  recording: {
    label: "Gravando",
    badgeClass: "badge-recording",
    showRec: true,         // Mostra ponto pulsante
    enableStop: true,      // Usuário pode parar manualmente
  },
  // Enviando arquivo ao servidor
  uploading: {
    label: "Enviando...",
    badgeClass: "badge-uploading",
    showRec: false,
    enableStop: false,
  },
  // Upload concluído com sucesso
  done: {
    label: "Pronto ✓",
    badgeClass: "badge-done",
    showRec: false,
    enableStop: false,
  },
  // Erro durante gravação ou upload
  error: {
    label: "Erro",
    badgeClass: "badge-error",
    showRec: false,
    enableStop: false,
  },
};

// Renderização
// Função que atualiza a UI baseada no estado atual

/**
 * Atualiza todos os elementos visuais do popup com base no estado da gravação
 * @param {Object} state - Estado retornado pelo background.js
 * @param {string} state.status - Status atual (idle, recording, uploading, done, error)
 * @param {string} state.title - Título da reunião
 * @param {number} state.startedAt - Timestamp de início da gravação
 * @param {string} state.meetingId - ID da reunião (preenchido após sucesso)
 */
function renderState(state) {
  // Obtém configuração visual para o status atual
  const cfg = STATUS_CONFIG[state.status] || STATUS_CONFIG.idle;

  // Atualiza o badge de status no header
  statusBadge.textContent = cfg.label;
  statusBadge.className = `badge ${cfg.badgeClass}`;

  // Exibe o nome da reunião ou mensagem padrão se nenhuma ativa
  meetingName.textContent = state.title || "Nenhuma reunião ativa";

  // Calcula e exibe a duração em tempo real se está gravando
  if (state.startedAt && state.status === "recording") {
    // Calcula segundos decorridos desde início
    const elapsed = Math.floor((Date.now() - state.startedAt) / 1000);
    
    // Converte para formato MM:SS com zero à esquerda
    const min = Math.floor(elapsed / 60).toString().padStart(2, "0");
    const sec = (elapsed % 60).toString().padStart(2, "0");
    meetingDuration.textContent = `⏱ ${min}:${sec}`;
  } else {
    // Limpa duração se não está gravando
    meetingDuration.textContent = "";
  }

  // Mostra/esconde o indicador pulsante de gravação
  recIndicator.style.display = cfg.showRec ? "flex" : "none";

  // Habilita/desabilita botão de parar gravação
  stopBtn.disabled = !cfg.enableStop;

  // Mostra seção com ID da reunião apenas se upload foi bem-sucedido
  if (state.meetingId) {
    meetingIdSection.style.display = "block";
    meetingIdValue.textContent = state.meetingId;
  } else {
    meetingIdSection.style.display = "none";
  }
}

// Polling de estado 
// Atualiza continuamente a UI consultando o estado do background.js

/** ID do intervalo de polling (para poder limpar depois) */
let _pollInterval = null;

/**
 * Inicia o polling periódico do estado da gravação
 * Faz uma requisição inicial e depois a cada 1 segundo
 * O background.js responde com o estado atual armazenado no chrome.storage
 */
function startPolling() {
  // Função interna que faz uma requisição de estado
  function poll() {
    chrome.runtime.sendMessage({ type: "GET_STATE" }, (state) => {
      // Ignora se houve erro de conexão
      if (chrome.runtime.lastError) return;
      
      // Re-renderiza a UI com o novo estado
      renderState(state || { status: "idle" });
    });
  }
  
  // Faz uma requisição imediata
  poll();
  
  // Depois repete a cada 1000ms (1 segundo)
  _pollInterval = setInterval(poll, 1000);
}

//  Ações 
// Listeners para os botões do popup

/**
 * Botão "Parar gravação": envia mensagem ao background.js para parar e fazer upload
 */
stopBtn.addEventListener("click", () => {
  stopBtn.disabled = true; // Desabilita enquanto processa
  chrome.runtime.sendMessage({ type: "STOP_RECORDING" }, () => {});
});

/**
 * Botão "Abrir Meet Agent": abre a aplicação Streamlit em nova aba
 * Converte a porta 8000 (FastAPI) para 8501 (Streamlit)
 */
openBtn.addEventListener("click", () => {
  chrome.storage.sync.get("meetAgentConfig", (data) => {
    const url = data?.meetAgentConfig?.serverUrl || "http://localhost:8000";
    // Streamlit roda na porta 8501 por padrão
    const streamlitUrl = url.replace(":8000", ":8501");
    chrome.tabs.create({ url: streamlitUrl });
  });
});

/**
 * Botão "Copiar": copia o ID da reunião para a área de transferência
 * Muda o texto do botão como feedback visual
 */
copyBtn.addEventListener("click", () => {
  const id = meetingIdValue.textContent;
  navigator.clipboard.writeText(id).then(() => {
    copyBtn.textContent = "Copiado!";
    // Restaura o texto original após 1.5 segundos
    setTimeout(() => (copyBtn.textContent = "Copiar"), 1500);
  });
});

//  Configurações
// Gerencia gravação automática e URL do servidor

/**
 * Carrega as configurações salvas do chrome.storage
 * Preenche os inputs com valores existentes
 */
function loadConfig() {
  chrome.storage.sync.get("meetAgentConfig", (data) => {
    const cfg = data?.meetAgentConfig || {};
    // Define os valores padrão se não houver configuração salva
    serverUrl.value   = cfg.serverUrl   ?? "http://localhost:8000";
    autoRecord.checked = cfg.autoRecord ?? true;
  });
}

/**
 * Botão "Salvar": persiste as configurações do usuário
 * Armazena URL do servidor e preferência de gravação automática
 */
saveBtn.addEventListener("click", () => {
  const cfg = {
    serverUrl:  serverUrl.value.trim(),   // URL do servidor FastAPI
    autoRecord: autoRecord.checked,       // Habilitar gravação automática?
  };
  
  // Salva no chrome.storage.sync (sincroniza entre dispositivos)
  chrome.storage.sync.set({ meetAgentConfig: cfg }, () => {
    // Mostra mensagem de confirmação
    savedMsg.style.display = "block";
    
    // Esconde a mensagem após 2 segundos
    setTimeout(() => (savedMsg.style.display = "none"), 2000);
  });
});

// Inicialização
// Ao abrir o popup, carrega config e inicia polling

loadConfig();
startPolling();

// Init 

loadConfig();
startPolling();

// Para o polling quando o popup fecha (evita leak)
window.addEventListener("unload", () => clearInterval(_pollInterval));