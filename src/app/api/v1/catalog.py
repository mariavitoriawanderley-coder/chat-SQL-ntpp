"""Rotas do catálogo.

Alimentam a tela "o que posso perguntar". O índice não devolve rascunhos —
uma tabela pela metade não deve aparecer como promessa ao usuário.
"""

from fastapi import APIRouter

from app.api.deps import Catalogo
from app.schemas.catalog import DetalheTabela, IndiceCatalogo, ResumoTabela

router = APIRouter(prefix="/catalog", tags=["catálogo"])


@router.get("", response_model=IndiceCatalogo, summary="Índice resumido das tabelas")
async def indice(catalogo: Catalogo) -> IndiceCatalogo:
    tabelas = catalogo.indice()
    return IndiceCatalogo(
        total=len(tabelas),
        areas=sorted({t.area for t in tabelas}),
        tabelas=[ResumoTabela.de(t) for t in tabelas],
    )


@router.get("/{id_tabela}", response_model=DetalheTabela, summary="Detalhe de uma tabela")
async def detalhe(id_tabela: str, catalogo: Catalogo) -> DetalheTabela:
    # `obter` levanta RecursoNaoEncontrado, que o handler global vira 404.
    return DetalheTabela.de(catalogo.obter(id_tabela))
