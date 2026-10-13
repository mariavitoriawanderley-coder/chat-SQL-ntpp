"""Mapa de temas das comissões da ALEPE.

Camada pura. Diz, para cada comissão e cada tema que ela acompanha, em quais
conjuntos de dados da Base dos Dados procurar. É o "onde procurar" da
aplicação: o catálogo (`table_meta.py`) descreve tabelas prontas para gerar
SQL; este mapa aponta o conjunto de dados certo para um assunto, inclusive os
que ainda não têm tabela cadastrada.

A fonte é a planilha `dados/temas_comissoes_alepe.xlsx`, convertida para
`src/app/temas/comissoes.yaml` por `python -m app.cli importar-temas`.
"""

import re
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Todo link da planilha aponta para a página de um conjunto na Base dos Dados.
# O identificador é o UUID no fim da URL — é ele que liga o mapa ao catálogo.
PREFIXO_URL = "https://basedosdados.org/dataset/"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ConjuntoDados(BaseModel):
    """Um conjunto de dados da Base dos Dados indicado para o tema."""

    model_config = ConfigDict(extra="forbid")

    nome: str
    url: str

    @field_validator("url")
    @classmethod
    def _url_da_base_dos_dados(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(PREFIXO_URL) or not _UUID.match(v.removeprefix(PREFIXO_URL)):
            raise ValueError(f"o link precisa ser {PREFIXO_URL}<uuid>, e veio `{v}`")
        return v

    @property
    def dataset_uuid(self) -> str:
        return self.url.removeprefix(PREFIXO_URL)


class Tema(BaseModel):
    """Um assunto acompanhado pela comissão.

    Tema sem conjunto é permitido: registra que o assunto existe e ainda não
    tem fonte na Base dos Dados. A aplicação deve dizer isso ao usuário em vez
    de improvisar uma tabela parecida.
    """

    model_config = ConfigDict(extra="forbid")

    nome: str
    conjuntos: list[ConjuntoDados] = Field(default_factory=list)
    nota: str | None = None

    @property
    def sem_fonte(self) -> bool:
        return not self.conjuntos


class Comissao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sigla: str
    nome: str
    temas: list[Tema]

    @model_validator(mode="after")
    def _temas_unicos(self) -> Self:
        vistos: set[str] = set()
        for t in self.temas:
            if t.nome in vistos:
                raise ValueError(f"o tema `{t.nome}` aparece duas vezes em {self.sigla}")
            vistos.add(t.nome)
        return self


class MapaTemas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comissoes: list[Comissao]

    @model_validator(mode="after")
    def _siglas_unicas(self) -> Self:
        siglas = [c.sigla for c in self.comissoes]
        repetidas = sorted({s for s in siglas if siglas.count(s) > 1})
        if repetidas:
            raise ValueError(f"sigla de comissão repetida: {', '.join(repetidas)}")
        return self
