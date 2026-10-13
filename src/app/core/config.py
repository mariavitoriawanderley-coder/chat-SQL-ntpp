"""Configuração da aplicação, lida do ambiente.

Fonte única de verdade para tudo que muda entre máquina local e Cloud Run.
Nenhum outro módulo lê `os.environ` diretamente.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Configuracao(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ─── Identidade ────────────────────────────────────────────────
    nome_app: str = "Consulta a dados públicos"
    versao: str = "0.1.0"
    ambiente: Literal["local", "producao"] = "local"

    # ─── Servidor ──────────────────────────────────────────────────
    # O Cloud Run injeta PORT no container; respeitá-la é obrigatório.
    port: int = 8000
    log_level: str = "INFO"

    # Origens liberadas no CORS. Em produção o front é servido pelo próprio
    # FastAPI e a lista fica vazia; em dev o Vite roda na 5173.
    # `NoDecode`: sem ele o pydantic-settings tenta ler o valor como JSON antes
    # do validador abaixo, e `http://a,http://b` estoura na carga.
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # ─── Google Cloud ──────────────────────────────────────────────
    google_cloud_project: str = ""
    # Os datasets da Base dos Dados vivem na multirregião US. Confirmar antes
    # da Fase 2 — um valor errado faz o job falhar por região incompatível.
    bq_location: str = "US"
    bq_max_bytes_billed: int = 5_000_000_000
    bq_max_rows: int = 50_000

    # ─── Gemini ────────────────────────────────────────────────────
    gemini_api_key: str = ""

    # ─── Limites de sessão ─────────────────────────────────────────
    plan_cache_ttl_seconds: int = 900
    rate_limit_per_session: int = 20

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _dividir_origens(cls, v: object) -> object:
        """Aceita `a,b,c` na variável de ambiente além de lista JSON."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @property
    def raiz_projeto(self) -> Path:
        # config.py → core → app → src → raiz
        return Path(__file__).resolve().parents[3]

    @property
    def dir_catalogo(self) -> Path:
        """Cadastro das tabelas em YAML, versionado junto com o código."""
        return Path(__file__).resolve().parents[1] / "catalog"

    @property
    def arquivo_temas(self) -> Path:
        """Mapa comissão → tema → conjuntos de dados, gerado da planilha."""
        return Path(__file__).resolve().parents[1] / "temas" / "comissoes.yaml"

    @property
    def planilha_temas(self) -> Path:
        """Planilha que a equipe mantém no Excel — a fonte do mapa de temas."""
        return self.raiz_projeto / "dados" / "temas_comissoes_alepe.xlsx"

    @property
    def dir_estaticos(self) -> Path:
        """Onde ficam os arquivos do front compilado.

        Em produção, o Dockerfile copia `web/dist` para cá. Em desenvolvimento
        a pasta pode não existir — o `main` trata essa ausência.
        """
        return self.raiz_projeto / "static"


@lru_cache
def obter_config() -> Configuracao:
    return Configuracao()
