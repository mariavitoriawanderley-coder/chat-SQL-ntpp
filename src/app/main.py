"""Ponto de entrada do serviço.

Um container serve a API e o front. A ORDEM de montagem importa:

1. rotas da API sob `/api`         — declaradas primeiro, vencem sempre;
2. assets estáticos em `/assets`   — o que o Vite gera com hash no nome;
3. catch-all devolvendo index.html — faz o roteamento no cliente sobreviver
   a um F5 em qualquer URL.

Em desenvolvimento os dois rodam separados (Vite na 5173, uvicorn na 8000) e a
pasta `static/` nem existe. O código trata essa ausência em vez de estourar.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.deps import obter_catalogo
from app.api.v1 import router as router_v1
from app.core.config import obter_config
from app.core.exceptions import registrar_handlers
from app.core.logging import configurar_logging, obter_logger
from app.domain.errors import CatalogoInvalido

cfg = obter_config()
configurar_logging(nivel=cfg.log_level, ambiente=cfg.ambiente)
log = obter_logger("main")


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    # Catálogo primeiro: se algum YAML estiver quebrado, o serviço não sobe.
    # Falhar aqui é barulhento e óbvio; ignorar seria silencioso e caríssimo
    # de diagnosticar depois.
    #
    # Exceção só no ambiente local: o serviço sobe mesmo assim e cada rota que
    # depende do catálogo devolve a lista de erros, para o front mostrá-la na
    # tela. Como `obter_catalogo` não guarda falha em cache, corrigir o YAML e
    # recarregar a página basta — sem reiniciar o uvicorn.
    try:
        tabelas_ativas = len(obter_catalogo().indice())
    except CatalogoInvalido as e:
        log.error("catalogo_invalido", mensagem=e.mensagem)
        if cfg.ambiente != "local":
            raise RuntimeError(f"{e.mensagem}\n{e.detalhe or ''}") from e
        tabelas_ativas = 0

    log.info(
        "servico_iniciado",
        versao=cfg.versao,
        ambiente=cfg.ambiente,
        tabelas_ativas=tabelas_ativas,
        front_compilado=cfg.dir_estaticos.is_dir(),
    )
    yield
    log.info("servico_encerrado")


app = FastAPI(
    title=cfg.nome_app,
    version=cfg.versao,
    lifespan=ciclo_de_vida,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

registrar_handlers(app)

if cfg.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# 1 — API
app.include_router(router_v1)

# 2 — assets compilados
_estaticos = cfg.dir_estaticos
if (_estaticos / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_estaticos / "assets"), name="assets")

_index = _estaticos / "index.html"


# 3 — catch-all
# `response_model=None`: a rota devolve Response direto, e sem isso o FastAPI
# tenta derivar um modelo Pydantic da anotação de retorno e falha no import.
@app.get("/{caminho:path}", include_in_schema=False, response_model=None)
async def servir_front(caminho: str) -> FileResponse | JSONResponse:
    # Um /api/... que chegou até aqui é rota inexistente, não uma URL do front.
    # Sem esta guarda, um erro de digitação no endpoint devolveria HTML 200 e o
    # front tentaria fazer JSON.parse de "<!DOCTYPE html>".
    if caminho.startswith("api/") or caminho == "api":
        return JSONResponse(
            status_code=404,
            content={"erro": {"codigo": "nao_encontrado", "mensagem": "Rota inexistente."}},
        )

    # Arquivos soltos na raiz do build (favicon, robots.txt, manifest).
    if caminho:
        alvo = _resolver_dentro(_estaticos, caminho)
        if alvo is not None and alvo.is_file():
            return FileResponse(alvo)

    if not _index.is_file():
        return JSONResponse(
            status_code=503,
            content={
                "erro": {
                    "codigo": "front_ausente",
                    "mensagem": (
                        "O front ainda não foi compilado. Rode `make build-web` "
                        "ou acesse o servidor de desenvolvimento do Vite."
                    ),
                }
            },
        )
    return FileResponse(_index)


def _resolver_dentro(base: Path, caminho: str) -> Path | None:
    """Resolve `caminho` sob `base`, recusando qualquer coisa que escape dela.

    Barra a travessia de diretório (`../../etc/passwd`) comparando o caminho
    já resolvido com a base resolvida.
    """
    try:
        alvo = (base / caminho).resolve()
        alvo.relative_to(base.resolve())
    except (ValueError, OSError):
        return None
    return alvo
