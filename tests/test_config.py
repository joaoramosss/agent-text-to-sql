import pytest

from textsql.config import ENV_VARS, PROJECT_ROOT, Settings, load_settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isola os testes do .env real e de variáveis já exportadas no shell."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_env_example_documenta_todas_as_variaveis():
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    declared = {
        line.split("=", 1)[0].strip()
        for line in example.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert set(ENV_VARS) <= declared


def test_env_vars_apontam_para_campos_existentes():
    assert set(ENV_VARS.values()) <= set(Settings.model_fields)


def test_defaults_sem_env(tmp_path):
    settings = load_settings(env_file=tmp_path / "nao_existe.env")
    assert settings.llm_provider == "groq"
    assert settings.groq_api_key is None


def test_le_env_file_e_ignora_valores_vazios(tmp_path):
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=OpenRouter\nOPENROUTER_API_KEY=abc\nGROQ_API_KEY=\n")
    settings = load_settings(env_file=env)
    assert settings.llm_provider == "openrouter"
    assert settings.openrouter_api_key == "abc"
    assert settings.groq_api_key is None


def test_trace_file_padrao_e_off(tmp_path):
    assert load_settings(env_file=tmp_path / "nao_existe.env").trace_file.name == "traces.jsonl"
    env = tmp_path / ".env"
    env.write_text("TRACE_FILE=off\n")
    assert load_settings(env_file=env).trace_file is None


def test_provider_invalido_falha(tmp_path):
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=banana\n")
    with pytest.raises(ValueError):
        load_settings(env_file=env)
