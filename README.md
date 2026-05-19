# 🤖 AgentBot — Do Chatbot ao Agente Autônomo

Agente autônomo com **loop ReAct** (Reasoning + Acting), implementando os 3 pilares da atividade:

| Pilar | Implementação |
|-------|---------------|
| **A — Raciocínio (Reasoning)** | Tags `<pensamento>` antes de cada ação; loop ReAct com até 8 iterações |
| **B — Memória de Contexto** | Janela deslizante de 20 mensagens; histórico completo enviado à API |
| **C — Habilidades Externas** | Web Search (Tavily) + Google Calendar |

---

## 📁 Estrutura do Projeto

```
agente/
├── agent.py          # Núcleo do agente (loop ReAct + memória)
├── tools.py          # Ferramentas externas (busca + calendário)
├── bot.py            # Interface do Telegram
├── requirements.txt  # Dependências Python
├── .env.example      # Template de variáveis de ambiente
└── README.md         # Este arquivo
```

---

## ⚙️ Configuração Passo a Passo

### 1. Instalar Dependências

```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 2. Criar o Bot no Telegram

1. Abra o Telegram e procure por **@BotFather**
2. Envie `/newbot`
3. Escolha um nome e username para o bot
4. Copie o **token** gerado

### 3. Obter as API Keys

| Serviço | URL | Plano Gratuito |
|---------|-----|----------------|
| Anthropic (Claude) | https://console.anthropic.com/ | $5 de crédito grátis |
| Tavily (busca) | https://tavily.com/ | 1.000 buscas/mês |

### 4. Configurar Variáveis de Ambiente

```bash
cp .env.example .env
# Edite o arquivo .env com suas chaves
```

### 5. Configurar Google Calendar (OAuth2)

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/)
2. Crie um novo projeto ou selecione um existente
3. Vá em **APIs e Serviços → Biblioteca**
4. Busque e ative **Google Calendar API**
5. Vá em **APIs e Serviços → Credenciais**
6. Clique em **Criar Credenciais → ID do cliente OAuth 2.0**
7. Tipo de aplicativo: **App para computador**
8. Baixe o arquivo JSON e renomeie para `credentials.json`
9. Coloque o `credentials.json` na pasta do projeto

Na **primeira execução**, uma janela do navegador abrirá para você autorizar o acesso. Um arquivo `token.json` será criado automaticamente para as próximas execuções.

### 6. Executar o Bot

```bash
# Carrega variáveis do .env automaticamente
python -c "from dotenv import load_dotenv; load_dotenv()"
python bot.py
```

Ou em um único comando:

```bash
python -c "
from dotenv import load_dotenv
load_dotenv()
import bot
bot.main()
"
```

---

## 🧪 Exemplos de Uso

### Busca Web
```
Você: Quais são as últimas notícias sobre inteligência artificial?
Bot: [busca no Tavily e responde com fontes atualizadas]
```

### Google Calendar — Listar
```
Você: Quais são meus compromissos esta semana?
Bot: [lista eventos do calendário primário]
```

### Google Calendar — Criar
```
Você: Marque uma consulta médica na sexta-feira às 10h no Hospital das Clínicas
Bot: [cria evento e confirma]
```

### Google Calendar — Cancelar
```
Você: Cancele a reunião de amanhã
Bot: [lista eventos, identifica o correto, confirma e remove]
```

---

## 🏗️ Arquitetura do Agente

```
Usuário (Telegram)
        ↓
   bot.py (interface)
        ↓
   agent.py (loop ReAct)
        ↓
  [Pensamento → Ação → Observação → Resposta]
        ↓
   tools.py (ferramentas)
    ├── Tavily API (busca web)
    └── Google Calendar API
```

### Loop ReAct Detalhado

```
1. Recebe mensagem do usuário
2. Adiciona ao histórico (memória deslizante)
3. Envia para Claude com system prompt + ferramentas
4. Claude responde com <pensamento> + ação
5. Se tool_use → executa ferramenta → adiciona resultado
6. Volta ao passo 3 (máx. 8 iterações)
7. Quando end_turn → limpa tags → envia ao usuário
```

---

## 📊 Critérios de Avaliação Atendidos

| Critério | Como foi implementado |
|----------|----------------------|
| **Qualidade do System Prompt** | Prompt estruturado em seções: processo de raciocínio, ferramentas, regras e personalidade |
| **Tratamento de Erros** | Try/catch em todas as ferramentas; mensagens claras ao usuário; fallback no loop |
| **Logs de Pensamento** | Tags `<pensamento>` extraídas e logadas no terminal via `logging` |
| **Eficiência de Tokens** | Janela deslizante de 20 mensagens; respostas de ferramentas truncadas a 500 chars |

---

## 🔧 Solução de Problemas

**Erro: `ANTHROPIC_API_KEY não configurada`**
→ Verifique se o arquivo `.env` existe e tem a chave correta

**Erro: `credentials.json não encontrado`**
→ Siga o passo 5 de configuração do Google Calendar

**O bot não responde no Telegram**
→ Verifique o `TELEGRAM_BOT_TOKEN` e se o bot foi iniciado sem erros

**Erro de autenticação no Google**
→ Delete o `token.json` e execute novamente para reautorizar
