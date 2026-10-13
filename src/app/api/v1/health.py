"""GET /api/v1/health — sinal de vida do serviço.

O Cloud Run usa esta rota para saber se o container subiu. Ela responde sem
tocar em BigQuery nem em Gemini: um health check que depende de rede externa
derruba o serviço quando o problema está do outro lado. O catálogo é exceção
justificada — já está em memória desde o startup, ler dele não custa nada.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import Catalogo
from app.core.config import obter_config

router = APIRouter(tags=["saude"])


class RespostaSaude(BaseModel):
    status: str
    versao: str
    ambiente: str
    tabelas_carregadas: int
    tabelas_rascunho: int


@router.get("/health", response_model=RespostaSaude)
async def health(catalogo: Catalogo) -> RespostaSaude:
    cfg = obter_config()
    ativas = catalogo.indice()
    todas = catalogo.todas(incluir_rascunhos=True)
    return RespostaSaude(
        status="ok",
        versao=cfg.versao,
        ambiente=cfg.ambiente,
        tabelas_carregadas=len(ativas),
        tabelas_rascunho=len(todas) - len(ativas),
    )
