"""
Bot do Telegram com whitelist de usuarios e memoria persistente por usuario
"""

import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes,
)
from agent import Agent

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

AGENT_NAME = os.environ.get("AGENT_NAME", "Karen")

# ── Whitelist de usuarios ─────────────────────────────────────────────────────
def _load_whitelist() -> set[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
    if not raw.strip():
        return set()  # vazio = todos permitidos (modo desenvolvimento)
    ids = set()
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            ids.add(int(item))
    return ids

ALLOWED_USER_IDS = _load_whitelist()
agent = Agent()


def _is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True  # sem whitelist configurada, permite todos
    return user_id in ALLOWED_USER_IDS


# ── Handlers ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        await update.message.reply_text("Acesso nao autorizado.")
        logger.warning(f"Acesso negado para user_id={user_id}")
        return

    await update.message.reply_text(
        f"Ola! Sou {AGENT_NAME}, seu assistente pessoal autonomo.\n\n"
        "Posso ajudar com:\n"
        "- Busca na web\n"
        "- Gerenciar sua agenda (Google Calendar)\n"
        "- Responder perguntas e muito mais\n\n"
        "Use /ajuda para ver os comandos disponiveis."
    )


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return

    stats = agent.get_stats(str(update.effective_user.id))
    await update.message.reply_text(
        "Comandos disponiveis:\n\n"
        "/start - Apresentacao\n"
        "/ajuda - Esta mensagem\n"
        "/limpar - Limpa historico de conversa\n"
        "/status - Status e estatisticas\n\n"
        f"Suas estatisticas:\n"
        f"- Mensagens totais: {stats['total_messages']}\n"
        f"- Mensagens na sessao: {stats['session_messages']}"
    )


async def limpar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return
    agent.clear_history(str(user_id))
    await update.message.reply_text("Historico limpo! Podemos comecar do zero.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return

    stats = agent.get_stats(str(user_id))
    facts_text = ""
    if stats["facts"]:
        facts_text = "\nFatos que lembro de voce:\n" + "\n".join(
            f"- {k}: {v}" for k, v in stats["facts"].items()
        )

    await update.message.reply_text(
        f"Status do Agente {AGENT_NAME}:\n\n"
        f"- Total de mensagens trocadas: {stats['total_messages']}\n"
        f"- Mensagens na sessao atual: {stats['session_messages']}\n"
        f"- Custo acumulado na sessao: US$ {stats['custo_sessao_usd']:.6f}\n"
        f"- Janela de contexto: max 20 mensagens\n"
        f"- Memoria: SQLite (persistente)\n"
        f"- Modelo: Gemini 2.5 Flash Lite\n"
        f"- Ferramentas: Web Search, Google Calendar"
        f"{facts_text}"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        await update.message.reply_text("Acesso nao autorizado.")
        return

    user_message = update.message.text
    user_name = update.effective_user.first_name
    logger.info(f"Mensagem de {user_name} (id={user_id}): {user_message[:80]}")

    thinking_msg = await update.message.reply_text("Pensando...")

    try:
        response = agent.process_message(str(user_id), user_message)

        # Mensagem bloqueada pelo filtro de seguranca (silencioso)
        if response is None:
            await thinking_msg.delete()
            return

        await thinking_msg.delete()

        if len(response) > 4096:
            chunks = [response[i:i+4096] for i in range(0, len(response), 4096)]
            for chunk in chunks:
                try:
                    await update.message.reply_text(chunk, parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(chunk)
        else:
            try:
                await update.message.reply_text(response, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(response)

    except Exception as e:
        logger.error(f"Erro ao processar mensagem: {e}")
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            "Erro ao processar sua mensagem. Tente novamente ou use /limpar."
        )


# ── Inicializacao ─────────────────────────────────────────────────────────────
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN nao configurado!")

    if ALLOWED_USER_IDS:
        logger.info(f"Whitelist ativa: {ALLOWED_USER_IDS}")
    else:
        logger.info("Sem whitelist - todos os usuarios permitidos")

    logger.info(f"Iniciando {AGENT_NAME}...")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("limpar", limpar))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info(f"{AGENT_NAME} iniciado! Aguardando mensagens...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()