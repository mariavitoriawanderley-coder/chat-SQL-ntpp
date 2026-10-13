"""Injeção de dependências das rotas.

A camada `api` conhece só isto: uma função que devolve um serviço pronto.
Nenhuma rota constrói cliente de BigQuery, de Gemini ou lê arquivo do disco.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.core.config import obter_config
from app.services.catalog_service import ServicoCatalogo
from app.services.temas_service import ServicoTemas


@lru_cache
def obter_catalogo() -> ServicoCatalogo:
    """Instância única, carregada uma vez no startup.

    O catálogo é imutável em tempo de execução — vem de arquivos versionados
    junto com o código. Recarregar exige novo deploy, o que é a intenção.
    """
    cfg = obter_config()
    servico = ServicoCatalogo(cfg.dir_catalogo)
    if not servico.carregado:
        servico.carregar()
    return servico


@lru_cache
def obter_temas() -> ServicoTemas:
    """Mapa de temas das comissões — onde procurar cada assunto."""
    servico = ServicoTemas(obter_config().arquivo_temas)
    servico.carregar()
    return servico


Catalogo = Annotated[ServicoCatalogo, Depends(obter_catalogo)]
Temas = Annotated[ServicoTemas, Depends(obter_temas)]
