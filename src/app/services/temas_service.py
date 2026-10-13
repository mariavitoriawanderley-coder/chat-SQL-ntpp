"""Carga, busca e importação do mapa de temas das comissões.

Três responsabilidades, todas sem HTTP:

- **carregar** `src/app/temas/comissoes.yaml` e validar contra `MapaTemas`;
- **onde procurar**: dado um assunto em português, devolver os temas e os
  conjuntos de dados indicados para ele — ignorando acento e caixa, porque
  quem pergunta escreve "saude" e a planilha diz "Saúde";
- **importar** a planilha `.xlsx` que a equipe mantém e gerar o YAML.

A leitura do `.xlsx` usa só a biblioteca padrão (o formato é um zip de XML).
Uma dependência inteira para ler quatro colunas de uma aba não se paga.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.logging import obter_logger
from app.domain.errors import CatalogoInvalido
from app.domain.temas import Comissao, ConjuntoDados, MapaTemas, Tema

log = obter_logger("temas")

# Cabeçalho esperado na primeira linha da planilha, na ordem das colunas A a D.
CABECALHO = ("Comissão", "Tema", "Conjunto de dados", "Link do banco de dados")

# Palavras que não ajudam a achar tema nenhum ("dados de saúde da mulher").
# sem acento — a comparação acontece depois de `_normalizar`
_VAZIAS = frozenset(
    {
        *("a", "o", "as", "os", "e", "um", "uma", "ao", "aos"),
        *("de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas"),
        *("por", "para", "com", "sem", "contra", "sobre", "entre", "ate"),
        *("que", "qual", "quais", "quantos", "quantas", "como", "dados"),
    }
)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def _termos(texto: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _normalizar(texto)) if t not in _VAZIAS]


def _contem(palavras: list[str], termo: str) -> bool:
    """Casa pelo começo da palavra: "mulher" acha "mulheres", mas "contra"
    não acha "contratações" por estar no meio de outra palavra qualquer."""
    return any(p.startswith(termo) for p in palavras)


@dataclass(frozen=True)
class Indicacao:
    """Um tema que casou com a busca, com a comissão a que pertence."""

    comissao: Comissao
    tema: Tema
    acertos: int


class ServicoTemas:
    def __init__(self, arquivo: Path) -> None:
        self._arquivo = arquivo
        self._mapa: MapaTemas | None = None

    # ─── Carga ────────────────────────────────────────────────────────
    def carregar(self) -> None:
        rotulo = f"temas/{self._arquivo.name}"
        try:
            bruto = yaml.safe_load(self._arquivo.read_text(encoding="utf-8"))
        except OSError as e:
            raise CatalogoInvalido(f"{rotulo}: não foi possível abrir o arquivo. {e}") from e
        except yaml.YAMLError as e:
            raise CatalogoInvalido(f"{rotulo}: o YAML não pôde ser lido. {e}") from e

        try:
            self._mapa = MapaTemas.model_validate(bruto)
        except ValidationError as e:
            linhas = [
                f"    campo `{'.'.join(str(p) for p in err['loc'])}`: {err['msg']}"
                for err in e.errors()
            ]
            raise CatalogoInvalido(
                f"{rotulo}: o mapa de temas tem campos inválidos.",
                detalhe="\n".join(linhas),
            ) from e

        log.info(
            "temas_carregados",
            comissoes=len(self._mapa.comissoes),
            temas=sum(len(c.temas) for c in self._mapa.comissoes),
        )

    @property
    def mapa(self) -> MapaTemas:
        if self._mapa is None:
            self.carregar()
        assert self._mapa is not None
        return self._mapa

    # ─── Consulta ─────────────────────────────────────────────────────
    def comissao(self, sigla: str) -> Comissao | None:
        sigla = sigla.upper()
        return next((c for c in self.mapa.comissoes if c.sigla == sigla), None)

    def onde_procurar(self, assunto: str, sigla: str | None = None) -> list[Indicacao]:
        """Temas que casam com os termos do assunto, do mais ao menos aderente.

        Termo no nome do tema ou de um conjunto vale 2; no nome da comissão,
        1. Assim "violência contra a mulher" põe "Violência doméstica e sexual"
        — tema de violência, comissão da Mulher — à frente de um tema que só
        fala de violência. Tema que casa apenas pelo nome da comissão não
        entra: seria a comissão inteira, e isso não ajuda a escolher a fonte.
        """
        termos = _termos(assunto)
        if not termos:
            return []

        comissoes = self.mapa.comissoes
        if sigla:
            comissoes = [c for c in comissoes if c.sigla == sigla.upper()]

        achados: list[Indicacao] = []
        for c in comissoes:
            da_comissao = _termos(c.nome)
            for t in c.temas:
                do_tema = _termos(" ".join([t.nome, *(cj.nome for cj in t.conjuntos)]))
                no_tema = sum(2 for termo in termos if _contem(do_tema, termo))
                if not no_tema:
                    continue
                na_comissao = sum(1 for termo in termos if _contem(da_comissao, termo))
                achados.append(Indicacao(comissao=c, tema=t, acertos=no_tema + na_comissao))

        return sorted(achados, key=lambda i: -i.acertos)


# ─── Importação da planilha ───────────────────────────────────────────────

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def ler_planilha(caminho: Path) -> list[dict[str, str]]:
    """Linhas da primeira aba como `{coluna: texto}`, com A1 como cabeçalho."""
    with zipfile.ZipFile(caminho) as z:
        compartilhados: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in raiz.findall("m:si", _NS):
                compartilhados.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))

        livro = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        alvos = {r.get("Id"): r.get("Target", "") for r in rels}
        primeira = livro.find("m:sheets", _NS)[0]  # type: ignore[index]
        alvo = alvos[primeira.get(f"{{{_NS['r']}}}id")].lstrip("/").removeprefix("xl/")
        aba = ET.fromstring(z.read(f"xl/{alvo}"))

    linhas: list[dict[str, str]] = []
    for row in aba.iter(f"{{{_NS['m']}}}row"):
        celulas: dict[str, str] = {}
        for c in row.findall("m:c", _NS):
            coluna = re.sub(r"\d", "", c.get("r", ""))
            v = c.find("m:v", _NS)
            if c.get("t") == "s" and v is not None and v.text is not None:
                texto = compartilhados[int(v.text)]
            elif c.get("t") == "inlineStr":
                texto = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            else:
                texto = v.text if v is not None and v.text else ""
            if texto.strip():
                celulas[coluna] = texto.strip()
        if celulas:
            linhas.append(celulas)
    return linhas


def montar_mapa(linhas: list[dict[str, str]]) -> MapaTemas:
    """Agrupa as linhas da planilha em comissão → tema → conjuntos.

    A comissão vem como "Nome por extenso - SIGLA". Qualquer texto numa coluna
    além da D vira `nota` do tema — é onde a equipe deixa lembretes.
    """
    if not linhas:
        raise CatalogoInvalido("A planilha está vazia.")
    cabecalho = tuple(linhas[0].get(col, "") for col in "ABCD")
    if cabecalho != CABECALHO:
        raise CatalogoInvalido(
            "A primeira linha da planilha não é o cabeçalho esperado.",
            detalhe=f"  esperado: {' | '.join(CABECALHO)}\n  veio:     {' | '.join(cabecalho)}",
        )

    comissoes: dict[str, Comissao] = {}
    problemas: list[str] = []

    for numero, linha in enumerate(linhas[1:], start=2):
        bruto_comissao = linha.get("A", "")
        nome_tema = linha.get("B", "")
        if not bruto_comissao or not nome_tema:
            problemas.append(f"  • linha {numero}: falta a comissão ou o tema.")
            continue

        nome, _, sigla = bruto_comissao.rpartition(" - ")
        if not nome or not sigla:
            problemas.append(
                f"  • linha {numero}: a comissão precisa ser `Nome - SIGLA`, "
                f"e veio `{bruto_comissao}`."
            )
            continue

        comissao = comissoes.setdefault(
            sigla, Comissao(sigla=sigla.strip(), nome=nome.strip(), temas=[])
        )
        tema = next((t for t in comissao.temas if t.nome == nome_tema), None)
        if tema is None:
            tema = Tema(nome=nome_tema)
            comissao.temas.append(tema)

        extras = [v for col, v in sorted(linha.items()) if col not in ("A", "B", "C", "D")]
        if extras:
            tema.nota = "; ".join(filter(None, [tema.nota, *extras]))

        nome_conjunto, url = linha.get("C", ""), linha.get("D", "")
        if bool(nome_conjunto) != bool(url):
            problemas.append(f"  • linha {numero}: conjunto e link precisam vir juntos.")
            continue
        if nome_conjunto:
            try:
                tema.conjuntos.append(ConjuntoDados(nome=nome_conjunto, url=url))
            except ValidationError as e:
                problemas.append(f"  • linha {numero}: {e.errors()[0]['msg']}")

    if problemas:
        raise CatalogoInvalido(
            "A planilha tem linhas que não puderam ser importadas.",
            detalhe="\n".join(problemas),
        )
    return MapaTemas(comissoes=list(comissoes.values()))


_AVISO = """\
# GERADO A PARTIR DA PLANILHA — não edite à mão.
#
# Fonte:      dados/temas_comissoes_alepe.xlsx
# Atualizar:  .venv/Scripts/python -m app.cli importar-temas
#
# Diz, para cada tema de cada comissão, em quais conjuntos de dados da Base dos
# Dados procurar. Tema com `conjuntos: []` ainda não tem fonte mapeada.

"""


def escrever_yaml(mapa: MapaTemas, destino: Path) -> None:
    conteudo = yaml.safe_dump(
        mapa.model_dump(exclude_none=True),
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(_AVISO + conteudo, encoding="utf-8")
