"""Agentes internos do Meet Agent.

ETL Agent:      .webm → WhisperLocal → transcrição → MongoDB
Collection Agent: Poll DB a cada 10s → sincroniza com interface
Orchestrator Agent: Controla pipeline, valida cada etapa
"""
