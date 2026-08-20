import os
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from retrieve import retrieve
from llm_provider import get_provider
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
llm = get_provider()

class ChatRequest(BaseModel):
    message: str
    sender_id: str
    is_group: bool

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    print(f"Recebida mensagem via unofficial API: {req.message} de {req.sender_id} (Grupo: {req.is_group})")
    
    # 1. Recuperar contexto do banco vetorial
    documentos_relevantes = retrieve(req.message, top_k=3)
    contexto = "\n\n".join([f"[Fonte: {doc['source']}, p. {doc['page']}]\n{doc['text']}" for doc in documentos_relevantes])
    
    # 2. Montar o Prompt Sistêmico
    prompt = f"""Você é um assistente de atendimento automatizado prestativo e educado.
Use o contexto fornecido abaixo para responder à pergunta do usuário. 

REGRAS IMPORTANTES:
1. Se o usuário mandar apenas uma saudação ou conversa fiada (ex: "Oi", "Tudo bem?", "Bom dia"), responda EXATAMENTE com o seguinte texto:
"Olá! Eu sou a IA de Renan, mais conhecido com NaN (Not a Number). Como sou uma versão beta, algumas informações podem estar incompletas, mas estou aqui para ajudar!
Se você preferir, também pode falar diretamente com Renan. Como posso te ajudar hoje?"
NUNCA use HANDOFF para saudações.
2. Se o usuário fizer uma pergunta específica e a resposta NÃO estiver no contexto abaixo, responda APENAS com a palavra: HANDOFF

CONTEXTO:
{contexto}

PERGUNTA DO USUÁRIO:
{req.message}
"""
    # 3. Gerar resposta
    resposta_ia = llm.generate(prompt).strip()
    
    if resposta_ia == "HANDOFF":
        return {"handoff": True}
        
    # Anexa a frase de transferência para Renan se a resposta não for a saudação padrão
    if not resposta_ia.startswith("Olá! Eu sou a IA de Renan"):
        resposta_ia += " Se preferir uma ajuda mais específica, posso te transferir agora mesmo para falar com Renan."
    
    return {"reply": resposta_ia}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
