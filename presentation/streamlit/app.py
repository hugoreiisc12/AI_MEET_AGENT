"""
presentation/streamlit/app.py

Modo solo  : upload direto → processa na hora → dashboard.
Modo collab: informa o meeting_id da sala → aguarda processamento → dashboard.
             (o bot entra automaticamente via Playwright em processo separado - S5)

Telas:
  - 📋 Reuniões   → dashboard da reunião (sem chat integrado)
  - 💬 Chat       → chat interativo dedicado com Ollama + LangChain
"""

import sys, os, uuid, subprocess, json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st
from config.settings import get_settings, AppMode
from presentation.container import get_container
from domain.entities.meeting import Meeting, Summary
from use_cases.transcribe_meeting import TranscribeMeetingInput
from use_cases.summarize_meeting import SummarizeMeetingInput
from use_cases.chat_with_meeting import ChatWithMeetingInput

settings = get_settings()
AUDIO_DIR = Path(settings.audio_storage_path)

@st.cache_resource
def get_app_container():
    return get_container()

container = get_app_container()

st.set_page_config(page_title="Meet Agent", page_icon="🎤", layout="wide")

MAX_CHAT_HISTORY = 50

_SECTION_EMOJI = {
    "went_well": "✅", "to_improve": "🔧", "action_items": "📌",
    "risks": "⚠️", "delivered": "📦", "not_delivered": "⏳",
    "stakeholder_feedback": "💬", "feedbacks": "🔄",
    "strengths": "💪", "concerns": "🚩", "recommendation": "🎯",
    "ideas": "💡",
}

_PAGES = {
    "📋 Reuniões": "meetings",
    "💬 Chat Interativo": "chat",
}

def _init():
    defaults = {
        "page": "meetings",
        "meeting": None,
        "chat_history": [],
        "chat_meeting_id": None,
        "chat_history_store": {},
        "mode_selected": False,
        "bot_process": None,
        "bot_session_id": None,
        "refresh_queue": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


def bot_is_running() -> bool:
    proc = st.session_state.get("bot_process")
    return proc is not None and proc.poll() is None


def start_bot(meeting_url: str) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "infrastructure.recorder.run_bot",
         "--url", meeting_url],
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
    )
    st.session_state.bot_process = proc
    st.session_state.bot_session_id = None


def read_bot_status() -> dict | None:
    proc = st.session_state.get("bot_process")
    if proc is None:
        return None
    if st.session_state.get("bot_session_id") is None and proc.poll() is not None:
        out = (proc.stdout.read() or "").strip().splitlines()
        if out:
            st.session_state.bot_session_id = out[0]
    sid = st.session_state.get("bot_session_id")
    if not sid:
        candidates = sorted(AUDIO_DIR.glob("bot_session_*.json"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return None
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    path = AUDIO_DIR / f"bot_session_{sid}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


_SECTION_LABELS = {
    "went_well": "O que foi bem", "to_improve": "O que melhorar",
    "action_items": "Ações", "risks": "Riscos",
    "delivered": "Entregue", "not_delivered": "Não entregue",
    "stakeholder_feedback": "Feedback", "feedbacks": "Feedbacks",
    "strengths": "Pontos Fortes", "concerns": "Pontos de Atenção",
    "recommendation": "Recomendação", "ideas": "Ideias",
}

def render_extra_sections(summary) -> None:
    if not summary or not getattr(summary, "extra_sections", None):
        return
    for key, value in summary.extra_sections.items():
        emoji = _SECTION_EMOJI.get(key, "📌")
        label = _SECTION_LABELS.get(key, key.replace("_", " ").title())
        st.markdown(f"### {emoji} {label}")
        if isinstance(value, str):
            st.write(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    # action_items, feedbacks, ideas — dicts estruturados
                    st.markdown("- " + " — ".join(
                        f"**{k}**: {v}" for k, v in item.items()))
                else:
                    st.markdown(f"- {item}")
        else:
            st.write(value)


with st.sidebar:
    st.title("🎤 Meet Agent")
    badge = "Solo" if settings.is_solo else "Colaborativo"
    st.caption(f"Modo: **{badge}**")
    st.divider()

    page_label = st.radio(
        "Navegação",
        options=list(_PAGES.keys()),
        index=0 if st.session_state.page == "meetings" else 1,
        label_visibility="collapsed",
    )
    st.session_state.page = _PAGES[page_label]
    st.divider()

    if st.session_state.page == "meetings":
        st.subheader("Reuniões salvas")

        col_refresh, col_badge = st.columns([3, 1])
        with col_refresh:
            if st.button("🔄 Refresh", use_container_width=True, type="secondary"):
                try:
                    if hasattr(container, "collection_agent"):
                        count = container.collection_agent.poll()
                        if count > 0:
                            st.toast(f"{count} nova(s) reunião(ões) encontrada(s)!", icon="🆕")
                except Exception:
                    pass
                st.rerun()

        pending = container.collection_agent.pending_count if hasattr(container, "collection_agent") else 0
        with col_badge:
            if pending > 0:
                st.markdown(f"**<span style='color:#ff6b6b'>📬 {pending}</span>**", unsafe_allow_html=True)
            else:
                st.markdown("**📭 0**")

        st.divider()

        queued_meetings: list[Meeting] = []
        try:
            if hasattr(container, "collection_agent"):
                queued_meetings = container.collection_agent.drain_queue()
        except Exception:
            pass

        st.session_state.refresh_queue.extend(queued_meetings)
        if queued_meetings:
            st.toast(f"📥 {len(queued_meetings)} reunião(ões) da fila adicionada(s)!", icon="📬")

        all_meetings: list = []
        new_ids: set = set()
        try:
            all_meetings = container.repository.list_all()
            known_ids = st.session_state.get("_known_meeting_ids") or []
            known = set(known_ids)
            new_ids = set(m.id for m in all_meetings) - known
            if new_ids:
                merged = list(known | new_ids)
                st.session_state._known_meeting_ids = merged
        except Exception as e:
            st.error(f"Erro ao carregar reuniões: {str(e)}")

        if st.session_state.get("_known_meeting_ids") is None:
            st.session_state._known_meeting_ids = [m.id for m in all_meetings]

        for m in all_meetings:
            is_new = m.id in new_ids
            prefix = "🆕 " if is_new else "📋 "
            label = m.title[:30] + ("..." if len(m.title) > 30 else "")
            if st.button(f"{prefix}{label}", key=f"load_{m.id}", use_container_width=True):
                st.session_state.meeting = m
                st.rerun()

        if st.session_state.refresh_queue:
            st.divider()
            st.caption("📬 Fila de refresh:")
            for m in st.session_state.refresh_queue:
                qlabel = m.title[:30] + ("..." if len(m.title) > 30 else "")
                if st.button(f"📬 {qlabel}", key=f"queued_{m.id}", use_container_width=True):
                    st.session_state.meeting = m
                    st.rerun()

        if st.session_state.meeting:
            st.divider()
            if st.button("✖ Limpar sessão", use_container_width=True):
                st.session_state.meeting = None
                st.rerun()


if st.session_state.page == "meetings":

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
                    transcript_raw=t.transcript.text_raw,
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
                st.rerun()

        else:
            st.subheader("Enviar bot para a reunião")

            col_form, col_status = st.columns([1, 1], gap="large")

            with col_form:
                st.markdown("### 🤖 Enviar bot")
                meet_url = st.text_input(
                    "Link do Google Meet",
                    placeholder="https://meet.google.com/xxx-yyyy-zzz",
                )
                meeting_title = st.text_input(
                    "Título da reunião",
                    placeholder="Sprint Planning — Semana 22",
                )

                if st.button(
                    "🚀 Enviar bot para a reunião",
                    disabled=not (meet_url and meeting_title) or bot_is_running(),
                    type="primary",
                    use_container_width=True,
                ):
                    start_bot(meet_url)
                    st.success("✅ Bot iniciado em processo separado!")

                status = read_bot_status()
                if status:
                    st.metric("Status do bot", status["status"])
                    if status.get("error"):
                        st.error(status["error"])

            with col_status:
                st.markdown("### 📋 Como funciona")
                st.markdown("""
                1. Cole o link do Google Meet
                2. Clique em **Enviar bot**
                3. O **Meet Agent 🤖** entra na reunião como participante
                4. O bot grava o áudio da reunião enquanto estiver ativo
                5. Quando a reunião terminar, ele sai automaticamente
                6. O áudio é transcrito e o resumo fica disponível aqui

                **Nota:** Use uma conta Google dedicada para o bot.
                Configure com: `python -m infrastructure.recorder.bot_setup`
                """)

            st.divider()
            st.markdown("### 🔍 Buscar reunião processada")
            meeting_id = st.text_input(
                "ID da reunião",
                placeholder="Cole o ID gerado após o processamento",
            )
            if st.button("Buscar", disabled=not meeting_id):
                found_meeting = container.repository.find_by_id(meeting_id.strip())
                if found_meeting and found_meeting.is_summarized:
                    st.session_state.meeting = found_meeting
                    st.rerun()
                else:
                    status_messages = {
                        "queued": "⏳ Aguardando processamento...",
                        "transcribing": "🎤 Transcrevendo áudio...",
                        "summarizing": "📝 Gerando resumo...",
                        "done": "✅ Processamento concluído!",
                        "error": "❌ Erro ao processar.",
                    }
                    try:
                        from worker.tasks import get_task_status
                        status = get_task_status(meeting_id.strip())
                        msg = status_messages.get(status, f"Status: {status}")
                    except:
                        msg = "Reunião não encontrada."
                    st.info(msg)

    else:
        meeting: Meeting = st.session_state.meeting
        if meeting is None:
            st.warning("Reunião não selecionada.")
            st.stop()
        summary = meeting.summary

        st.subheader(f"📋 {meeting.title}")
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
                st.markdown("### Tópicos")
                for t in summary.topics:
                    st.markdown(f"- {t}")

            if summary.tasks:
                st.markdown("### Tarefas")
                st.info("📝 Nota: Mudanças em tarefas não são persistidas nesta versão.")
                for idx, task in enumerate(summary.tasks):
                    task_label = f"**{task.description}**  \n*{task.responsible}* · {task.deadline}"
                    st.checkbox(
                        task_label,
                        value=getattr(task, "done", False),
                        key=f"task_{idx}_{task.description[:10]}",
                        disabled=True,
                    )

            if summary.decisions:
                st.markdown("### Decisões")
                for dec in summary.decisions:
                    with st.expander(dec.description):
                        st.write(dec.context or "Sem contexto adicional.")

            render_extra_sections(summary)

        st.divider()
        with st.expander("📄 Transcrição completa"):
            st.text(meeting.transcript_formatted or meeting.transcript_text)
            st.download_button(
                "⬇️ Baixar .txt",
                data=meeting.transcript_formatted or meeting.transcript_text,
                file_name=f"{meeting.title}_transcricao.txt",
            )

elif st.session_state.page == "chat":

    st.title("💬 Chat Interativo com IA")
    st.caption("Ollama · PromptBuilder · LangChain")

    try:
        meetings = container.repository.list_all()
    except Exception as e:
        st.error(f"Erro ao carregar reuniões: {str(e)}")
        meetings = []

    transcribed = [m for m in meetings if m.is_transcribed]

    if not transcribed:
        st.info("Nenhuma reunião transcrita disponível para chat.")
        st.stop()

    meeting_options = {f"{m.title[:50]} — {m.id[:8]}...": m for m in transcribed}
    selected_label = st.selectbox(
        "Selecione uma reunião para conversar:",
        options=list(meeting_options.keys()),
        index=0,
    )
    chat_meeting = meeting_options[selected_label]

    if st.session_state.chat_meeting_id != chat_meeting.id:
        st.session_state.chat_meeting_id = chat_meeting.id
        if chat_meeting.id not in st.session_state.chat_history_store:
            st.session_state.chat_history_store[chat_meeting.id] = []
        st.rerun()

    chat_history = st.session_state.chat_history_store.setdefault(chat_meeting.id, [])

    st.markdown("---")
    col_meta, _ = st.columns([2, 3])
    with col_meta:
        st.markdown(f"**{chat_meeting.title}**")
        st.caption(
            f"{len(chat_meeting.participants)} participantes · "
            f"{chat_meeting.duration_minutes:.0f} min · "
            f"{chat_meeting.started_at.strftime('%d/%m/%Y %H:%M')}"
        )

    st.divider()

    chat_container = st.container(height=500, border=True)
    with chat_container:
        if not chat_history:
            st.caption("Faça uma pergunta sobre esta reunião.")
        for msg in chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

    if prompt := st.chat_input("Ex: Quais foram as principais decisões?"):
        if len(chat_history) >= MAX_CHAT_HISTORY:
            chat_history = chat_history[-MAX_CHAT_HISTORY:]

        chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history_store[chat_meeting.id] = chat_history

        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            with st.spinner("Pensando..."):
                try:
                    result = container.chat_with_meeting.execute(
                        ChatWithMeetingInput(
                            meeting=chat_meeting,
                            question=prompt,
                            history=chat_history[:-1],
                        )
                    )
                    answer = result.answer if result.success else f"⚠️ {result.error_message}"
                except Exception as e:
                    answer = f"❌ Erro: {str(e)}"
                    result = None

            placeholder.write(answer)

            # Lacuna 4 — tarefas criadas pelo chat: exibe E persiste.
            if result is not None and result.success and result.extracted_tasks:
                if chat_meeting.summary is None:
                    chat_meeting.summary = Summary()
                chat_meeting.summary.tasks.extend(result.extracted_tasks)
                try:
                    container.repository.save(chat_meeting)
                    for new_task in result.extracted_tasks:
                        st.success(f"✅ Tarefa criada: {new_task.description} "
                                   f"— {new_task.responsible}"
                                   + (f" · {new_task.deadline}" if new_task.deadline else ""))
                    st.toast(f"📌 {len(result.extracted_tasks)} tarefa(s) "
                             "salva(s) na reunião!", icon="✅")
                except Exception as e:
                    st.warning(f"Tarefa extraída, mas falhou ao salvar: {e}")

        chat_history.append({"role": "assistant", "content": answer})
        st.session_state.chat_history_store[chat_meeting.id] = chat_history
        st.rerun()