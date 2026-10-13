"""Contratos HTTP do catálogo.

Separado de `domain/table_meta.py` de propósito: o que o cadastro guarda e o
que a API expõe mudam por motivos diferentes. O índice, em especial, é
deliberadamente magro — a tela "o que posso perguntar" não precisa de coluna
nenhuma, e mandar 40 colunas por tabela só encheria a rede.
"""

from pydantic import BaseModel

from app.domain.table_meta import ColumnMeta, ConsultaExemplo, TableMeta


class ResumoTabela(BaseModel):
    """Item do índice. Sem colunas."""

    id: str
    nome_exibicao: str
    area: str
    fonte: str
    resumo: str
    palavras_chave: list[str]
    perguntas_exemplo: list[str]
    cobertura_inicio: int | None
    cobertura_fim: int | None
    total_colunas: int

    @classmethod
    def de(cls, t: TableMeta) -> "ResumoTabela":
        return cls(
            id=t.id,
            nome_exibicao=t.nome_exibicao,
            area=t.area,
            fonte=t.fonte,
            resumo=t.resumo,
            palavras_chave=t.palavras_chave,
            perguntas_exemplo=t.perguntas_exemplo,
            cobertura_inicio=t.cobertura_temporal.inicio,
            cobertura_fim=t.cobertura_temporal.fim,
            total_colunas=len(t.colunas),
        )


class IndiceCatalogo(BaseModel):
    total: int
    areas: list[str]
    tabelas: list[ResumoTabela]


class DetalheTabela(BaseModel):
    """Uma tabela por inteiro, incluindo colunas e consultas de exemplo."""

    id: str
    dataset_id: str
    table_id: str
    referencia_bigquery: str
    nome_exibicao: str
    area: str
    fonte: str
    url_documentacao: str | None
    resumo: str
    palavras_chave: list[str]
    perguntas_exemplo: list[str]
    grao: str
    cobertura_inicio: int | None
    cobertura_fim: int | None
    cobertura_geografica: str | None
    particoes: list[str]
    volume_aproximado: str | None
    observacoes: str | None
    colunas: list[ColumnMeta]
    consultas_exemplo: list[ConsultaExemplo]

    @classmethod
    def de(cls, t: TableMeta) -> "DetalheTabela":
        return cls(
            id=t.id,
            dataset_id=t.dataset_id,
            table_id=t.table_id,
            referencia_bigquery=t.referencia_bigquery,
            nome_exibicao=t.nome_exibicao,
            area=t.area,
            fonte=t.fonte,
            url_documentacao=t.url_documentacao,
            resumo=t.resumo,
            palavras_chave=t.palavras_chave,
            perguntas_exemplo=t.perguntas_exemplo,
            grao=t.grao,
            cobertura_inicio=t.cobertura_temporal.inicio,
            cobertura_fim=t.cobertura_temporal.fim,
            cobertura_geografica=t.cobertura_geografica,
            particoes=t.particoes,
            volume_aproximado=t.volume_aproximado,
            observacoes=t.observacoes,
            colunas=t.colunas,
            consultas_exemplo=t.consultas_exemplo,
        )
