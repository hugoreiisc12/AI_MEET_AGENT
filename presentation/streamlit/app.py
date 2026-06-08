"""
presentation/streamlit/app.py

Modo solo  : upload direto → processa na hora → chat.
Modo collab: informa o meeting_id da sala → aguarda processamento → chat.
             (o bot entra automaticamente via Playwright quando configurado)
"""

import sys, os, uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st
from config.settings import get_settings, AppMode
from presentation.container import get_container
from domain.entities.meeting import Meeting
from use_cases.transcribe_meeting import TranscribeMeetingInput
from use_cases.summarize_meeting import SummarizeMeetingInput
from use_cases.chat_with_meeting import ChatWithMeetingInput

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

settings = get_settings()

@st.cache_resource
def get_app_container():
    return get_container()

container = get_app_container()

st.set_page_config(page_title="Meet Agent", page_icon="🎤", layout="wide")

MAX_CHAT_HISTORY = 50

def _init():
    defaults = {
        "meeting": None,
        "chat_history": [],
        "chat_mode": False,
        "mode_selected": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

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

        for m in meetings:
            label = m.title[:35] + ("..." if len(m.title) > 35 else "")
            if st.button(f"📋 {label}", key=f"load_{m.id}", use_container_width=True):
                st.session_state.meeting = m
                st.session_state.chat_history = []
                st.session_state.chat_mode = False
                st.rerun()

        # Auto-refresh enquanto houver bot ativo
        if HAS_AUTOREFRESH and hasattr(container, "record_meeting") and container.record_meeting:
            active = container.record_meeting.list_active_sessions()
            if active:
                st_autorefresh(interval=10_000, key="bot_autorefresh")
                st.caption(f"🤖 {len(active)} bot(s) ativo(s) — atualizando a cada 10s")

        if st.session_state.meeting:
            st.divider()
            if st.button("✖ Limpar sessão", use_container_width=True):
                st.session_state.meeting = None
                st.session_state.chat_history = []
                st.rerun()

_render_sidebar()

st.title("🎤 Meet Agent")

if st.session_state.meeting is None:
    if settings.is_solo:
        st.subheader("Nova reunião")
        title = st.text_input("Título", placeholder="Sprint Planning — Semana 22")
        audio_file = st.file_uploader(
            "Arquivo de áudio",
            type=["wav", "mp3", "m4a", "webm", "ogg"],
        )
        use_diarization = st.toggle("Identificar speakers", value=True)

        if st.button("🚀 Processar", disabled=not (title and audio_file), type="primary"):
            if not audio_file:
                st.error("Selecione um arquivo de áudio")
                st.stop()

            audio_dir = Path(settings.audio_storage_path)
            audio_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(audio_file.name).suffix
            audio_path = str(audio_dir / f"{uuid.uuid4()}{suffix}")
            with open(audio_path, "wb") as f:
                f.write(audio_file.read())

            with st.spinner("Transcrevendo..."):
                t = container.transcribe_meeting.execute(
                    TranscribeMeetingInput(audio_path=audio_path,
                                          with_diarization=use_diarization)
                )
            if not t.success:
                st.error(t.error_message)
                st.stop()

            meeting = Meeting(
                id=str(uuid.uuid4()), title=title,
                started_at=datetime.now(), audio_path=audio_path,
                transcript_text=t.transcript.full_text,
                transcript_formatted=t.transcript.formatted,
                participants=t.transcript.speakers,
                duration_minutes=t.transcript.duration_minutes,
            )

            with st.spinner("Gerando resumo..."):
                s = container.summarize_meeting.execute(
                    SummarizeMeetingInput(meeting=meeting)
                )
            if not s.success:
                st.error(s.error_message)
                st.stop()

            meeting.summary = s.summary
            st.session_state.meeting = meeting
            st.session_state.chat_history = []
            st.rerun()

    else:
        st.subheader("Enviar bot para a reunião")

        if hasattr(container, "record_meeting") and container.record_meeting:
            active = container.record_meeting.list_active_sessions()
            if active:
                st.info(f"🤖 Bot ativo em {len(active)} reunião(ões)")
                for s in active:
                    st.caption(f"Session {s.session_id} — {s.status} — {s.duration_seconds/60:.1f} min")

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
                disabled=not (meet_url and meeting_title),
                type="primary",
                use_container_width=True,
            ):
                if not hasattr(container, "record_meeting") or not container.record_meeting:
                    st.error(
                        "Bot não configurado. Adicione no `.env`:\n"
                        "```\nRECORDER_PROVIDER=playwright\n"
                        "BOT_GOOGLE_EMAIL=seubot@gmail.com\n"
                        "BOT_GOOGLE_PASSWORD=senha\n```\n"
                        "E execute: `python bot_setup.py`"
                    )
                else:
                    with st.spinner("Enviando bot para a reunião..."):
                        from use_cases.record_meeting import SendBotInput

                        import uuid as _uuid_lib

                        safe_meet_url = meet_url or ""
                        meeting_id = str(_uuid_lib.uuid4())

                        def on_done(
                            audio_path: str,
                            title: str,
                            participant_info: dict[str, str],
                            speaker_observations: list[dict[str, float | str]],
                            mid: str,
                        ) -> None:
                            """Dispara o pipeline completo (transcrever → sumarizar → salvar)."""
                            c = get_container()
                            c.pipeline_orchestrator.run_pipeline(
                                meeting_id=mid,
                                audio_path=audio_path,
                                title=title,
                                participant_info=participant_info or {},
                                speaker_observations=speaker_observations or [],
                            )
                            print(f"[Bot] ✅ Pipeline disparado: {title} ({mid})")

                        result = container.record_meeting.send_bot(
                            SendBotInput(
                                meeting_url=safe_meet_url,
                                title=meeting_title,
                                meeting_id=meeting_id,
                                on_finished=on_done,
                            )
                        )

                    if result.success:
                        st.success("✅ Bot enviado! Ele está entrando na reunião agora.")
                        st.info(
                            f"**Meeting ID:** `{meeting_id}`\n\n"
                            "Quando a reunião terminar, o resumo aparecerá automaticamente "
                            "no histórico de reuniões."
                        )
                    else:
                        st.error(f"Erro: {result.error_message}")

        with col_status:
            st.markdown("### 📋 Como funciona")
            st.markdown("""
            1. Cole o link do Google Meet
            2. Clique em **Enviar bot**
            3. O **Meet Agent 🤖** entra na reunião como participante
            4. Quando a reunião terminar, ele sai automaticamente
            5. O áudio é transcrito e o resumo fica disponível aqui

            **Nota:** Use uma conta Google dedicada para o bot.
            Configure com `python bot_setup.py`.
            """)

        st.divider()
        st.markdown("### 🔍 Buscar reunião processada")
        meeting_id = st.text_input(
            "ID da reunião",
            placeholder="Cole o ID gerado após o processamento",
        )
        if st.button("Buscar", disabled=not meeting_id):
            found_meeting: Meeting | None = container.repository.find_by_id(meeting_id.strip())
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

    chat_box = st.container(height=500)
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
        st.rerun()

    col_back, _ = st.columns([1, 5])
    with col_back:
        if st.button("← Voltar aos detalhes"):
            st.session_state.chat_mode = False
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