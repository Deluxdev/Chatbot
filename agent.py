"""
Agente Autonomo com Loop ReAct (Reasoning + Acting)
Implementa os 3 pilares: Raciocinio, Memoria de Contexto e Chamada de Ferramentas
Modelo: Google Gemini | Memoria: SQLite
"""

import os
import json
import logging
import re
from dotenv import load_dotenv
import google.generativeai as genai
from tools import execute_tool
from memory import Memory

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

MAX_CONTEXT_MESSAGES = 20
MAX_ITERATIONS = 8
MODEL = "models/gemini-2.5-flash-lite"
AGENT_NAME = os.environ.get("AGENT_NAME", "Karen")

SYSTEM_PROMPT = f"""Voce e {AGENT_NAME}, um assistente pessoal autonomo e inteligente.

## Processo de Raciocinio (ReAct Loop)
Antes de QUALQUER resposta, pense em voz alta:

<pensamento>
- O que o usuario realmente precisa?
- Preciso de alguma ferramenta?
- Qual e o melhor plano de acao?
</pensamento>

## Ferramentas Disponiveis
1. web_search - Busca informacoes atuais na internet
2. calendar_list - Lista eventos do Google Calendar
3. calendar_create - Cria eventos no calendario
4. calendar_delete - Remove eventos do calendario
5. get_datetime - Data e hora atual em Brasilia

## Regras
- SEMPRE use <pensamento>...</pensamento> antes de responder
- Nunca invente informacoes - use ferramentas para dados reais
- Se uma ferramenta falhar, explique e tente alternativa
- Seja conciso e direto

## Personalidade
- Proativo, honesto e eficiente
- Lembra de conversas anteriores com o usuario
"""

GEMINI_TOOLS = [
    {"name": "web_search", "description": "Busca informacoes atuais na internet.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Termo de busca"}, "max_results": {"type": "integer", "description": "Maximo de resultados"}}, "required": ["query"]}},
    {"name": "calendar_list", "description": "Lista proximos eventos do Google Calendar.", "parameters": {"type": "object", "properties": {"max_results": {"type": "integer"}, "days_ahead": {"type": "integer"}}}},
    {"name": "calendar_create", "description": "Cria evento no Google Calendar.", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"}, "time": {"type": "string", "description": "HH:MM"}, "duration_minutes": {"type": "integer"}, "description": {"type": "string"}, "location": {"type": "string"}}, "required": ["title", "date"]}},
    {"name": "calendar_delete", "description": "Remove evento do Google Calendar.", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}, "event_title": {"type": "string"}}, "required": ["event_id"]}},
    {"name": "get_datetime", "description": "Retorna data e hora atual em Brasilia.", "parameters": {"type": "object", "properties": {}}}
]


class Agent:
    def __init__(self):
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY nao configurada no arquivo .env")

        genai.configure(api_key=api_key)

        tools = [genai.protos.Tool(
            function_declarations=[
                genai.protos.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            k: genai.protos.Schema(
                                type=genai.protos.Type.STRING if v["type"] == "string" else genai.protos.Type.INTEGER,
                                description=v.get("description", "")
                            )
                            for k, v in t["parameters"].get("properties", {}).items()
                        },
                        required=t["parameters"].get("required", [])
                    )
                )
                for t in GEMINI_TOOLS
            ]
        )]

        self.model = genai.GenerativeModel(
            model_name=MODEL,
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
        )

        # Pilar B: memoria em RAM (janela deslizante) + SQLite (persistente)
        self.sessions = {}      # user_id -> lista de mensagens em RAM
        self.memory = Memory()  # persistencia entre sessoes
        logger.info(f"Agente {AGENT_NAME} inicializado com Gemini + SQLite")

    def _get_session(self, user_id: str) -> list:
        """Retorna o historico em RAM do usuario, carregando do SQLite se necessario."""
        if user_id not in self.sessions:
            # Restaura historico persistido ao iniciar nova sessao
            self.sessions[user_id] = self.memory.get_history(user_id, limit=MAX_CONTEXT_MESSAGES)
            logger.info(f"Sessao restaurada para user_id={user_id} ({len(self.sessions[user_id])} msgs)")
        return self.sessions[user_id]

    def _trim_session(self, user_id: str):
        """Janela deslizante: mantém apenas as ultimas MAX_CONTEXT_MESSAGES."""
        history = self.sessions[user_id]
        if len(history) > MAX_CONTEXT_MESSAGES:
            removed = len(history) - MAX_CONTEXT_MESSAGES
            self.sessions[user_id] = history[-MAX_CONTEXT_MESSAGES:]
            logger.info(f"Janela deslizante: {removed} msgs removidas da RAM (user={user_id})")

    def process_message(self, user_id: str, user_message: str) -> str:
        logger.info(f"Mensagem de user_id={user_id}: {user_message[:80]}")

        history = self._get_session(user_id)

        # Adiciona contexto de fatos persistentes ao inicio da conversa
        facts = self.memory.get_facts(user_id)
        context_prefix = ""
        if facts:
            context_prefix = f"[Fatos sobre o usuario: {json.dumps(facts, ensure_ascii=False)}]\n\n"

        history.append({"role": "user", "parts": [context_prefix + user_message]})
        self._trim_session(user_id)

        # Persiste no SQLite
        self.memory.save_message(user_id, "user", user_message)

        chat = self.model.start_chat(history=history[:-1])
        current_message = context_prefix + user_message
        iteration = 0
        final_response = None

        while iteration < MAX_ITERATIONS:
            iteration += 1
            logger.info(f"Iteracao {iteration}/{MAX_ITERATIONS}")

            try:
                response = chat.send_message(current_message)
            except Exception as e:
                logger.error(f"Erro na API do Gemini: {e}")
                return f"Erro ao conectar com a IA: {str(e)}"

            tool_calls = []
            text_parts = []

            for part in response.parts:
                if hasattr(part, "function_call") and part.function_call.name:
                    tool_calls.append(part.function_call)
                elif hasattr(part, "text") and part.text:
                    text_parts.append(part.text)

            for text in text_parts:
                if "<pensamento>" in text:
                    start = text.find("<pensamento>") + len("<pensamento>")
                    end = text.find("</pensamento>")
                    if end > start:
                        logger.info(f"RACIOCINIO:\n{text[start:end].strip()}")

            if tool_calls:
                tool_responses = []
                for fc in tool_calls:
                    tool_name = fc.name
                    tool_input = dict(fc.args)
                    logger.info(f"Ferramenta: {tool_name} | Params: {tool_input}")
                    try:
                        result = execute_tool(tool_name, tool_input)
                        logger.info(f"Resultado: {str(result)[:200]}")
                    except Exception as e:
                        result = f"ERRO: {str(e)}"
                        logger.error(f"Erro na ferramenta: {e}")

                    tool_responses.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=tool_name,
                                response={"result": result}
                            )
                        )
                    )
                current_message = tool_responses
            else:
                full_text = "\n".join(text_parts)
                final_response = self._clean_response(full_text)

                # Persiste resposta do agente
                self.memory.save_message(user_id, "model", full_text)
                history.append({"role": "model", "parts": [full_text]})
                break

        if final_response is None:
            final_response = "Limite de iteracoes atingido. Tente reformular sua pergunta."

        logger.info(f"Resposta gerada ({len(final_response)} chars)")
        return final_response

    def _clean_response(self, text: str) -> str:
        return re.sub(r"<pensamento>.*?</pensamento>", "", text, flags=re.DOTALL).strip()

    def clear_history(self, user_id: str):
        self.memory.clear_history(user_id)
        self.sessions.pop(user_id, None)
        logger.info(f"Historico limpo para user_id={user_id}")

    def get_stats(self, user_id: str) -> dict:
        return {
            "total_messages": self.memory.message_count(user_id),
            "session_messages": len(self.sessions.get(user_id, [])),
            "facts": self.memory.get_facts(user_id),
        }