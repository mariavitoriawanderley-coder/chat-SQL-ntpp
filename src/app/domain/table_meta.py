"""Entidades do catálogo de tabelas.

Camada pura: descreve o que é uma tabela cadastrada, sem saber de onde ela foi
lida nem para onde vai. O carregamento dos YAML mora em
`services/catalog_service.py`; o contrato HTTP, em `schemas/catalog.py`.

O cadastro é preenchido à mão pelo desenvolvedor, então a validação aqui é
severa de propósito: um resumo vago ou uma partição declarada que não existe
entre as colunas só apareceria como consulta cara ou SQL errado lá na frente,
onde o rastro até a causa é longo.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Area = Literal["educacao", "saude", "economia"]

# `rascunho` é o gabarito recém-criado, ainda com TODO nos campos. Ele é
# validado na estrutura mas fica FORA do índice que vai ao modelo — o que
# impede que uma tabela pela metade seja escolhida para responder alguém.
Status = Literal["rascunho", "ativo"]

# Tipos do BigQuery que o catálogo aceita. A lista é curta de propósito:
# tipo fora dela é quase sempre erro de digitação no cadastro.
TipoColuna = Literal[
    "STRING",
    "INT64",
    "FLOAT64",
    "NUMERIC",
    "BIGNUMERIC",
    "BOOL",
    "DATE",
    "DATETIME",
    "TIME",
    "TIMESTAMP",
    "GEOGRAPHY",
]

SENTINELA_PENDENTE = "TODO"

# Projeto que hospeda o datalake público da Base dos Dados no BigQuery.
PROJETO_BASE_DOS_DADOS = "basedosdados"


class ColumnMeta(BaseModel):
    """Uma coluna da tabela, como o modelo vai vê-la na etapa 3."""

    model_config = ConfigDict(extra="forbid")

    nome: str
    tipo: TipoColuna
    descricao: str
    particao: bool = False
    valores_exemplo: list[str] = Field(default_factory=list)
    nota: str | None = None

    @field_validator("valores_exemplo", mode="before")
    @classmethod
    def _tudo_texto(cls, v: object) -> object:
        # No YAML `valores_exemplo: [2020, 2021]` vira int. Como o valor só
        # serve de amostra para o prompt, texto basta e evita erro de tipo.
        if isinstance(v, list):
            return [str(item) for item in v]
        return v


class CoberturaTemporal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inicio: int | None = None
    fim: int | None = None

    @model_validator(mode="after")
    def _ordem(self) -> Self:
        if self.inicio is not None and self.fim is not None and self.inicio > self.fim:
            raise ValueError(f"início ({self.inicio}) é posterior ao fim ({self.fim})")
        return self


class ConsultaExemplo(BaseModel):
    """Few-shot para a geração de SQL: ensina o padrão de filtro por partição."""

    model_config = ConfigDict(extra="forbid")

    pergunta: str
    sql: str


class TableMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ─── Identificação ─────────────────────────────────────────────
    id: str
    dataset_id: str
    table_id: str
    nome_exibicao: str
    area: Area
    fonte: str
    url_documentacao: str | None = None
    status: Status = "rascunho"

    # ─── Resumo (etapa 2, seleção de tabela) ───────────────────────
    resumo: str
    palavras_chave: list[str] = Field(default_factory=list)
    perguntas_exemplo: list[str] = Field(default_factory=list)

    # ─── Características ───────────────────────────────────────────
    grao: str
    cobertura_temporal: CoberturaTemporal = Field(default_factory=CoberturaTemporal)
    cobertura_geografica: str | None = None
    particoes: list[str] = Field(default_factory=list)
    # Reconhecimento explícito de que a tabela não tem partição nenhuma. Sem
    # ele, `particoes` vazia é tratada como cadastro esquecido — porque quase
    # sempre é, e o preço do engano é uma varredura da tabela inteira.
    sem_particao: bool = False
    volume_aproximado: str | None = None
    observacoes: str | None = None

    # ─── Colunas (etapa 3, geração do SQL) ─────────────────────────
    colunas: list[ColumnMeta] = Field(default_factory=list)
    consultas_exemplo: list[ConsultaExemplo] = Field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def referencia_bigquery(self) -> str:
        """`basedosdados.dataset.table` — como a tabela aparece no FROM.

        É desta propriedade que sai a whitelist do validador de SQL: uma
        consulta só pode citar tabelas que existem no catálogo.
        """
        return f"{PROJETO_BASE_DOS_DADOS}.{self.dataset_id}.{self.table_id}"

    @property
    def pendente(self) -> bool:
        return self.status == "rascunho"

    def coluna(self, nome: str) -> ColumnMeta | None:
        return next((c for c in self.colunas if c.nome == nome), None)

    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _coerencia(self) -> Self:
        nomes = [c.nome for c in self.colunas]
        repetidas = {n for n in nomes if nomes.count(n) > 1}
        if repetidas:
            raise ValueError(f"colunas repetidas: {', '.join(sorted(repetidas))}")

        # Uma partição declarada que não existe entre as colunas faria o
        # validador da etapa 4 exigir um filtro impossível de escrever.
        ausentes = [p for p in self.particoes if p not in nomes]
        if ausentes:
            raise ValueError(
                f"partições declaradas que não existem entre as colunas: {', '.join(ausentes)}"
            )

        # As duas listas dizem a mesma coisa; discordância é erro de cadastro.
        marcadas = {c.nome for c in self.colunas if c.particao}
        declaradas = set(self.particoes)
        if marcadas != declaradas:
            so_na_coluna = sorted(marcadas - declaradas)
            so_na_lista = sorted(declaradas - marcadas)
            detalhe = []
            if so_na_coluna:
                detalhe.append(f"com `particao: true` mas fora de `particoes`: {so_na_coluna}")
            if so_na_lista:
                detalhe.append(f"em `particoes` mas sem `particao: true` na coluna: {so_na_lista}")
            raise ValueError("; ".join(detalhe))

        if self.sem_particao and self.particoes:
            raise ValueError("`sem_particao: true` contradiz a lista `particoes` preenchida")

        if self.status == "ativo":
            self._exigir_cadastro_completo()

        return self

    def _exigir_cadastro_completo(self) -> None:
        """Regras que só valem para tabela publicada.

        O gabarito recém-criado tem TODO em tudo e precisa poder existir no
        repositório; a tabela marcada `ativo` é a que o modelo vai ver, e aí
        não há espaço para campo pela metade.
        """
        for campo in ("resumo", "grao", "nome_exibicao", "fonte"):
            valor = str(getattr(self, campo) or "").strip()
            if not valor or valor.upper().startswith(SENTINELA_PENDENTE):
                raise ValueError(
                    f"`{campo}` ainda está por preencher — "
                    f"tabela com `status: ativo` não pode ter {SENTINELA_PENDENTE}"
                )

        # O resumo é a ÚNICA coisa que o modelo lê ao escolher a tabela.
        # Curto demais e ele escolhe errado.
        if len(self.resumo.split()) < 20:
            raise ValueError(
                "`resumo` tem menos de 20 palavras. É o único texto que o modelo lê "
                "na seleção de tabela — descreva o que a tabela contém, quem produz "
                "e que perguntas ela responde."
            )

        if not self.colunas:
            raise ValueError("`colunas` está vazia — sem elas não há como gerar SQL")

        if not self.particoes and not self.sem_particao:
            raise ValueError(
                "`particoes` está vazia. Se a tabela realmente não tem partição, "
                "escreva `sem_particao: true` — toda consulta a ela vai varrer a "
                "tabela inteira, e isso precisa ser uma decisão, não um esquecimento."
            )
