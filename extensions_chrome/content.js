/**
 * content.js — Injeta na aba do Google Meet.
 *
 * Responsabilidades:
 *   1. Detectar quando o usuário entra em uma sala (URL com código de sala)
 *   2. Detectar quando o usuário sai (botão "Sair da chamada" ou navegação)
 *   3. Capturar o título da reunião do DOM
 *   4. Enviar eventos ao background.js via chrome.runtime.sendMessage
 *
 * O content.js NÃO grava áudio — isso é feito pelo background.js
 * que tem acesso à API chrome.tabCapture.
 */

(function () {
  "use strict";

  // ── Utilitários ──────────────────────────────────────────────────────

  // Padrão para detectar URL de uma sala ativa no Google Meet
  // Aceita diferentes formatos de código: 3-4-3, 3-3-3, etc.
  // Exemplo: meet.google.com/abc-defg-hij ou meet.google.com/qjg-ncrt-wcv
  const MEET_ROOM_PATTERN = /meet\.google\.com\/[a-z]+-[a-z]+-[a-z]+/;

  /**
   * Verifica se o usuário está atualmente dentro de uma sala de reunião
   * @returns {boolean} true se está em uma sala ativa
   */
  function isInRoom() {
    return MEET_ROOM_PATTERN.test(window.location.href);
  }

  /**
   * Extrai o título da reunião do DOM
   * Tenta múltiplos seletores pois Google altera a estrutura conforme versão
   * 
   * @returns {string} Título da reunião ou "Reunião sem título" como fallback
   */
  function getMeetingTitle() {
    // O Meet exibe o nome da reunião em diferentes seletores conforme a versão
    // Tenta: data-meeting-title → data-call-name → jsname="r4nke"
    const selectors = [
      'c-wiz[data-meeting-title]',
      '[data-call-name]',
      'div[jsname="r4nke"]',
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) {
        const title =
          el.getAttribute("data-meeting-title") ||
          el.getAttribute("data-call-name") ||
          el.textContent?.trim();
        if (title) return title;
      }
    }
    // Fallback: usa o título da aba do navegador como última opção
    return document.title.replace(" - Google Meet", "").trim() || "Reunião sem título";
  }

  /**
   * Extrai o código único da sala da URL
   * Código no formato: pode ser 3-4-3, 3-3-3, ou outros formatos
   * 
   * @returns {string|null} Código da sala ou null se não encontrado
   */
  function getMeetingCode() {
    const match = window.location.href.match(/meet\.google\.com\/([a-z]+-[a-z]+-[a-z]+)/);
    return match ? match[1] : null;
  }

  // ── Estado local ──────────────────────────────────────────────────────
  
  /** Flag indicando se o usuário está atualmente em uma sala */
  let _inRoom = false;
  
  /** ID do intervalo de polling que tenta capturar o título real */
  let _titlePollingInterval = null;
  
  /** Armazena o título resolvido da reunião atual */
  let _resolvedTitle = "";

  // ── Funções principais ────────────────────────────────────────────────

  /**
   * Executado quando o usuário entra em uma sala de reunião
   * Envia mensagem ao background.js para iniciar a gravação
   */
  function onEnterRoom() {
    if (_inRoom) return; // Evita disparar múltiplas vezes
    _inRoom = true;

    const code = getMeetingCode();
    const title = getMeetingTitle();
    _resolvedTitle = title;

    // Notifica background.js que uma reunião começou
    chrome.runtime.sendMessage({
      type: "MEET_STARTED",
      payload: { code, title, url: window.location.href },
    });

    // Continua tentando capturar o título real (pode demorar para aparecer no DOM)
    // O título inicial pode estar vazio ou incompleto, espera-se a atualização
    _titlePollingInterval = setInterval(() => {
      const t = getMeetingTitle();
      if (t && t !== _resolvedTitle && t !== "Reunião sem título") {
        _resolvedTitle = t;
        // Envia atualização do título quando encontrado
        chrome.runtime.sendMessage({
          type: "MEET_TITLE_UPDATED",
          payload: { code, title: t },
        });
        clearInterval(_titlePollingInterval);
      }
    }, 2000); // Verifica a cada 2 segundos
  }

  /**
   * Executado quando o usuário sai de uma sala de reunião
   * Para a gravação e notifica o background.js
   */
  function onLeaveRoom() {
    if (!_inRoom) return; // Evita disparar múltiplas vezes
    _inRoom = false;
    clearInterval(_titlePollingInterval);

    // Notifica background.js que a reunião acabou
    chrome.runtime.sendMessage({
      type: "MEET_ENDED",
      payload: { title: _resolvedTitle },
    });
  }

  // ── Observa mudanças de URL (SPA — sem reload de página) ──────────────
  // Google Meet é uma Single Page Application (SPA), então a URL muda sem recarregar
  // Precisamos monitorar essas mudanças para detectar entrada/saída de salas

  let _lastHref = window.location.href;

  const urlObserver = new MutationObserver(() => {
    if (window.location.href !== _lastHref) {
      _lastHref = window.location.href;

      // Se a nova URL está em uma sala, dispara entrada
      // Caso contrário, dispara saída
      if (isInRoom()) {
        onEnterRoom();
      } else {
        onLeaveRoom();
      }
    }
  });

  urlObserver.observe(document.body, { childList: true, subtree: true });

  // ── Detecta clique no botão "Sair da chamada" ─────────────────────────
  // Complementa a detecção por URL, caso o usuário clique no botão sem recarregar a página
  document.addEventListener("click", (e) => {
    const btn = e.target?.closest('[aria-label*="Sair"], [aria-label*="Leave"]');
    if (btn) {
      onLeaveRoom();
    }
  }, true);

  // ── Detecta fechamento da aba ─────────────────────────────────────────
  // Se o usuário fechar a aba enquanto em uma reunião, notifica o término
  window.addEventListener("beforeunload", () => {
    if (_inRoom) onLeaveRoom();
  });

  // ── Inicialização ─────────────────────────────────────────────────────
  // Se já está em uma sala ao carregar o content.js, inicia o monitoramento
  if (isInRoom()) {
    // Aguarda DOM estar pronto antes de capturar título (1.5s de delay)
    setTimeout(onEnterRoom, 1500);
  }
})();