"""
Agente Autonomo com Loop ReAct (Reasoning + Acting)
Implementa os 3 pilares: Raciocinio, Memoria de Contexto e Chamada de Ferramentas
Modelo: Google Gemini | Memoria: SQLite
Extras: Controle de Custo por Interacao + Filtro de Seguranca contra Prompt Injection
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

# ── Precos do modelo (por 1 milhao de tokens) ─────────────────────────────────
# Fonte: https://ai.google.dev/pricing  (gemini-2.5-flash-lite)
PRICE_INPUT_PER_M  = 0.10   # US$ por 1M tokens de entrada
PRICE_OUTPUT_PER_M = 0.40   # US$ por 1M tokens de saida

# ── Padroes de Prompt Injection ───────────────────────────────────────────────
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|earlier|above)\s+instructions?",
    r"ignor[ea]\s+(todas?\s+)?(as\s+)?(instru[cç][oõ]es|regras)\s+anteriores",
    r"esque[cç]a\s+(tudo|as\s+instru[cç][oõ]es|as\s+regras)",
    r"a\s+partir\s+de\s+agora\s+(voc[eê]\s+[eé]|fa[cç]a|ignore)",
    r"now\s+you\s+(are|will\s+be|must)",
    r"you\s+are\s+now\s+a",
    r"act\s+as\s+(if\s+you\s+are|a)",
    r"pretend\s+(you\s+are|to\s+be)",
    r"fa[cç]a\s+de\s+conta\s+que\s+voc[eê]\s+[eé]",
    r"voc[eê]\s+agora\s+[eé]\s+um",
    r"novo\s+prompt\s+do\s+sistema",
    r"system\s+prompt\s*:",
    r"<\s*system\s*>",
    r"\[system\]",
    r"override\s+(your\s+)?(instructions?|rules?|behavior)",
    r"bypass\s+(your\s+)?(safety|filter|restriction)",
    r"jailbreak",
    r"dan\s+mode",
    r"developer\s+mode",
    r"disable\s+(your\s+)?(safety|filter|restriction)",
]

# Pre-compila os padroes para performance
_COMPILED_PATTERNS = [
    re.compile(p, re.IGNORECASE | re.UNICODE) for p in INJECTION_PATTERNS
]


def detect_prompt_injection(text: str) -> bool:
    """
    Retorna True se o texto contiver padrao de prompt injection.
    Loga o padrao detectado no terminal.
    """
    for pattern in _COMPILED_PATTERNS:
        match = pattern.search(text)
        if match:
            logger.warning(
                f"[SEGURANCA] Prompt injection detectado! "
                f"Padrao: '{pattern.pattern}' | "
                f"Trecho: '{match.group(0)}' | "
                f"Mensagem completa: '{text[:120]}'"
            )
            return True
    return False


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """Calcula o custo em dolares com base nos tokens consumidos."""
    cost = (input_tokens / 1_000_000 * PRICE_INPUT_PER_M) + \
           (output_tokens / 1_000_000 * PRICE_OUTPUT_PER_M)
    return cost


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

        self.sessions = {}
        self.memory = Memory()

        # Acumulador de custo total da sessao
        self.total_cost_session = 0.0

        logger.info(f"Agente {AGENT_NAME} inicializado | Modelo: {MODEL}")
        logger.info(f"Preco: US$ {PRICE_INPUT_PER_M}/M tokens entrada | US$ {PRICE_OUTPUT_PER_M}/M tokens saida")

    def _get_session(self, user_id: str) -> list:
        if user_id not in self.sessions:
            self.sessions[user_id] = self.memory.get_history(user_id, limit=MAX_CONTEXT_MESSAGES)
            logger.info(f"Sessao restaurada para user_id={user_id} ({len(self.sessions[user_id])} msgs)")
        return self.sessions[user_id]

    def _trim_session(self, user_id: str):
        history = self.sessions[user_id]
        if len(history) > MAX_CONTEXT_MESSAGES:
            removed = len(history) - MAX_CONTEXT_MESSAGES
            self.sessions[user_id] = history[-MAX_CONTEXT_MESSAGES:]
            logger.info(f"Janela deslizante: {removed} msgs removidas da RAM (user={user_id})")

    def process_message(self, user_id: str, user_message: str) -> str:
        logger.info(f"Mensagem de user_id={user_id}: {user_message[:80]}")

        # ── Filtro de Seguranca: Prompt Injection ─────────────────────────────
        if detect_prompt_injection(user_message):
            logger.warning(f"[SEGURANCA] Mensagem bloqueada de user_id={user_id}")
            return None  # None = bloqueado silenciosamente (bot.py trata)

        history = self._get_session(user_id)

        facts = self.memory.get_facts(user_id)
        context_prefix = ""
        if facts:
            context_prefix = f"[Fatos sobre o usuario: {json.dumps(facts, ensure_ascii=False)}]\n\n"

        history.append({"role": "user", "parts": [context_prefix + user_message]})
        self._trim_session(user_id)
        self.memory.save_message(user_id, "user", user_message)

        chat = self.model.start_chat(history=history[:-1])
        current_message = context_prefix + user_message
        iteration = 0
        final_response = None

        # Acumuladores de tokens para esta interacao
        total_input_tokens  = 0
        total_output_tokens = 0

        while iteration < MAX_ITERATIONS:
            iteration += 1
            logger.info(f"Iteracao {iteration}/{MAX_ITERATIONS}")

            try:
                response = chat.send_message(current_message)
            except Exception as e:
                logger.error(f"Erro na API do Gemini: {e}")
                return f"Erro ao conectar com a IA: {str(e)}"

            # ── Contagem de Tokens ─────────────────────────────────────────────
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                meta = response.usage_metadata
                iter_input  = getattr(meta, "prompt_token_count", 0) or 0
                iter_output = getattr(meta, "candidates_token_count", 0) or 0
                total_input_tokens  += iter_input
                total_output_tokens += iter_output

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
                self.memory.save_message(user_id, "model", full_text)
                history.append({"role": "model", "parts": [full_text]})
                break

        # ── Exibe Custo da Interacao no Terminal ──────────────────────────────
        if total_input_tokens > 0 or total_output_tokens > 0:
            cost = calculate_cost(total_input_tokens, total_output_tokens)
            self.total_cost_session += cost
            logger.info(
                f"[CUSTO] Tokens: {total_input_tokens} entrada + {total_output_tokens} saida = "
                f"{total_input_tokens + total_output_tokens} total | "
                f"Custo: US$ {cost:.6f} | "
                f"Acumulado na sessao: US$ {self.total_cost_session:.6f}"
            )
        else:
            logger.info("[CUSTO] Metadados de tokens nao disponiveis para este modelo no plano atual.")

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
            "custo_sessao_usd": round(self.total_cost_session, 6),
        }