import os
import requests
from fastapi import FastAPI, Request, Query, HTTPException, Response
from dotenv import load_dotenv
from llm_provider import get_provider
from retrieve import retrieve

load_dotenv()

app = FastAPI()

# Inicializa o modelo de IA usando o provider configurado no .env
llm = get_provider()

def enviar_mensagem_whatsapp(numero_destino: str, texto_resposta: str):
    """Função auxiliar para enviar a resposta final via Meta Cloud API"""
    url = f"https://graph.facebook.com/v26.0/{os.getenv('WHATSAPP_PHONE_NUMBER_ID')}/messages"
    headers = {
        "Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": numero_destino,
        "type": "text",
        "text": {"body": texto_resposta}
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.status_code

@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    """Rota obrigatoria exigida pela Meta para validar seu Webhook"""
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("VERIFY_TOKEN"):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Token de verificação inválido")

@app.post("/webhook")
async def receber_mensagem(request: Request):
    """Rota que recebe as mensagens do usuário enviadas pelo WhatsApp"""
    dados = await request.json()
    
    # Valida se a estrutura do payload da Meta contém mensagens
    if "entry" in dados and dados["entry"][0].get("changes") and "messages" in dados["entry"][0]["changes"][0]["value"]:
        mensagem_objeto = dados["entry"][0]["changes"][0]["value"]["messages"][0]
        
        # Ignora se não for uma mensagem de texto (ex: imagens, localizações)
        if mensagem_objeto.get("type") != "text":
            return {"status": "tipo_nao_suportado"}
            
        numero_cliente = mensagem_objeto["from"]
        pergunta_cliente = mensagem_objeto["text"]["body"]
        
        print(f"Mensagem recebida de {numero_cliente}: {pergunta_cliente}")
        
        resposta_ia = processar_pergunta_rag(pergunta_cliente, "WhatsApp")
        enviar_mensagem_whatsapp(numero_cliente, resposta_ia)
        
    return {"status": "sucesso"}

def processar_pergunta_rag(pergunta_cliente: str, plataforma: str) -> str:
    """Aplica o fluxo de RAG para responder a pergunta."""
    # 1. Recuperar contexto do banco vetorial
    documentos_relevantes = retrieve(pergunta_cliente, top_k=3)
    contexto = "\n\n".join([f"[Fonte: {doc['source']}, p. {doc['page']}]\n{doc['text']}" for doc in documentos_relevantes])
    
    # 2. Montar o Prompt Sistêmico
    prompt = f"""Você é um assistente de atendimento automatizado prestativo e educado.
Use APENAS o contexto fornecido abaixo para responder à pergunta do usuário. 
Se a informação não estiver no contexto, diga educadamente que não possui essa informação no momento.

CONTEXTO:
{contexto}

PERGUNTA DO USUÁRIO:
{pergunta_cliente}

RESPOSTA (seja direto, amigável e formate com quebras de linha adequadas para o {plataforma}):"""

    # 3. Chamar a LLM
    return llm.generate(prompt)

def enviar_mensagem_telegram(chat_id: str, texto_resposta: str):
    """Função auxiliar para enviar a resposta final via Telegram API"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        print("Erro: TELEGRAM_BOT_TOKEN não configurado no .env")
        return None
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto_resposta
    }
    
    response = requests.post(url, json=payload)
    return response.status_code

@app.post("/telegram-webhook")
async def receber_mensagem_telegram(request: Request):
    """Rota que recebe as mensagens do usuário enviadas pelo Telegram"""
    dados = await request.json()
    
    # Valida estrutura básica do payload do Telegram
    if "message" in dados and "text" in dados["message"]:
        chat_id = str(dados["message"]["chat"]["id"])
        pergunta_cliente = dados["message"]["text"]
        
        print(f"Mensagem recebida do Telegram de {chat_id}: {pergunta_cliente}")
        
        resposta_ia = processar_pergunta_rag(pergunta_cliente, "Telegram")
        enviar_mensagem_telegram(chat_id, resposta_ia)
        
        
    return {"status": "sucesso"}

def enviar_mensagem_slack(channel_id: str, texto_resposta: str):
    """Função auxiliar para enviar a resposta final via Slack API"""
    token = os.getenv('SLACK_BOT_TOKEN')
    if not token:
        print("Erro: SLACK_BOT_TOKEN não configurado no .env")
        return None
        
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "channel": channel_id,
        "text": texto_resposta
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.status_code

@app.post("/slack-webhook")
async def receber_mensagem_slack(request: Request):
    """Rota que recebe as mensagens e eventos enviados pelo Slack"""
    dados = await request.json()
    
    # O Slack requer que novos webhooks respondam ao challenge de verificação
    if dados.get("type") == "url_verification":
        return Response(content=dados.get("challenge"), media_type="text/plain")
        
    if dados.get("type") == "event_callback":
        evento = dados.get("event", {})
        
        # Ignora mensagens de bots para evitar loops
        if evento.get("type") == "message" and not evento.get("bot_id"):
            channel_id = evento.get("channel")
            pergunta_cliente = evento.get("text")
            
            print(f"Mensagem recebida do Slack no canal {channel_id}: {pergunta_cliente}")
            
            resposta_ia = processar_pergunta_rag(pergunta_cliente, "Slack")
            enviar_mensagem_slack(channel_id, resposta_ia)
            
    return {"status": "sucesso"}

if __name__ == "__main__":
    import uvicorn
    # Executa o servidor na porta 8000 (sem reload para evitar problemas de importação do uvicorn)
    uvicorn.run(app, host="0.0.0.0", port=8000)
