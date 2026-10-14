"""Carga e indexação do catálogo de tabelas.

Lê todos os YAML de `app/catalog/<area>/`, valida contra `TableMeta` e monta
duas estruturas em memória:

- **índice resumido** — identificação, resumo, palavras-chave e cobertura.
  É o único conteúdo que vai ao modelo na etapa 2 (seleção de tabela), e por
  isso não carrega coluna nenhuma: o prompt fica pequeno e barato.
- **detalhe completo** — indexado por `id`, recuperado sob demanda na etapa 3.

Um YAML malformado derruba o startup com o arquivo e o campo na mensagem.
Ignorar em silêncio seria pior: a tabela sumiria do índice e a aplicação diria
"não tenho cobertura" sem ninguém entender por quê.

Este módulo não conhece HTTP. Roda em teste e por linha de comando
(`make validar-catalogo`) sem subir servidor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.core.logging import obter_logger
from app.domain.errors import CatalogoInvalido, RecursoNaoEncontrado
from app.domain.table_meta import ArquivoAuxiliares, TabelaAuxiliar, TableMeta

log = obter_logger("catalogo")

# Arquivos que começam com `_` não são cadastro de tabela: documentação do
# formato (`_schema.yaml`) ou a lista de tabelas auxiliares, lida à parte.
PREFIXO_IGNORADO = "_"
EXTENSOES = (".yaml", ".yml")
ARQUIVO_AUXILIARES = "_auxiliares.yaml"


class ServicoCatalogo:
    def __init__(self, diretorio: Path) -> None:
        self._diretorio = diretorio
        self._tabelas: dict[str, TableMeta] = {}
        self._auxiliares: dict[str, TabelaAuxiliar] = {}
        self._carregado = False

    # ─── Carga ────────────────────────────────────────────────────────
    def carregar(self) -> None:
        """Lê e valida tudo. Levanta `CatalogoInvalido` no primeiro problema.

        Acumula TODOS os erros antes de levantar: quem está cadastrando cinco
        tabelas quer ver os cinco problemas de uma vez, não um por execução.
        """
        if not self._diretorio.is_dir():
            raise CatalogoInvalido(
                f"A pasta do catálogo não existe: {self._diretorio}",
                detalhe="Crie `src/app/catalog/<area>/` e cadastre ao menos uma tabela.",
            )

        tabelas: dict[str, TableMeta] = {}
        origem: dict[str, str] = {}
        problemas: list[str] = []

        for caminho in self._arquivos():
            rotulo = self._rotulo(caminho)
            try:
                tabela = self._ler(caminho)
            except CatalogoInvalido as e:
                problemas.append(e.mensagem)
                continue

            if tabela.id in tabelas:
                problemas.append(
                    f"{rotulo}: o id `{tabela.id}` já está em uso por "
                    f"{origem[tabela.id]}. Cada tabela precisa de um id único."
                )
                continue

            tabelas[tabela.id] = tabela
            origem[tabela.id] = rotulo

        auxiliares: dict[str, TabelaAuxiliar] = {}
        try:
            for aux in self._ler_auxiliares():
                if aux.id in tabelas or aux.id in auxiliares:
                    problemas.append(
                        f"catalog/{ARQUIVO_AUXILIARES}: `{aux.id}` aparece duas vezes "
                        "(ou também como tabela do catálogo). Deixe em um lugar só."
                    )
                    continue
                auxiliares[aux.id] = aux
        except CatalogoInvalido as e:
            problemas.append(e.mensagem)

        if problemas:
            raise CatalogoInvalido(
                "O catálogo tem cadastros inválidos e o serviço não pode subir.",
                detalhe="\n".join(f"  • {p}" for p in problemas),
            )

        self._tabelas = dict(sorted(tabelas.items()))
        self._auxiliares = dict(sorted(auxiliares.items()))
        self._carregado = True

        ativas = [t for t in self._tabelas.values() if not t.pendente]
        log.info(
            "catalogo_carregado",
            arquivos=len(self._tabelas),
            ativas=len(ativas),
            rascunhos=len(self._tabelas) - len(ativas),
            auxiliares=len(self._auxiliares),
        )

    def _ler_auxiliares(self) -> list[TabelaAuxiliar]:
        """Tabelas de apoio (diretórios) que o SQL pode unir. Arquivo opcional."""
        caminho = self._diretorio / ARQUIVO_AUXILIARES
        if not caminho.is_file():
            return []
        rotulo = f"catalog/{ARQUIVO_AUXILIARES}"
        try:
            bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise CatalogoInvalido(f"{rotulo}: o YAML não pôde ser lido. {_resumir_yaml(e)}") from e
        try:
            return ArquivoAuxiliares.model_validate(bruto).auxiliares
        except ValidationError as e:
            raise CatalogoInvalido(f"{rotulo}:\n{_formatar_erros(e)}") from e

    def _arquivos(self) -> list[Path]:
        return sorted(
            c
            for c in self._diretorio.rglob("*")
            if c.is_file()
            and c.suffix.lower() in EXTENSOES
            and not c.name.startswith(PREFIXO_IGNORADO)
        )

    def _ler(self, caminho: Path) -> TableMeta:
        rotulo = self._rotulo(caminho)

        try:
            bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise CatalogoInvalido(f"{rotulo}: o YAML não pôde ser lido. {_resumir_yaml(e)}") from e
        except OSError as e:
            raise CatalogoInvalido(f"{rotulo}: não foi possível abrir o arquivo. {e}") from e

        if bruto is None:
            raise CatalogoInvalido(f"{rotulo}: o arquivo está vazio.")
        if not isinstance(bruto, dict):
            raise CatalogoInvalido(
                f"{rotulo}: o conteúdo precisa ser um mapa de campos, "
                f"e veio {type(bruto).__name__}."
            )

        try:
            tabela = TableMeta.model_validate(bruto)
        except ValidationError as e:
            raise CatalogoInvalido(f"{rotulo}:\n{_formatar_erros(e)}") from e

        self._conferir_convencoes(tabela, caminho, rotulo)
        return tabela

    def _conferir_convencoes(self, tabela: TableMeta, caminho: Path, rotulo: str) -> None:
        """Regras que dependem de onde o arquivo está, não do seu conteúdo."""
        if caminho.stem != tabela.id:
            raise CatalogoInvalido(
                f"{rotulo}: o nome do arquivo (`{caminho.stem}`) precisa ser igual "
                f"ao campo `id` (`{tabela.id}`)."
            )

        esperado = f"{tabela.dataset_id}__{tabela.table_id}"
        if tabela.id != esperado:
            raise CatalogoInvalido(
                f"{rotulo}: o `id` deveria ser `{esperado}` "
                f"(`dataset_id` + `__` + `table_id`), e é `{tabela.id}`."
            )

        pasta = caminho.parent.name
        if pasta != tabela.area:
            raise CatalogoInvalido(
                f"{rotulo}: o arquivo está na pasta `{pasta}` mas declara "
                f"`area: {tabela.area}`. Mova o arquivo ou corrija o campo."
            )

    @staticmethod
    def _rotulo(caminho: Path) -> str:
        """Caminho curto e clicável, a partir de `catalog/`."""
        partes = caminho.parts
        if "catalog" in partes:
            return "/".join(partes[partes.index("catalog") :])
        return caminho.name

    # ─── Consulta ─────────────────────────────────────────────────────
    @property
    def carregado(self) -> bool:
        return self._carregado

    def todas(self, incluir_rascunhos: bool = False) -> list[TableMeta]:
        return [t for t in self._tabelas.values() if incluir_rascunhos or not t.pendente]

    def indice(self) -> list[TableMeta]:
        """As tabelas que o modelo pode escolher. Rascunho fica de fora."""
        return self.todas()

    def obter(self, id_tabela: str) -> TableMeta:
        tabela = self._tabelas.get(id_tabela)
        if tabela is None:
            raise RecursoNaoEncontrado(f"Não existe tabela com o identificador `{id_tabela}`.")
        return tabela

    def auxiliares(self) -> list[TabelaAuxiliar]:
        """Diretórios que o SQL pode unir para trocar código por nome."""
        return list(self._auxiliares.values())

    def whitelist(self) -> set[str]:
        """Referências `projeto.dataset.tabela` que o SQL pode citar.

        Base da validação da etapa 4 — qualquer outra tabela é rejeitada.
        Entram as tabelas ativas (rascunho não deve chegar a uma consulta) e
        as auxiliares, que só servem de JOIN e nunca são escolhidas sozinhas.
        """
        ativas = {t.referencia_bigquery for t in self.todas()}
        return ativas | {a.referencia_bigquery for a in self._auxiliares.values()}

    def por_area(self) -> dict[str, list[TableMeta]]:
        agrupado: dict[str, list[TableMeta]] = {}
        for tabela in self.todas():
            agrupado.setdefault(tabela.area, []).append(tabela)
        return agrupado


def _formatar_erros(e: ValidationError) -> str:
    """Erros do Pydantic no formato `campo: mensagem`, um por linha.

    O padrão do Pydantic é verboso e cita nomes de classe que não dizem nada
    a quem está editando YAML.
    """
    linhas = []
    for erro in e.errors():
        mensagem = erro["msg"].removeprefix("Value error, ")
        campo = _caminho_campo(erro["loc"])
        # loc vazio é erro do modelo inteiro (validador de coerência), não de
        # um campo. Chamá-lo de "(raiz)" não ajudaria ninguém.
        rotulo = f"campo `{campo}`" if campo else "coerência do cadastro"
        linhas.append(f"    {rotulo}: {mensagem}")
    return "\n".join(linhas)


def _caminho_campo(loc: tuple[Any, ...]) -> str:
    """`('colunas', 2, 'tipo')` → `colunas[2].tipo`."""
    partes: list[str] = []
    for item in loc:
        if isinstance(item, int):
            partes.append(f"[{item}]")
        elif partes:
            partes.append(f".{item}")
        else:
            partes.append(str(item))
    return "".join(partes)


def _resumir_yaml(e: yaml.YAMLError) -> str:
    marca = getattr(e, "problem_mark", None)
    problema = getattr(e, "problem", None) or str(e)
    if marca is not None:
        return f"Linha {marca.line + 1}, coluna {marca.column + 1}: {problema}."
    return f"{problema}."
