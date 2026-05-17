"""
presentation/streamlit/app.py

Modo solo  : upload direto → processa na hora → chat.
Modo collab: informa o meeting_id da sala → aguarda processamento → chat.
             (o upload é feito pela extensão Chrome automaticamente)
"""

import sys, os, uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st
from config.settings import get_settings, AppMode
from presetation.container import get_container
from entities.metting import Meeting
from user_cases.transcribe_meeting import TranscribeMeetingInput
from user_cases.summarize_metting import SummarizeMeetingInput
from user_cases.chat_with_meeting import ChatWithMeetingInput

# Import requests para upload em modo colaborativo
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

settings = get_settings()

@st.cache_resource
def get_app_container():
    """Carrega container uma única vez usando cache."""
    return get_container()

container = get_app_container()

st.set_page_config(page_title="Meet Agent", page_icon="🎤", layout="wide")

# ── Session state ─────────────────────────────────────────────────────────

MAX_CHAT_HISTORY = 50  # Limite para evitar consumo excessivo de memória

def _init():
    """Inicializa valores padrão do session state."""
    defaults = {
        "meeting": None,
        "chat_history": [],
        "mode_selected": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

# ── Sidebar ───────────────────────────────────────────────────────────────

def _render_sidebar():
    """Renderiza barra lateral com reuniões salvas."""
    with st.sidebar:
        st.title("🎤 Meet Agent")
        badge = "Solo" if settings.is_solo else "Colaborativo"
        st.caption(f"Modo: **{badge}**")
        st.divider()

        st.subheader("Reuniões salvas")
        try:
            meetings = container.repository.list_all()
        except Exception as e:
            st.error(f"Erro ao carregar reuniões: {str(e)}")
            meetings = []

        for m in meetings:
            label = m.title[:30] + ("..." if len(m.title) > 30 else "")
            if st.button(f"📋 {label}", key=f"load_{m.id}", use_container_width=True):
                st.session_state.meeting = m
                st.session_state.chat_history = []
                st.rerun()

        if st.session_state.meeting:
            st.divider()
            if st.button("✖ Limpar sessão", use_container_width=True):
                st.session_state.meeting = None
                st.session_state.chat_history = []
                st.rerun()

_render_sidebar()

# ── Tela principal ────────────────────────────────────────────────────────

st.title("🎤 Meet Agent")

if st.session_state.meeting is None:
    # ── MODO SOLO: upload manual ──────────────────────────────────
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

            # O resumo foi gerado e anexado à reunião pelo use case
            meeting.summary = s.summary
            st.session_state.meeting = meeting
            st.session_state.chat_history = []
            st.rerun()

    # ── MODO COLLAB: acesso por ID de sala ────────────────────────
    else:
        st.subheader("Entrar em uma sala")
        st.info(
            "A gravação é feita automaticamente pela extensão Chrome "
            "quando você entra no Google Meet.\n\n"
            "Assim que a reunião terminar, informe o ID da sala abaixo."
        )
        meeting_id = st.text_input(
            "ID da sala",
            placeholder="Ex: 3f2a1b4c-...",
            help="Disponível na interface do organizador ou na extensão Chrome.",
        )

        if st.button("Entrar", disabled=not meeting_id, type="primary"):
            meeting = container.repository.find_by_id(meeting_id.strip())  # type: ignore
            if meeting is None:
                st.warning("Reunião não encontrada ou ainda em processamento. Aguarde.")
            else:
                st.session_state.meeting = meeting
                st.session_state.chat_history = []
                st.rerun()

        # Também permite upload manual em modo collab (fallback)
        if HAS_REQUESTS:
            with st.expander("Upload manual (fallback sem extensão Chrome)"):
                f = st.file_uploader("Áudio", type=["wav", "mp3", "m4a", "webm"])
                t2 = st.text_input("Título da reunião")
                if st.button("Enviar para servidor") and f and t2:
                    try:
                        r = requests.post(  # type: ignore
                            f"http://{settings.api_host}:{settings.api_port}/meetings/upload",
                            files={"file": (f.name, f.read(), f.type)},
                            data={"title": t2},
                            timeout=30,
                        )
                        if r.ok:
                            data = r.json()
                            st.success(f"ID da sala: `{data['meeting_id']}`")
                        else:
                            st.error(f"Erro no upload: {r.status_code}")
                    except Exception as e:
                        st.error(f"Erro ao conectar ao servidor: {str(e)}")
        else:
            st.warning("Biblioteca 'requests' não instalada. Upload indisponível.")

# ── Dashboard ─────────────────────────────────────────────────────────────

else:
    meeting: Meeting = st.session_state.meeting
    summary = meeting.summary

    st.subheader(f"📋 {meeting.title}")
    # Formatar data compatível com Windows, Linux e Mac
    date_str = meeting.started_at.strftime("%d de %B de %Y às %H:%M").lstrip("0")
    st.caption(date_str)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("⏱ Duração", f"{meeting.duration_minutes:.0f} min")
    c2.metric("👥 Participantes", len(meeting.participants) or "—")
    c3.metric("✅ Tarefas", len(summary.tasks) if summary else 0)
    c4.metric("🔑 Decisões", len(summary.decisions) if summary else 0)

    st.divider()
    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        if summary:
            st.markdown("### Visão Geral")
            st.write(summary.overview)

            if summary.topics:
                st.markdown("### Tópicos")
                for t in summary.topics:
                    st.markdown(f"- {t}")

            if summary.tasks:
                st.markdown("### Tarefas")
                st.info("📝 Nota: Mudanças em tarefas não são persistidas nesta versão.")
                for idx, task in enumerate(summary.tasks):
                    st.checkbox(
                        f"**{task.description}**  \n*{task.responsible}* · {task.deadline}",
                        value=task.done,
                        key=f"task_{idx}_{task.description[:10]}",
                        disabled=True,
                    )

            if summary.decisions:
                st.markdown("### Decisões")
                for dec in summary.decisions:
                    with st.expander(dec.description):
                        st.write(dec.context or "Sem contexto adicional.")

    with col_right:
        st.markdown("### 💬 Chat")
        chat_box = st.container(height=400)
        with chat_box:
            if not st.session_state.chat_history:
                st.caption("Faça uma pergunta sobre a reunião.")
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])

        if question := st.chat_input("Ex: Quem ficou com a tarefa X?"):
            # Limitar histórico para evitar consumo excessivo de memória
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
                    st.session_state.chat_history.pop()  # Remove a pergunta que causou erro
                    st.stop()

            st.session_state.chat_history.append({"role": "assistant", "content": answer})
            st.rerun()

    st.divider()
    with st.expander("📄 Transcrição completa"):
        st.text(meeting.transcript_formatted or meeting.transcript_text)
        st.download_button(
            "⬇️ Baixar .txt",
            data=meeting.transcript_formatted or meeting.transcript_text,
            file_name=f"{meeting.title}_transcricao.txt",
        )