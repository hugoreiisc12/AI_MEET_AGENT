"""
presentation/streamlit/app.py

Envia o bot para um link do Google Meet, aguarda o processamento e abre o chat.

S5 — Bot roda em processo separado (run_bot.py) para evitar loop infinito
e problemas de event loop no Windows. UI acompanha via polling de JSON.
"""

import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st
from config.settings import get_settings
from presentation.container import get_container, get_mongo_fallback_warning
from domain.entities.meeting import Meeting
from use_cases.chat_with_meeting import ChatWithMeetingInput
from infrastructure.email.email_sender import EmailSender
from infrastructure.pipeline.meeting_pipeline_orchestrator import MeetingPipelineOrchestrator


try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

settings = get_settings()
AUDIO_DIR = Path(settings.audio_storage_path)

@st.cache_resource
def get_app_container():
    return get_container()

container = get_app_container()

st.set_page_config(page_title="Meet Agent", page_icon="🎤", layout="wide")

if warn := get_mongo_fallback_warning():
    st.warning(f"**MongoDB indisponível** — {warn}", icon="⚠️")

MAX_CHAT_HISTORY = 50

def _init():
    defaults = {
        "meeting": None,
        "chat_history": [],
        "chat_mode": False,
        "mode_selected": False,
        "pending_task": None,
        "task_email_sent": False,
        "task_email_content": "",
        "bot_process": None,
        "bot_session_id": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

def _bot_is_running() -> bool:
    proc = st.session_state.get("bot_process")
    return proc is not None and proc.poll() is None

def _start_bot(meeting_url: str) -> None:
    """S5 — Lança o bot em PROCESSO separado."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "infrastructure.recorder.run_bot",
         "--url", meeting_url],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    st.session_state.bot_process = proc
    st.session_state.bot_session_id = None

def _read_bot_status() -> dict | None:
    """Lê o JSON de status mais recente do bot."""
    proc = st.session_state.get("bot_process")
    if proc is None:
        return None
    if st.session_state.get("bot_session_id") is None and proc.poll() is not None:
        out = (proc.stdout.read() or "").strip().splitlines()
        if out:
            st.session_state.bot_session_id = out[0]
    sid = st.session_state.get("bot_session_id")
    if not sid:
        candidates = sorted(
            AUDIO_DIR.glob("bot_session_*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not candidates:
            return None
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    path = AUDIO_DIR / f"bot_session_{sid}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

def _render_sidebar():
    with st.sidebar:
        st.title("🎤 Meet Agent")
        badge = "Solo" if settings.is_solo else "Colaborativo"
        st.caption(f"Modo: **{badge}**")
        st.divider()

        st.subheader("Reuniões salvas")
        col_refresh, _ = st.columns([1, 3])
        with col_refresh:
            if st.button("🔄 Atualizar", use_container_width=True):
                st.rerun()

        try:
            meetings = container.repository.list_all()
        except Exception as e:
            st.error(f"Erro ao carregar reuniões: {str(e)}")
            meetings = []

        processing_count = 0
        for m in meetings:
            status = MeetingPipelineOrchestrator.get_pipeline_status(m)
            if status == "done":
                icon = "✅"
            elif status == "transcribing":
                icon = "⏳"
                processing_count += 1
            elif status == "pending":
                icon = "⏸️"
                processing_count += 1
            else:
                icon = "❌"

            label = m.title[:30] + ("..." if len(m.title) > 30 else "")
            if st.button(f"{icon} {label}", key=f"load_{m.id}", use_container_width=True):
                st.session_state.meeting = m
                st.session_state.chat_history = []
                st.session_state.chat_mode = False
                st.rerun()

        if HAS_AUTOREFRESH:
            bot_running = _bot_is_running()
            if bot_running or processing_count > 0:
                st_autorefresh(interval=10_000, key="direct_query_autorefresh")
                if bot_running:
                    st.caption("🤖 Bot em reunião — status a cada 10s")
                else:
                    st.caption(f"⚡ {processing_count} reunião(ões) processando")

        if st.session_state.meeting:
            st.divider()
            if st.button("✖ Limpar sessão", use_container_width=True):
                st.session_state.meeting = None
                st.session_state.chat_history = []
                st.rerun()

_render_sidebar()

st.title("🎤 Meet Agent")

if st.session_state.meeting is None:
    st.subheader("Enviar bot para a reunião")

    bot_running = _bot_is_running()
    if bot_running:
        st.info("🤖 Bot está ativo em uma reunião.")
        status = _read_bot_status()
        if status:
            st.caption(f"Status: {status.get('status', 'desconhecido')}")
            if status.get("error"):
                st.error(status["error"])

    col_form, col_status = st.columns([1, 1], gap="large")

    with col_form:
        st.markdown("### 🤖 Enviar bot")
        default_meet_url = ""
        default_title = ""
        if getattr(container, "calendar_event", None):
            default_meet_url = container.calendar_event.meet_url if container.calendar_event else ""
            default_title = container.calendar_event.title if container.calendar_event else ""

        meet_url = st.text_input(
            "Link do Google Meet",
            placeholder="https://meet.google.com/xxx-yyyy-zzz",
            value=default_meet_url,
        )
        meeting_title = st.text_input(
            "Título da reunião",
            placeholder="Sprint Planning — Semana 22",
            value=default_title,
        )

        if st.button(
            "🚀 Enviar bot para a reunião",
            disabled=bot_running or not (meet_url and meeting_title),
            type="primary",
            use_container_width=True,
        ):
            _start_bot(meet_url)
            st.success("✅ Bot iniciado em processo separado.")
            st.info(
                "O bot está entrando na reunião. Acompanhe o status no painel. "
                "Quando a reunião terminar, o resumo aparecerá no histórico."
            )

    with col_status:
        st.markdown("### 📋 Como funciona")
        st.markdown("""
        1. Cole o link do Google Meet
        2. Clique em **Enviar bot**
        3. O **Meet Agent 🤖** entra na reunião como participante
        4. Quando a reunião terminar, ele sai automaticamente
        5. O áudio é transcrito e o resumo fica disponível aqui

        **Nota:** Use uma conta Google dedicada para o bot.
        Configure com: `python infrastructure/recorder/bot_setup.py`
        """)

    st.divider()
    st.markdown("### 🔍 Buscar reunião processada")
    search_id = st.text_input(
        "ID da reunião",
        placeholder="Cole o ID gerado após o processamento",
    )
    if st.button("Buscar", disabled=not search_id):
        found_meeting: Meeting | None = container.repository.find_by_id(search_id.strip())
        if found_meeting and found_meeting.is_summarized:
            st.session_state.meeting = found_meeting
            st.session_state.chat_history = []
            st.rerun()
        else:
            st.warning("Reunião não encontrada ou ainda em processamento.")

if st.session_state.meeting is None:
    st.info("Selecione ou carregue uma reunião para ver o dashboard.")
elif st.session_state.get("chat_mode"):
    meeting: Meeting = st.session_state.meeting
    if meeting is None:
        st.warning("Reunião não selecionada.")
        st.stop()

    st.subheader(f"💬 Consulta sobre: {meeting.title}")
    st.markdown(f"**Meeting ID:** `{meeting.id}`")
    st.divider()

    chat_box = st.container(height=400)
    with chat_box:
        if not st.session_state.chat_history:
            st.caption("Faça uma pergunta sobre a reunião.")
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

    if question := st.chat_input("Ex: Quem ficou com a tarefa X?"):
        if len(st.session_state.chat_history) >= MAX_CHAT_HISTORY:
            st.session_state.chat_history = st.session_state.chat_history[-MAX_CHAT_HISTORY:]

        st.session_state.chat_history.append({"role": "user", "content": question})

        with st.spinner("Pensando..."):
            try:
                result = container.chat_with_meeting.execute(
                    ChatWithMeetingInput(
                        meeting=meeting,
                        question=question,
                        history=st.session_state.chat_history[:-1],
                    )
                )
                answer = result.answer if result.success else f"⚠️ {result.error_message}"
            except Exception as e:
                st.error(f"Erro no chat: {str(e)}")
                st.session_state.chat_history.pop()
                st.stop()

        st.session_state.chat_history.append({"role": "assistant", "content": answer})

        if result.success and result.task_data:
            st.session_state.pending_task = result.task_data
            st.session_state.task_email_sent = False
            st.session_state.task_email_content = ""

        st.rerun()

    pending = st.session_state.pending_task
    if pending and not st.session_state.task_email_sent:
        st.divider()
        st.markdown("### 📋 Confirmação de Tarefa")
        st.info("O agente identificou uma tarefa. Confirme os dados abaixo:")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Nome:** {pending.get('nome', '—')}")
            st.markdown(f"**Responsável:** {pending.get('responsavel', '—')}")
            st.markdown(f"**Destinatário:** {pending.get('destinatario', '—')}")
        with col2:
            st.markdown(f"**Prazo:** {pending.get('prazo', 'Indefinido')}")
            st.markdown(f"**E-mail:** {pending.get('email', '—')}")
            st.markdown(f"**Criada em:** {pending.get('criada_em', '—')}")

        st.markdown("**Descrição:**")
        st.write(pending.get("descricao", "Sem descrição"))

        c_confirm, c_cancel, _ = st.columns([1, 1, 4])
        with c_confirm:
            if st.button("✅ Confirmar e Enviar Tarefa", type="primary", use_container_width=True):
                with st.spinner("Enviando tarefa por e-mail..."):
                    try:
                        sender = EmailSender()
                        to_email = pending.get("email", "").strip() or settings.notification_email
                        if not to_email:
                            st.error(
                                "E-mail do destinatário não informado na tarefa e "
                                "NOTIFICATION_EMAIL não configurado no .env."
                            )
                            st.stop()

                        meeting = st.session_state.meeting
                        meeting_title = meeting.title if meeting else "Reunião"
                        meeting_date = meeting.started_at.strftime("%d/%m/%Y às %H:%M") if meeting and meeting.started_at else ""
                        meeting_link = f"Meet Agent - {meeting.id}" if meeting else ""

                        sender.send_task_email(
                            to_email=to_email,
                            task_data=pending,
                            meeting_title=meeting_title,
                            meeting_date=meeting_date,
                            meeting_link=meeting_link,
                        )

                        st.session_state.task_email_sent = True

                        from infrastructure.llm.langchain_llm_service import LangChainLLMService
                        email_content = LangChainLLMService.generate_task_email_content(pending, meeting)
                        st.session_state.task_email_content = email_content

                        st.success(f"✅ Tarefa enviada com sucesso para {to_email}!")
                        st.rerun()
                    except Exception as e:
                        error_msg = str(e)
                        if "SMTPAuthenticationError" in error_msg or "Username and Password not accepted" in error_msg:
                            st.error(
                                "🔑 Senha de App do Gmail inválida ou expirada. "
                                "Gere uma nova em: https://myaccount.google.com/apppasswords\n"
                                "Use a senha gerada no campo SMTP_PASSWORD do .env."
                            )
                        else:
                            st.error(f"Erro ao enviar tarefa: {error_msg}")

        with c_cancel:
            if st.button("✏️ Editar / Cancelar", use_container_width=True):
                st.session_state.pending_task = None
                st.rerun()

    if st.session_state.task_email_sent and st.session_state.task_email_content:
        st.divider()
        st.markdown("### 📧 Tarefa Enviada")
        st.text_area("Conteúdo do e-mail", st.session_state.task_email_content, height=400)
        st.download_button(
            "⬇️ Baixar .txt",
            data=st.session_state.task_email_content,
            file_name="tarefa_meeting.txt",
        )
        if st.button("✖ Limpar confirmação"):
            st.session_state.pending_task = None
            st.session_state.task_email_content = ""
            st.session_state.task_email_sent = False
            st.rerun()

    col_back, _ = st.columns([1, 5])
    with col_back:
        if st.button("← Voltar aos detalhes"):
            st.session_state.chat_mode = False
            st.session_state.pending_task = None
            st.rerun()

else:
    meeting: Meeting = st.session_state.meeting
    if meeting is None:
        st.warning("Reunião não selecionada.")
        st.stop()
    summary = meeting.summary

    st.subheader(f"📋 {meeting.title}")
    st.markdown(f"**Meeting ID:** `{meeting.id}`")
    date_str = meeting.started_at.strftime("%d de %B de %Y às %H:%M").lstrip("0")
    st.caption(date_str)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("⏱ Duração", f"{meeting.duration_minutes:.0f} min")
    c2.metric("👥 Participantes", len(meeting.participants) or "—")
    c3.metric("✅ Tarefas", len(summary.tasks) if summary else 0)
    c4.metric("🔑 Decisões", len(summary.decisions) if summary else 0)

    st.divider()

    if summary:
        st.markdown("### Visão Geral")
        st.write(summary.overview)

        if summary.topics:
            col_top, col_chat = st.columns([1, 1], gap="large")
            with col_top:
                st.markdown("### Tópicos")
                for t in summary.topics:
                    st.markdown(f"- {t}")

            with col_chat:
                st.markdown("### 💬 Agent")
                st.write("Faça perguntas sobre a reunião com o agente de IA.")
                if st.button("🚀 Iniciar consulta com Agent", type="primary", use_container_width=True):
                    st.session_state.chat_history = []
                    st.session_state.chat_mode = True
                    st.rerun()
        else:
            st.markdown("### Tópicos")
            for t in summary.topics:
                st.markdown(f"- {t}")

        if summary.tasks:
            st.markdown("### Tarefas")
            st.info("📝 Nota: Mudanças em tarefas não são persistidas nesta versão.")
            for idx, task in enumerate(summary.tasks):
                st.checkbox(
                    f"**{task.description}**  \n*{task.responsible}* · {task.deadline}",
                    value=getattr(task, "done", False),
                    key=f"task_{idx}_{task.description[:10]}",
                    disabled=True,
                )

        if summary.decisions:
            st.markdown("### Decisões")
            for dec in summary.decisions:
                with st.expander(dec.description):
                    st.write(dec.context or "Sem contexto adicional.")

        st.divider()
        if st.button("💬 Iniciar consulta com Agent", type="primary", use_container_width=True):
            st.session_state.chat_history = []
            st.session_state.chat_mode = True
            st.rerun()

    st.divider()
    with st.expander("📄 Transcrição completa"):
        st.text(meeting.transcript_formatted or meeting.transcript_text)
        st.download_button(
            "⬇️ Baixar .txt",
            data=meeting.transcript_formatted or meeting.transcript_text,
            file_name=f"{meeting.title}_transcricao.txt",
        )