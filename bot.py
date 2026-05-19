"""
Bot do Telegram — Interface principal do Agente Autônomo
Conecta o agente ao Telegram para interação em tempo real
"""
from dotenv import load_dotenv
load_dotenv()

import os
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from agent import Agent

logger = logging.getLogger(__name__)

# Instância global do agente (uma por sessão de bot)
agent = Agent()


# ── Handlers de Comandos ──────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensagem de boas-vindas."""
    await update.message.reply_text(
        "👋 Olá! Sou seu *ProbectZmBot* — um assistente autônomo com capacidade de:\n\n"
        "🔍 *Web Search* — buscar informações atuais\n"
        "📅 *Google Calendar* — gerenciar sua agenda\n\n"
        "Exemplos do que posso fazer:\n"
        "• _\"Quais são as últimas notícias sobre IA?\"_\n"
        "• _\"Quais são meus compromissos desta semana?\"_\n"
        "• _\"Agende uma reunião amanhã às 15h\"_\n\n"
        "Use /ajuda para ver todos os comandos.",
        parse_mode="Markdown"
    )


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe os comandos disponíveis."""
    await update.message.reply_text(
        "📋 *Comandos disponíveis:*\n\n"
        "/start — Apresentação do bot\n"
        "/ajuda — Esta mensagem\n"
        "/limpar — Limpa o histórico de conversa\n"
        "/status — Verifica status do agente\n\n"
        "*Exemplos de uso:*\n"
        "• Busca: _\"Pesquise sobre o clima em Brasília\"_\n"
        "• Agenda: _\"Mostre minha agenda da semana\"_\n"
        "• Criar evento: _\"Marque consulta médica dia 20/06 às 10h\"_\n"
        "• Cancelar evento: _\"Cancele a reunião de amanhã\"_",
        parse_mode="Markdown"
    )


async def limpar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Limpa o histórico de conversa."""
    agent.clear_history()
    await update.message.reply_text(
        "🗑️ Histórico de conversa limpo! Podemos começar do zero."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verifica o status do agente."""
    msg_count = len(agent.conversation_history)
    await update.message.reply_text(
        f"✅ *Status do Agente:*\n\n"
        f"• Mensagens no histórico: {msg_count}\n"
        f"• Janela de contexto: máx. 20 mensagens\n"
        f"• Ferramentas ativas: Web Search, Google Calendar\n"
        f"• Modelo: Claude claude-opus-4-5",
        parse_mode="Markdown"
    )


# ── Handler de Mensagens ──────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens do usuário e retorna resposta do agente."""
    user_message = update.message.text
    user_name = update.effective_user.first_name

    logger.info(f"📱 Mensagem de {user_name}: {user_message[:80]}")

    # Feedback visual de processamento
    thinking_msg = await update.message.reply_text("⏳ Pensando...")

    try:
        # Chama o agente
        response = agent.process_message(user_message)
        
        # Apaga "pensando..." e envia resposta
        await thinking_msg.delete()
        
        # Divide mensagem longa (limite do Telegram: 4096 chars)
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
            "Erro ao processar sua mensagem. Tente novamente ou use /limpar para reiniciar."
        )


# ── Inicialização do Bot ──────────────────────────────────────────────────────
def main():
    """Inicia o bot do Telegram."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN não configurado!")

    logger.info("🚀 Iniciando bot do Telegram...")

    app = Application.builder().token(token).build()

    # Registra handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("limpar", limpar))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✅ Bot iniciado! Aguardando mensagens...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
