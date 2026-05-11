# 📋 IA Google Meet - Meeting Assistant

Uma aplicação inteligente que transcrevia reuniões do Google Meet, gera resumos automáticos com IA e permite chat interativo sobre o conteúdo da reunião.

## 🎯 Funcionalidades

- **🎙️ Transcrição de Áudio**: Converte áudio de reuniões em texto usando OpenAI Whisper
- **📝 Resumo Automático**: Gera resumos estruturados com IA (GPT-4o) contendo:
  - Overview (resumo geral)
  - Tópicos abordados
  - Tarefas identificadas (com responsável e deadline)
  - Decisões tomadas (com contexto)
- **💬 Chat Interativo**: Responde perguntas sobre a reunião com base na transcrição completa
- **🎨 Interface Web**: Dashboard Streamlit intuitivo
- **⚡ Modo Terminal**: Teste rápido sem interface gráfica

## 🏗️ Arquitetura

```
IA_GOOGLE MEET/
├── config/              # Configurações e variáveis de ambiente
├── domain/              # Entidades e interfaces (DDD)
│   ├── entities/        # Meeting, Summary, Task, Decision
│   └── interfaces/      # ILLMService, ITranscriber
├── llm/                 # Serviço LangChain + OpenAI
├── user_cases/          # Casos de uso principais
│   ├── transcribe_meeting.py
│   ├── summarize_meeting.py
│   └── chat_with_meeting.py
├── presentation/        # Camada de apresentação
│   └── streamlit/       # Interface web
├── storage/             # Persistência de dados
├── repositores/         # Acesso a dados
└── main.py              # Ponto de entrada
```

## 🚀 Como Usar

### **Pré-requisitos**
- Python 3.10+
- Chave de API OpenAI
- Microfone (para captura de áudio em tempo real)
- **Dependências do Sistema**:
  - **macOS**: `brew install portaudio ffmpeg`
  - **Linux**: `sudo apt-get install portaudio19-dev libasound2-dev ffmpeg`
  - **Windows**: Instale [ffmpeg](https://ffmpeg.org/download.html) manualmente ou via Chocolatey

### **Instalação**

```bash
# 1. Clone ou copie o projeto
cd "IA_GOOGLE MEET"

# 2. Crie um ambiente virtual
python -m venv venv
source venv/bin/activate  # macOS/Linux
# ou
venv\Scripts\activate  # Windows

# 3. Instale dependências do sistema (se precisar de captura de áudio)
# macOS (recomendado):
brew install portaudio

# Linux (Ubuntu/Debian):
sudo apt-get install portaudio19-dev python3-pyaudio

# Windows: Instalação via pip geralmente funciona diretamente

# 4. Instale as dependências Python
pip install -r requirements.txt

# ⚠️ Se pyaudio falhar no macOS, tente:
pip install --global-option='build_ext' --global-option='-I/usr/local/include' --global-option='-L/usr/local/lib' pyaudio

# 5. Configure as variáveis de ambiente
# Crie um arquivo .env com:
# OPENAI_API_KEY=sua_chave_aqui
# OPENAI_MODEL=gpt-4o
# WHISPER_MODEL=whisper-1
# WHISPER_LANGUAGE=pt
# STORAGE_PATH=data/meetings
```

### **Execução**

#### **Interface Web (Streamlit)**
```bash
streamlit run main.py
```
Abre dashboard em `http://localhost:8501`

#### **Teste via Terminal**
```bash
python main.py --test caminho/para/audio.wav
```

#### **Teste Completo com Mocks** (recomendado primeiro!)
```bash
# Valida o fluxo completo sem gastar API calls
python test/test_full.py
```
Este teste:
- ✅ Simula transcrição, resumo, chat e persistência
- ✅ Usa dados fictícios (não precisa de OPENAI_API_KEY)
- ✅ Salva dados em `data/test_meetings/`
- ✅ Perfeito para validar a instalação

## 📦 Dependências Principais

| Pacote | Função | Obrigatório | Notas |
|--------|--------|-------------|-------|
| `openai` | API OpenAI (Whisper + GPT-4o) | ✅ | - |
| `langchain` | Orquestração de LLMs | ✅ | - |
| `langchain-openai` | Integração com OpenAI | ✅ | - |
| `streamlit` | Interface web | ✅ | - |
| `pydantic` | Validação de dados | ✅ | - |
| `python-dotenv` | Carregamento de .env | ✅ | - |
| `pydub` | Processamento de áudio | ✅ | Requer ffmpeg |
| `pyaudio` | Captura de áudio | ❌ | Requer PortAudio (ver Troubleshooting) |
| `webrtcvad` | Detecção de atividade de voz | ❌ | Opcional |

## 🔄 Fluxo de Funcionamento

```
1. CAPTURA
   ├─ Áudio da reunião (arquivo ou mic)
   
2. TRANSCRIÇÃO
   ├─ OpenAI Whisper
   ├─ Texto com speakers identificados
   
3. RESUMO
   ├─ GPT-4o analisa transcrição
   ├─ Extrai: tarefas, decisões, tópicos
   ├─ Retorna JSON estruturado
   
4. PERSISTÊNCIA
   ├─ Meeting salva com resumo
   
5. CHAT INTERATIVO
   ├─ Usuário faz perguntas
   ├─ GPT-4o responde com contexto da reunião
   ├─ Mantém histórico de conversa
```

## 🧩 Componentes Chave

### **LangChainLLMService** (`llm/langchain_llm_service.py`)
- Integração com GPT-4o via LangChain
- Dois modos:
  - `summarize()`: Resumo estruturado
  - `chat()`: Conversa interativa
- Mantém histórico via `ConversationBufferMemory`

### **TranscribeMeetingUC** (`user_cases/transcribe_meeting.py`)
- Transcreve áudio usando Whisper
- Identifica speakers
- Formata output

### **SummarizeMeetingUC** (`user_cases/summarize_meeting.py`)
- Recebe reunião já transcrita
- Gera summary via LLM
- Anexa à entidade Meeting

### **Meeting Entity** (`domain/entities/meeting.py`)
- Encapsula dados da reunião
- Validações automáticas
- Suporta múltiplos formatos de transcrição

## ⚙️ Configuração

Edite `.env` para customizar:

```env
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o                    # Modelo para resumo/chat
WHISPER_MODEL=whisper-1                # Modelo para transcrição
WHISPER_LANGUAGE=pt                    # Idioma (pt, en, es, etc)

# Storage
STORAGE_PATH=data/meetings             # Diretório para salvar reuniões
MAX_AUDIO_SIZE_MB=25                   # Limite Whisper API
```

## 📊 Exemplo de Output

### Summary gerado:
```json
{
  "overview": "Reunião de planejamento do Q2. Definidas metas, responsáveis e timelines.",
  "topics": ["Roadmap", "Budget", "Equipe"],
  "tasks": [
    {
      "description": "Preparar apresentação de resultados",
      "responsible": "Ana Silva",
      "deadline": "15/05/2026"
    }
  ],
  "decisions": [
    {
      "description": "Adotar nova ferramenta de gestão de projetos",
      "context": "Votação unânime. Implementação até 01/06"
    }
  ]
}
```

## ✅ Testes

### **Test Full (Fluxo Completo com Mocks)**

O arquivo `test/test_full.py` testa todo o fluxo sem gastar créditos de API:

```bash
python test/test_full.py
```

**O que testa:**

| Teste | Descrição | Validação |
|-------|-----------|-----------|
| **1. Transcrição** | Simula conversão de áudio em texto com identificação de speakers | Segmentos e formatação |
| **2. Resumo** | Gera resumo estruturado (tasks, decisions, topics) | JSON parsing e entities |
| **3. Chat** | Responde perguntas sobre a reunião | Histórico de conversa |
| **4. Persistência** | Salva e carrega reunião em JSON | Serialização/desserialização |

**Saída esperada:**
```
✅ Todos os testes passaram!

Próximo passo:
  1. Configure sua .env com OPENAI_API_KEY
  2. python main.py --test <seu_audio.wav>
  3. python main.py  →  abre o Streamlit
```



- ✅ Variáveis sensíveis em `.env` (não versione)
- ✅ API Key do OpenAI protegida
- ✅ Validação de entrada com Pydantic
- ✅ Tratamento de exceções estruturado

## 🐛 Troubleshooting

### "error: command 'clang' failed" ou "pyaudio installation failed"
**Causa**: Faltam dependências de compilação do PortAudio

**Solução (macOS)**:
```bash
brew install portaudio
pip install --global-option='build_ext' \
  --global-option='-I/usr/local/include' \
  --global-option='-L/usr/local/lib' pyaudio
```

**Solução (Linux)**:
```bash
sudo apt-get install portaudio19-dev
pip install pyaudio
```

**Solução (Windows)**:
```bash
# Geralmente funciona diretamente:
pip install pyaudio
# Se falhar, instale Visual C++ Build Tools
```

**Alternativa (sem captura de áudio ao vivo)**:
Se não precisa capturar áudio em tempo real, remova `pyaudio` de requirements.txt:
```bash
pip install -r requirements.txt --no-deps
pip install openai langchain langchain-openai streamlit pydantic-settings python-dotenv pydub webrtcvad
```

### "ModuleNotFoundError: No module named 'X'"
```bash
# Verifique se instalou dependências:
pip install -r requirements.txt
```

### "OPENAI_API_KEY not found"
```bash
# Crie .env na raiz do projeto com:
OPENAI_API_KEY=sua_chave_aqui
```

### Áudio não é capturado
```bash
# Verifique permissões de microfone
# macOS: Preferências > Segurança > Privacidade > Microfone
# Linux: Adicione usuário ao grupo audio
sudo usermod -a -G audio $USER
```

### "ImportError: cannot import name 'ChatOpenAI'"
```bash
# Atualize LangChain:
pip install --upgrade langchain langchain-openai
```

## 📝 Padrões de Código

- **DDD**: Separação de domínio, casos de uso e apresentação
- **Dependency Injection**: Container gerencia dependências
- **Type Hints**: Tipagem forte em todo código
- **Docstrings**: Documentação em português

## 🤝 Contribuindo

1. Faça fork do projeto
2. Crie uma branch para sua feature (`git checkout -b feature/AmazingFeature`)
3. Commit suas mudanças (`git commit -m 'Add some AmazingFeature'`)
4. Push para a branch (`git push origin feature/AmazingFeature`)
5. Abra um Pull Request

## 📄 Licença

MIT License - veja LICENSE para detalhes

## 📧 Contato

Hugo - [seu email/github]

## 🎓 Tecnologias Usadas

- Python 3.10+
- OpenAI API (GPT-4o, Whisper)
- LangChain
- Streamlit
- Pydantic
- SQLAlchemy (opcional)

---

**Última atualização**: 10 de maio de 2026
