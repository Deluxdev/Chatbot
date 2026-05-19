"""
Agente Autônomo com Loop ReAct (Reasoning + Acting)
Implementa os 3 pilares: Raciocínio, Memória de Contexto e Chamada de Ferramentas
Modelo: Google Gemini
"""

import os
import json
import logging
import re
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai
from tools import execute_tool

load_dotenv()

# ── Configuração de Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log"),
    ]
)
logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────────────────────
MAX_CONTEXT_MESSAGES = 20
MAX_ITERATIONS = 8
MODEL = "models/gemini-2.5-flash-lite"

# ── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Você é um assistente pessoal autônomo e inteligente chamado AgentBot.

## Seu Processo de Raciocínio (ReAct Loop)
Antes de QUALQUER resposta, você DEVE pensar em voz alta usando este formato:

<pensamento>
- O que o usuário realmente precisa?
- Preciso de alguma ferramenta? (busca, calendário, etc.)
- Qual é o melhor plano de ação?
- Há riscos ou ambiguidades nesta solicitação?
</pensamento>

Depois execute a ação necessária e forneça uma Resposta Final clara.

## Ferramentas Disponíveis
1. **web_search**: Busque informações atuais na internet
2. **calendar_list**: Liste eventos do calendário Google
3. **calendar_create**: Crie novos eventos no calendário
4. **calendar_delete**: Remova eventos do calendário
5. **get_datetime**: Obtenha data e hora atual

## Regras Importantes
- SEMPRE use <pensamento>...</pensamento> antes de responder
- Se uma ferramenta falhar, explique o erro claramente e tente uma abordagem alternativa
- Nunca invente informações — use ferramentas para buscar dados reais
- Seja conciso mas completo nas respostas

## Personalidade
- Proativo: antecipe necessidades do usuário
- Honesto: admita limitações
- Eficiente: vá direto ao ponto
"""

# ── Definição das ferramentas ─────────────────────────────────────────────────
GEMINI_TOOLS = [
    {"name": "web_search", "description": "Busca informações atuais na internet.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Termo de busca"}, "max_results": {"type": "integer", "description": "Número máximo de resultados"}}, "required": ["query"]}},
    {"name": "calendar_list", "description": "Lista os próximos eventos do Google Calendar.", "parameters": {"type": "object", "properties": {"max_results": {"type": "integer", "description": "Máximo de eventos"}, "days_ahead": {"type": "integer", "description": "Dias à frente"}}}},
    {"name": "calendar_create", "description": "Cria um novo evento no Google Calendar.", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"}, "time": {"type": "string", "description": "HH:MM"}, "duration_minutes": {"type": "integer"}, "description": {"type": "string"}, "location": {"type": "string"}}, "required": ["title", "date"]}},
    {"name": "calendar_delete", "description": "Remove um evento do Google Calendar.", "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}, "event_title": {"type": "string"}}, "required": ["event_id"]}},
    {"name": "get_datetime", "description": "Retorna a data e hora atual no horário de Brasília.", "parameters": {"type": "object", "properties": {}}}
]


class Agent:
    def __init__(self):
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY não configurada no arquivo .env")

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

        self.conversation_history = []
        logger.info("🤖 Agente Gemini inicializado com sucesso")

    def _manage_context_window(self):
        if len(self.conversation_history) > MAX_CONTEXT_MESSAGES:
            removed = len(self.conversation_history) - MAX_CONTEXT_MESSAGES
            self.conversation_history = self.conversation_history[-MAX_CONTEXT_MESSAGES:]
            logger.info(f"🧹 Memória: removidas {removed} mensagens antigas")

    def process_message(self, user_message: str) -> str:
        logger.info(f"📨 Mensagem recebida: {user_message[:100]}...")

        self.conversation_history.append({"role": "user", "parts": [user_message]})
        self._manage_context_window()

        chat = self.model.start_chat(history=self.conversation_history[:-1])
        current_message = user_message
        iteration = 0
        final_response = None

        while iteration < MAX_ITERATIONS:
            iteration += 1
            logger.info(f"🔄 Iteração {iteration}/{MAX_ITERATIONS}")

            try:
                response = chat.send_message(current_message)
            except Exception as e:
                logger.error(f"❌ Erro na API do Gemini: {e}")
                return f"⚠️ Erro ao conectar com a IA: {str(e)}"

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
                        logger.info(f"💭 RACIOCÍNIO:\n{text[start:end].strip()}")

            if tool_calls:
                tool_responses = []
                for fc in tool_calls:
                    tool_name = fc.name
                    tool_input = dict(fc.args)
                    logger.info(f"🔧 Ferramenta: {tool_name} | Params: {tool_input}")
                    try:
                        result = execute_tool(tool_name, tool_input)
                        logger.info(f"✅ Resultado: {str(result)[:200]}")
                    except Exception as e:
                        result = f"ERRO: {str(e)}"
                        logger.error(f"❌ {e}")

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
                self.conversation_history.append({"role": "model", "parts": [full_text]})
                break

        if final_response is None:
            final_response = "⚠️ Limite de iterações atingido. Tente reformular sua pergunta."

        logger.info(f"✉️ Resposta gerada ({len(final_response)} chars)")
        return final_response

    def _clean_response(self, text: str) -> str:
        return re.sub(r"<pensamento>.*?</pensamento>", "", text, flags=re.DOTALL).strip()

    def clear_history(self):
        self.conversation_history = []
        logger.info("🗑️ Histórico limpo")