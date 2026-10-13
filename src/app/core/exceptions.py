"""Tradução de exceções em resposta HTTP.

Todo erro sai no mesmo formato — `{ "erro": { "codigo", "mensagem" } }` —
para que o front tenha um único caminho de tratamento.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import obter_config
from app.core.logging import obter_logger
from app.domain.errors import ErroDominio

log = obter_logger("erro")


def _corpo(codigo: str, mensagem: str, detalhe: str | None = None) -> dict:
    erro = {"codigo": codigo, "mensagem": mensagem}
    if detalhe:
        erro["detalhe"] = detalhe
    return {"erro": erro}


def registrar_handlers(app: FastAPI) -> None:
    @app.exception_handler(ErroDominio)
    async def _dominio(_req: Request, exc: ErroDominio) -> JSONResponse:
        log.warning("erro_dominio", codigo=exc.codigo, detalhe=exc.detalhe)
        # O detalhe pode citar caminho de arquivo e estrutura interna: só sai
        # do servidor no ambiente local, onde quem lê é quem está cadastrando.
        detalhe = exc.detalhe if obter_config().ambiente == "local" else None
        return JSONResponse(
            status_code=exc.status_http,
            content=_corpo(exc.codigo, exc.mensagem, detalhe),
        )

    @app.exception_handler(RequestValidationError)
    async def _validacao(_req: Request, exc: RequestValidationError) -> JSONResponse:
        log.warning("entrada_invalida", erros=exc.errors())
        return JSONResponse(
            status_code=422,
            content=_corpo("entrada_invalida", "Os dados enviados não estão no formato esperado."),
        )

    @app.exception_handler(Exception)
    async def _inesperado(_req: Request, exc: Exception) -> JSONResponse:
        # O detalhe fica no log; o usuário recebe uma frase acionável.
        log.exception("erro_inesperado", tipo=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=_corpo(
                "erro_interno",
                "A aplicação encontrou uma falha ao processar o pedido. Tente novamente.",
            ),
        )
