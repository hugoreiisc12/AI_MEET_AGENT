# Arquivo principal da interface Streamlit, que orquestra a interação do usuário, exibe o dashboard da reunião ,
#  e mantém o estado da aplicação usando session_state
import sys
import os
import uuid
from datetime import datetime
from pathlib import Path


# Garante que o root do projeto está no path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from domain.entities.meeting import Meeting
from domain.entities.transcript import Transcript
from presentation.container import get_container
from use_cases.transcribe_meeting import TranscribeMeetingInput
from use_cases.summarize_meeting import SummarizeMeetingInput
from use_cases.chat_with_meeting import ChatWithMeetingInput

"""
app.py — Interface Streamlit do Meet Agent.

Execute: streamlit run presentation/streamlit/app.py
"""
# Configuração da página


st.set_page_config(
    page_title="Meet Agent",
    page_icon="🎤",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Session state — persiste estado entre reruns do Streamlit
# Função para inicializar o estado da sessão, garantindo que as chaves necessárias estejam presentes com valores padrão.
def init_state() -> None:
    defaults = {
        "current_meeting": None,   # Meeting ativa no momento
        "chat_history": [],        # [{"role": str, "content": str}]
        "processing": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_state()
container = get_container()

# Sidebar — histórico de reuniões salvas e controle de sessão 
with st.sidebar:
    st.title("🎤 Meet Agent")
    st.caption("Agente de reuniões com IA")
    st.divider()

    st.subheader("Reuniões salvas")
    saved_meetings = container.repository.list_all()

    if not saved_meetings:
        st.info("Nenhuma reunião salva ainda.")
    else:
        for m in saved_meetings:
            label = f"📋 {m.title[:28]}..." if len(m.title) > 28 else f"📋 {m.title}"
            date_str = m.started_at.strftime("%d/%m %H:%M")
            if st.button(f"{label}\n{date_str}", key=f"load_{m.id}", use_container_width=True):
                st.session_state.current_meeting = m
                st.session_state.chat_history = []
                st.rerun()

    st.divider()
    if st.session_state.current_meeting:
        if st.button("🗑 Limpar sessão atual", use_container_width=True):
            st.session_state.current_meeting = None
            st.session_state.chat_history = []
            st.rerun()

# Main — área principal

st.title("🎤 Meet Agent")

# Se não há reunião ativa, mostra o formulario de upload para iniciar nova reunnião e processar o audio, transcrição e resumo

if st.session_state.current_meeting is None:
    st.subheader("Nova reunião")
    st.caption("Envie o áudio gravado da reunião para iniciar.")

    col_upload, col_info = st.columns([2, 1])

    with col_upload:
        title = st.text_input(
            "Título da reunião",
            placeholder="Ex: Sprint Planning — Semana 22",
        )
        audio_file = st.file_uploader(
            "Arquivo de áudio",
            type=["wav", "mp3", "m4a", "webm", "ogg", "mp4"],
            help="Máximo 25MB (limite da API Whisper)",
        )

        use_diarization = st.toggle(
            "Identificar speakers",
            value=True,
            help="Tenta separar quem falou cada parte (heurística por pausas)",
        )
# Botão para processar a reunião, que salva o audio, chama o processo de transcrição e resumo, e atualiza o estado da sessão com a reunião processada.
        if st.button("🚀 Processar reunião", disabled=not (title and audio_file), type="primary"):
            with st.spinner("Salvando áudio..."):
                # Salva áudio temporariamente
                audio_dir = Path("data/audio")
                audio_dir.mkdir(parents=True, exist_ok=True)
                suffix = Path(audio_file.name).suffix
                audio_path = str(audio_dir / f"{uuid.uuid4()}{suffix}")
                with open(audio_path, "wb") as f:
                    f.write(audio_file.read())

            with st.spinner("Transcrevendo com Whisper... (pode levar alguns segundos)"):
                t_result = container.transcribe_meeting.execute(
                    TranscribeMeetingInput(
                        audio_path=audio_path,
                        with_diarization=use_diarization,
                    )
                )

# Conferência ativa de erros na transcrição, exibindo mensagem de erro e interrompedo 
# o processo caso a transcrição falhe
            if not t_result.success:
                st.error(f"Erro na transcrição: {t_result.error_message}")
                st.stop()

            transcript: Transcript = t_result.transcript

# Monta a Meeting com a transcrição e metadados, chama o processo e de resumo,
# e atualiza com estado da sessão com reunião atualizada com resumo
            meeting = Meeting(
                id=str(uuid.uuid4()),
                title=title,
                started_at=datetime.now(),
                audio_path=audio_path,
                transcript_text=transcript.full_text,
                transcript_formatted=transcript.formatted,
                participants=transcript.speakers,
                duration_minutes=transcript.duration_minutes,
            )

            with st.spinner("Gerando resumo com IA..."):
                s_result = container.summarize_meeting.execute(
                    SummarizeMeetingInput(meeting=meeting)
                )

            if not s_result.success:
                st.error(f"Erro ao gerar resumo: {s_result.error_message}")
                st.stop()

            st.session_state.current_meeting = s_result.meeting
            st.session_state.chat_history = []
            st.rerun()

    with col_info:
        st.info(
            "**Como funciona:**\n\n"
            "1. Grave sua reunião no Meet\n"
            "2. Faça upload do áudio aqui\n"
            "3. A IA transcreve e resume\n"
            "4. Pergunte o que quiser sobre a reunião"
        )

#  Dashboard da reunião
# Se não há reunião ativa, o dashboard da reunião é exibido, mostrando o resumo estruturado, a transcrição completa (colapsada)
else:
    meeting: Meeting = st.session_state.current_meeting
    summary = meeting.summary

# Header com título da reunião, data e hora, e metricas importantes como duração, número de participantes, tarefas e decisões.
    st.subheader(f"📋 {meeting.title}")
    st.caption(meeting.started_at.strftime("%-d de %B de %Y às %H:%M"))

# Métricas importantes da reunião (Ex: duração, participantes, número de tarefas e decisões e etc...)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("⏱ Duração", f"{meeting.duration_minutes:.0f} min")
    col2.metric("👥 Participantes", len(meeting.participants) or "—")
    col3.metric("✅ Tarefas", len(summary.tasks) if summary else 0)
    col4.metric("🔑 Decisões", len(summary.decisions) if summary else 0)

    st.divider()

# Layout: resumo + chat lado a lado, e transcrição completa colapsada abaixo
    col_left, col_right = st.columns([1, 1], gap="large")

 # Coluna esquerda: Resumo estruturado, que exibe a vusão geral, tópicos, tarefas, decisões e permite marcar tarefas como concluídas 
    with col_left:
        if summary:
            st.markdown("### Visão Geral")
            st.write(summary.overview)

            if summary.topics:
                st.markdown("### Tópicos")
                for topic in summary.topics:
                    st.markdown(f"- {topic}")

            if summary.tasks:
                st.markdown("### Tarefas")
                for task in summary.tasks:
                    done = st.checkbox(
                        f"**{task.description}**  \n"
                        f"*{task.responsible}* · {task.deadline}",
                        value=task.done,
                        key=f"task_{id(task)}",
                    )
                    task.done = done

            if summary.decisions:
                st.markdown("### Decisões")
                for dec in summary.decisions:
                    with st.expander(dec.description):
                        st.write(dec.context or "Sem contexto adicional.")
        else:
            st.warning("Resumo não disponível.")

 #  Coluna direita: Chat interativo, que permite ao usuário fazer perguntas sobre a reunião e obter respostas da LLM, 
 # mantendo o histórico de conversa para contexto adicional
    with col_right:
        st.markdown("### 💬 Pergunte sobre a reunião")

# Histórico visual do chat, que exibe as mensagens anteriores com formatação difereciada para usuário e assistente, e uma mensagem de boas vindas 
        chat_container = st.container(height=400)
        with chat_container:
            if not st.session_state.chat_history:
                st.caption("Faça uma pergunta sobre a reunião abaixo.")
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])

# Input de chat, que captura a pergunta do usuário, atualize o historico de conversa, 
# chama o processo de chat com reunião passando a pergunta
        if question := st.chat_input("Ex: Quem ficou responsável pela tarefa X?"):
            st.session_state.chat_history.append({"role": "user", "content": question})

            with st.spinner("Pensando..."):
                c_result = container.chat_with_meeting.execute(
                    ChatWithMeetingInput(
                        meeting=meeting,
                        question=question,
                        history=st.session_state.chat_history[:-1],
                    )
                )

            if c_result.success:
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": c_result.answer}
                )
            else:
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": f"⚠️ {c_result.error_message}"}
                )

            st.rerun()

 #  Transcrição completa (colapsada), que exibe a transcrição completa da reunião, 
 # permitindo ao usuário expandir para ler detalhes e baixar a transcrição e o resumo em arquivos de texto.
    st.divider()
    with st.expander("📄 Transcrição completa"):
        st.text(meeting.transcript_formatted or meeting.transcript_text)

        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            st.download_button(
                "⬇️ Baixar .txt",
                data=meeting.transcript_formatted or meeting.transcript_text,
                file_name=f"{meeting.title}_transcricao.txt",
                mime="text/plain",
            )
        with col_exp2:
            if summary:
                st.download_button(
                    "⬇️ Baixar resumo .txt",
                    data=summary.formatted,
                    file_name=f"{meeting.title}_resumo.txt",
                    mime="text/plain",
                )