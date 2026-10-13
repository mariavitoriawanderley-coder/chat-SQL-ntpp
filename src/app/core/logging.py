"""Log estruturado em JSON.

O Cloud Logging lê JSON da saída padrão e indexa os campos automaticamente.
Localmente a saída sai colorida e legível, porque ninguém depura lendo JSON.
"""

import logging
import sys

import structlog


def saida_utf8() -> None:
    """Força UTF-8 na saída padrão.

    O console do Windows ainda usa cp1252 e transformaria `catálogo` em
    `cat�logo` — justamente nas mensagens de erro do catálogo, que existem
    para ser lidas. Em Linux (Cloud Run) já é UTF-8 e a chamada é inócua.
    """
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")


def configurar_logging(nivel: str = "INFO", ambiente: str = "local") -> None:
    saida_utf8()
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=nivel.upper())

    processadores: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if ambiente == "producao":
        # `severity` é o campo que o Cloud Logging usa para o nível.
        processadores += [_renomear_nivel, structlog.processors.JSONRenderer()]
    else:
        processadores.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processadores,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[nivel.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _renomear_nivel(_logger: object, _nome: str, evento: dict) -> dict:
    if "level" in evento:
        evento["severity"] = evento.pop("level").upper()
    return evento


def obter_logger(nome: str = "app") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(nome)
