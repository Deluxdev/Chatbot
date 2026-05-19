"""
Pilar C: Habilidades Externas (Tool Calling)
Implementa Web Search (Tavily) e Integração com Google Calendar
"""

import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Definição das ferramentas para a API da Anthropic ────────────────────────
TOOLS_DEFINITION = [
    {
        "name": "web_search",
        "description": (
            "Busca informações atuais e em tempo real na internet usando Tavily. "
            "Use quando o usuário perguntar sobre notícias recentes, clima, preços, "
            "eventos atuais ou qualquer informação que possa ter mudado recentemente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Termo de busca em português ou inglês"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Número máximo de resultados (padrão: 3)",
                    "default": 3
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "calendar_list",
        "description": (
            "Lista os próximos eventos do Google Calendar do usuário. "
            "Use para verificar agenda, compromissos futuros ou verificar disponibilidade."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Número máximo de eventos a listar (padrão: 10)",
                    "default": 10
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Quantos dias à frente buscar (padrão: 7)",
                    "default": 7
                }
            }
        }
    },
    {
        "name": "calendar_create",
        "description": (
            "Cria um novo evento no Google Calendar. "
            "Use quando o usuário pedir para agendar algo, criar um lembrete ou marcar um compromisso."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Título do evento"
                },
                "date": {
                    "type": "string",
                    "description": "Data no formato YYYY-MM-DD (ex: 2025-06-15)"
                },
                "time": {
                    "type": "string",
                    "description": "Hora no formato HH:MM (ex: 14:30). Opcional para eventos de dia inteiro."
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Duração em minutos (padrão: 60)",
                    "default": 60
                },
                "description": {
                    "type": "string",
                    "description": "Descrição ou observações do evento"
                },
                "location": {
                    "type": "string",
                    "description": "Local do evento"
                }
            },
            "required": ["title", "date"]
        }
    },
    {
        "name": "calendar_delete",
        "description": (
            "Remove um evento do Google Calendar. "
            "Use apenas quando o usuário pedir explicitamente para cancelar ou deletar um evento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID do evento a ser removido (obtido via calendar_list)"
                },
                "event_title": {
                    "type": "string",
                    "description": "Título do evento para confirmação"
                }
            },
            "required": ["event_id"]
        }
    },
    {
        "name": "get_datetime",
        "description": "Retorna a data e hora atual no fuso horário de Brasília (UTC-3).",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]


# ── Roteador de Ferramentas ───────────────────────────────────────────────────
def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Roteia a chamada para a ferramenta correta."""
    tools = {
        "web_search": _web_search,
        "calendar_list": _calendar_list,
        "calendar_create": _calendar_create,
        "calendar_delete": _calendar_delete,
        "get_datetime": _get_datetime,
    }
    
    if tool_name not in tools:
        return f"Ferramenta '{tool_name}' não encontrada."
    
    return tools[tool_name](tool_input)


# ── Implementação: Data/Hora ──────────────────────────────────────────────────
def _get_datetime(params: dict) -> str:
    """Retorna data e hora atual no horário de Brasília."""
    from datetime import timezone, timedelta
    brasilia_tz = timezone(timedelta(hours=-3))
    now = datetime.now(brasilia_tz)
    return json.dumps({
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%d/%m/%Y"),
        "time": now.strftime("%H:%M"),
        "weekday": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][now.weekday()],
        "timezone": "America/Sao_Paulo (UTC-3)"
    }, ensure_ascii=False)


# ── Implementação: Web Search (Tavily) ───────────────────────────────────────
def _web_search(params: dict) -> str:
    """Busca na web usando a API do Tavily."""
    try:
        import requests
        
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return "ERRO: TAVILY_API_KEY não configurada. Configure a variável de ambiente."
        
        query = params.get("query", "")
        max_results = params.get("max_results", 3)
        
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
            },
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        
        # Formata resultado
        result = {
            "query": query,
            "answer": data.get("answer", ""),
            "results": [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", "")[:500],
                    "score": round(r.get("score", 0), 3),
                }
                for r in data.get("results", [])[:max_results]
            ]
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        logger.error(f"Erro no web_search: {e}")
        return f"ERRO na busca web: {str(e)}"


# ── Implementação: Google Calendar ────────────────────────────────────────────
def _get_calendar_service():
    """Cria e retorna o serviço autenticado do Google Calendar."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    
    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    creds = None
    
    # Carrega credenciais salvas
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    # Renova ou obtém novas credenciais
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError(
                    "credentials.json não encontrado. "
                    "Baixe o arquivo de credenciais do Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Salva credenciais para próximo uso
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    
    return build("calendar", "v3", credentials=creds)


def _calendar_list(params: dict) -> str:
    """Lista próximos eventos do Google Calendar."""
    try:
        from datetime import timezone, timedelta
        service = _get_calendar_service()
        
        max_results = params.get("max_results", 10)
        days_ahead = params.get("days_ahead", 7)
        
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days_ahead)
        
        events_result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        
        events = events_result.get("items", [])
        
        if not events:
            return json.dumps({"message": "Nenhum evento encontrado nos próximos dias.", "events": []})
        
        formatted_events = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            formatted_events.append({
                "id": event["id"],
                "title": event.get("summary", "Sem título"),
                "start": start,
                "location": event.get("location", ""),
                "description": event.get("description", "")[:200],
            })
        
        return json.dumps({
            "count": len(formatted_events),
            "events": formatted_events
        }, ensure_ascii=False, indent=2)
        
    except Exception as e:
        logger.error(f"Erro ao listar eventos: {e}")
        return f"ERRO ao acessar o Google Calendar: {str(e)}"


def _calendar_create(params: dict) -> str:
    """Cria um evento no Google Calendar."""
    try:
        from datetime import timezone, timedelta
        service = _get_calendar_service()
        
        title = params.get("title", "")
        date = params.get("date", "")
        time_str = params.get("time", "")
        duration = params.get("duration_minutes", 60)
        description = params.get("description", "")
        location = params.get("location", "")
        
        # Monta evento com horário ou dia inteiro
        if time_str:
            start_dt = datetime.fromisoformat(f"{date}T{time_str}:00")
            # Assume fuso de Brasília
            start_dt = start_dt.replace(tzinfo=timezone(timedelta(hours=-3)))
            end_dt = start_dt + timedelta(minutes=duration)
            
            event_body = {
                "summary": title,
                "description": description,
                "location": location,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/Sao_Paulo"},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": "America/Sao_Paulo"},
            }
        else:
            # Evento de dia inteiro
            event_body = {
                "summary": title,
                "description": description,
                "location": location,
                "start": {"date": date},
                "end": {"date": date},
            }
        
        event = service.events().insert(calendarId="primary", body=event_body).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Evento '{title}' criado com sucesso!",
            "event_id": event["id"],
            "link": event.get("htmlLink", ""),
        }, ensure_ascii=False)
        
    except Exception as e:
        logger.error(f"Erro ao criar evento: {e}")
        return f"ERRO ao criar evento no Google Calendar: {str(e)}"


def _calendar_delete(params: dict) -> str:
    """Remove um evento do Google Calendar."""
    try:
        service = _get_calendar_service()
        
        event_id = params.get("event_id", "")
        event_title = params.get("event_title", "evento")
        
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Evento '{event_title}' removido com sucesso."
        }, ensure_ascii=False)
        
    except Exception as e:
        logger.error(f"Erro ao deletar evento: {e}")
        return f"ERRO ao remover evento do Google Calendar: {str(e)}"
