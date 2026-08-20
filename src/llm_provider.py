"""
Abstração sobre o provedor de LLM usado na Fase 4 (geração).

O restante do pipeline (ingest/embed/retrieve) é local e não depende de
nenhum provedor externo — só a geração da resposta final precisa de um LLM.
Essa camada existe pra não travar isso no Anthropic: troque o provider sem
mexer em generate.py.

Como implementar seu próprio provider:
1. Crie uma classe que herda de LLMProvider e implementa generate(prompt) -> str.
   Essa é a única regra: recebe o prompt já montado (string) e devolve o
   texto da resposta (string).
2. A classe é responsável pela própria autenticação (variável de ambiente,
   etc.) e pelo próprio retry em erros transitórios — ver AnthropicProvider
   como referência.
3. Registre a classe no dicionário PROVIDERS, associada a um nome.
4. Selecione seu provider via variável de ambiente LLM_PROVIDER (default:
   "anthropic") em .env.

generate.py sempre chama get_provider().generate(prompt) — não sabe (nem
precisa saber) qual provider está por trás.
"""

import os
import time
from abc import ABC, abstractmethod

import anthropic


class LLMProvider(ABC):
    """Interface que todo provider de LLM precisa implementar."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Envia o prompt ao modelo e retorna o texto da resposta."""
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    """Provider de referência, usando a API do Anthropic (Claude).

    Requer ANTHROPIC_API_KEY em .env (ver .env.example).
    """

    MODEL = "claude-haiku-4-5"
    MAX_TOKENS = 2048
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 5

    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY não encontrada. Copie .env.example para .env e preencha a chave.")
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, prompt: str) -> str:
        response = self._call_with_retry(lambda: self._client.messages.create(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        ))
        return next(block.text for block in response.content if block.type == "text")

    def _call_with_retry(self, request_fn):
        """Roda request_fn() com retry em erros retentáveis (429 e 5xx)."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return request_fn()
            except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
                retryable = isinstance(e, anthropic.RateLimitError) or e.status_code >= 500
                if retryable and attempt < self.MAX_RETRIES:
                    print(f"  Erro {getattr(e, 'status_code', 429)}, retrying in {self.RETRY_DELAY_SECONDS}s... ({attempt}/{self.MAX_RETRIES})")
                    time.sleep(self.RETRY_DELAY_SECONDS)
                    continue
                raise
        raise RuntimeError("Failed to call the model after multiple retries")


class GeminiProvider(LLMProvider):
    """Provider usando a API do Gemini via Google AI Studio.

    Requer GEMINI_API_KEY em .env.
    """

    MODEL = "gemini-3.6-flash"
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 5

    def __init__(self):
        try:
            from google import genai
        except ImportError:
            raise RuntimeError("Pacote google-genai não encontrado. Instale com: pip install google-genai")
            
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY não encontrada. Copie .env.example para .env e preencha a chave.")
        self._client = genai.Client(api_key=api_key)

    def generate(self, prompt: str) -> str:
        response = self._call_with_retry(lambda: self._client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
        ))
        return response.text

    def _call_with_retry(self, request_fn):
        """Roda request_fn() com retry em erros transitórios."""
        from google.genai import errors
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return request_fn()
            except errors.APIError as e:
                # Retry em erros transitórios (429 e 5xx)
                retryable = getattr(e, 'code', 500) == 429 or getattr(e, 'code', 500) >= 500
                if retryable and attempt < self.MAX_RETRIES:
                    print(f"  Erro {getattr(e, 'code', 'desconhecido')} do Gemini, retrying in {self.RETRY_DELAY_SECONDS}s... ({attempt}/{self.MAX_RETRIES})")
                    time.sleep(self.RETRY_DELAY_SECONDS)
                    continue
                raise
        raise RuntimeError("Failed to call the model after multiple retries")


class OpenAIProvider(LLMProvider):
    """Provider usando a API da OpenAI.

    Requer OPENAI_API_KEY em .env.
    """

    MODEL = "gpt-4o-mini"
    MAX_TOKENS = 2048
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 5

    def __init__(self):
        try:
            import openai
        except ImportError:
            raise RuntimeError("Pacote openai não encontrado. Instale com: pip install openai")
            
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY não encontrada. Copie .env.example para .env e preencha a chave.")
        self._client = openai.OpenAI(api_key=api_key)

    def generate(self, prompt: str) -> str:
        response = self._call_with_retry(lambda: self._client.chat.completions.create(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        ))
        return response.choices[0].message.content

    def _call_with_retry(self, request_fn):
        """Roda request_fn() com retry em erros transitórios."""
        import openai
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return request_fn()
            except (openai.RateLimitError, openai.APIStatusError) as e:
                retryable = isinstance(e, openai.RateLimitError) or getattr(e, 'status_code', 200) >= 500
                if retryable and attempt < self.MAX_RETRIES:
                    print(f"  Erro {getattr(e, 'status_code', 429)} da OpenAI, retrying in {self.RETRY_DELAY_SECONDS}s... ({attempt}/{self.MAX_RETRIES})")
                    time.sleep(self.RETRY_DELAY_SECONDS)
                    continue
                raise
        raise RuntimeError("Failed to call the model after multiple retries")


# Nome usado em LLM_PROVIDER -> classe do provider.
# Adicione sua classe aqui depois de implementá-la.
PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
}


def get_provider(name: str | None = None) -> LLMProvider:
    """Instancia o provider selecionado (default: LLM_PROVIDER em .env, ou "anthropic")."""
    name = name or os.environ.get("LLM_PROVIDER", "anthropic")
    try:
        provider_cls = PROVIDERS[name]
    except KeyError:
        raise ValueError(f"Provider desconhecido: {name!r}. Providers disponíveis: {list(PROVIDERS)}")
    return provider_cls()
