import threading
from types import SimpleNamespace

import httpx2
import openai
import pytest
from conftest import FakeLLM

from textsql.config import Settings
from textsql.llm import PROVIDERS, LLMClient, LLMError, get_llm
from textsql.llm.openai_compat import OpenAICompatibleClient


def test_fake_cumpre_o_protocolo():
    fake = FakeLLM("SELECT 1")
    assert isinstance(fake, LLMClient)
    assert fake.complete([{"role": "user", "content": "oi"}]) == "SELECT 1"
    assert len(fake.calls) == 1


@pytest.mark.parametrize("provider", list(PROVIDERS))
def test_factory_monta_cliente_do_provedor(provider):
    _, key_field = PROVIDERS[provider]
    settings = Settings(llm_provider=provider, llm_model="m", **{key_field: "chave"})
    llm = get_llm(settings)
    assert isinstance(llm, OpenAICompatibleClient)
    assert isinstance(llm, LLMClient)
    assert llm.model == "m"
    assert llm.base_url == PROVIDERS[provider][0]


def test_factory_falha_sem_chave():
    settings = Settings(llm_provider="groq", groq_api_key=None)
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        get_llm(settings)


def test_guarda_tokens_da_ultima_chamada_por_thread(monkeypatch):
    client = OpenAICompatibleClient(base_url="http://teste", api_key="k", model="m")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="SELECT 1"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    monkeypatch.setattr(client._client.chat.completions, "create", lambda **_: response)

    assert client.complete([{"role": "user", "content": "oi"}]) == "SELECT 1"
    assert client.last_usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    other = []
    thread = threading.Thread(target=lambda: other.append(client.last_usage))
    thread.start()
    thread.join()
    assert other == [None]  # outra sessão não vê o consumo desta


def test_erro_do_sdk_vira_llmerror(monkeypatch):
    client = OpenAICompatibleClient(base_url="http://teste", api_key="k", model="m")

    def fail(**_):
        raise openai.APIConnectionError(request=httpx2.Request("POST", "http://teste"))

    monkeypatch.setattr(client._client.chat.completions, "create", fail)
    with pytest.raises(LLMError, match="APIConnectionError"):
        client.complete([{"role": "user", "content": "oi"}])
