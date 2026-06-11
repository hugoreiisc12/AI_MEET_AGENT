import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from config.settings import get_settings

TASK_TEMPLATE = """# CRIAÇÃO DE TAREFAS

Olá, colaborador! Tudo bem?

Agente de Reuniões aqui!

Como combinado anteriormente na reunião **{meeting_title}**, realizada no dia **{meeting_date}**, seguem abaixo algumas tarefas criadas e associadas a essa reunião.

Espero que consiga realizar todas as atividades com êxito e tenha um ótimo trabalho!

---

# TAREFAS CRIADAS

## 📌 Tarefa 1

* **Nome da tarefa:** {task_name}
* **Horário de criação:** {created_at}
* **Prazo de entrega:** {deadline}

### Descrição

{description}

---

Desde já, agradeço pela dedicação de sempre e pelo excelente trabalho realizado.

Caso tenha qualquer dúvida sobre alguma das tarefas, consulte seu gestor responsável ou entre em contato comigo através da reunião definida abaixo:

🔗 **Link da reunião/chat:**
{meeting_link}

---

Atenciosamente,

**Seu Agente Especializado em Reuniões**
"""


class EmailSender:
    def __init__(self) -> None:
        self._settings = get_settings()

    def send_task_email(self, to_email: str, task_data: dict, meeting_title: str = "", meeting_date: str = "", meeting_link: str = "") -> bool:
        settings = self._settings
        if not settings.smtp_user or not settings.smtp_password:
            raise RuntimeError("SMTP não configurado. Preencha SMTP_USER e SMTP_PASSWORD no .env")

        content = TASK_TEMPLATE.format(
            meeting_title=meeting_title or "Reunião",
            meeting_date=meeting_date or datetime.now().strftime("%d/%m/%Y às %H:%M"),
            task_name=task_data.get("nome", "Sem nome"),
            created_at=task_data.get("criada_em", datetime.now().strftime("%d/%m/%Y %H:%M")),
            deadline=task_data.get("prazo", "Indefinido"),
            description=task_data.get("descricao", "Sem descrição"),
            meeting_link=meeting_link or "Não informado",
        )

        msg = MIMEMultipart()
        msg["From"] = settings.smtp_from_email or settings.smtp_user
        msg["To"] = to_email
        msg["Subject"] = f"📋 Tarefa criada - {task_data.get('nome', 'Nova tarefa')}"

        msg.attach(MIMEText(content, "plain", "utf-8"))

        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls(context=context)
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(msg["From"], msg["To"], msg.as_string())

        return True
