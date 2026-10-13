"""Mapa de temas das comissões — importação da planilha e busca.

A planilha é mantida à mão no Excel, então, como no catálogo, o que mais
importa é a mensagem de erro apontar a LINHA da planilha com problema.
"""

import zipfile
from pathlib import Path

import pytest

from app.core.config import obter_config
from app.domain.errors import CatalogoInvalido
from app.services.temas_service import (
    CABECALHO,
    ServicoTemas,
    escrever_yaml,
    ler_planilha,
    montar_mapa,
)

URL = "https://basedosdados.org/dataset/f51134c2-5ab9-4bbc-882f-f1034603147a"
URL_2 = "https://basedosdados.org/dataset/9fa532fb-5681-4903-b99d-01dc45fd527a"

CABECA = dict(zip("ABCD", CABECALHO, strict=True))


def _linhas(*corpo: dict[str, str]) -> list[dict[str, str]]:
    return [CABECA, *corpo]


MULHER = "Defesa dos Direitos da Mulher - CDDM"
PCD = "Defesa da Pessoa com Deficiência e Atipicidades - CDPDA"


# ─── Importação ───────────────────────────────────────────────────────────


def test_agrupa_comissao_tema_e_conjuntos():
    mapa = montar_mapa(
        _linhas(
            {"A": MULHER, "B": "Violência doméstica e sexual", "C": "SINAN", "D": URL},
            {"A": MULHER, "B": "Mulheres no trabalho e renda", "C": "PNAD", "D": URL_2},
            {"A": MULHER, "B": "Mulheres no trabalho e renda", "C": "SINAN", "D": URL},
            {"A": MULHER, "B": "Cuidado e uso do tempo"},
        )
    )

    [cddm] = mapa.comissoes
    assert (cddm.sigla, cddm.nome) == ("CDDM", "Defesa dos Direitos da Mulher")
    assert [t.nome for t in cddm.temas] == [
        "Violência doméstica e sexual",
        "Mulheres no trabalho e renda",
        "Cuidado e uso do tempo",
    ]
    assert len(cddm.temas[1].conjuntos) == 2
    assert cddm.temas[0].conjuntos[0].dataset_uuid == URL.rsplit("/", 1)[1]
    assert cddm.temas[2].sem_fonte


def test_coluna_extra_vira_nota_do_tema():
    mapa = montar_mapa(_linhas({"A": MULHER, "B": "Tema", "C": "X", "D": URL, "E": "SP???"}))
    assert mapa.comissoes[0].temas[0].nota == "SP???"


def test_cabecalho_errado_e_recusado():
    with pytest.raises(CatalogoInvalido, match="cabeçalho"):
        montar_mapa([{"A": "Comissão", "B": "Assunto"}])


@pytest.mark.parametrize(
    ("linha", "trecho"),
    [
        ({"A": "Comissão sem sigla", "B": "Tema"}, "Nome - SIGLA"),
        ({"A": MULHER, "B": "Tema", "C": "Só o nome"}, "precisam vir juntos"),
        ({"A": MULHER, "B": "Tema", "C": "X", "D": "https://exemplo.com"}, "basedosdados.org"),
        ({"A": MULHER}, "falta a comissão ou o tema"),
    ],
)
def test_erro_aponta_a_linha_da_planilha(linha, trecho):
    with pytest.raises(CatalogoInvalido) as erro:
        montar_mapa(_linhas({"A": MULHER, "B": "Tema bom"}, linha))
    assert "linha 3" in (erro.value.detalhe or "")
    assert trecho in (erro.value.detalhe or "")


def test_le_xlsx_com_texto_compartilhado_e_em_linha(tmp_path: Path):
    """Planilha mínima montada à mão — o mesmo formato que o Excel grava."""
    caminho = tmp_path / "p.xlsx"
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    ns_r = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook {ns} {ns_r}><sheets><sheet name="A" sheetId="1" r:id="rId1"/>'
            "</sheets></workbook>",
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}><si><t>Comissão</t></si></sst>")
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f"<worksheet {ns}><sheetData>"
            '<row r="1"><c r="A1" t="s"><v>0</v></c>'
            '<c r="B1" t="inlineStr"><is><t>Tema</t></is></c></row>'
            '<row r="2"><c r="B2"><v>42</v></c></row>'
            "</sheetData></worksheet>",
        )

    assert ler_planilha(caminho) == [{"A": "Comissão", "B": "Tema"}, {"B": "42"}]


# ─── Busca ────────────────────────────────────────────────────────────────


@pytest.fixture
def servico(tmp_path: Path) -> ServicoTemas:
    mapa = montar_mapa(
        _linhas(
            {"A": MULHER, "B": "Violência doméstica e sexual", "C": "SINAN", "D": URL},
            {"A": MULHER, "B": "Rede de atendimento"},
            {"A": PCD, "B": "Violência contra a pessoa com deficiência", "C": "SINAN", "D": URL},
            {"A": PCD, "B": "Trabalho e cota de contratação", "C": "RAIS", "D": URL_2},
        )
    )
    arquivo = tmp_path / "comissoes.yaml"
    escrever_yaml(mapa, arquivo)
    return ServicoTemas(arquivo)


def test_busca_ignora_acento_e_caixa(servico):
    nomes = [i.tema.nome for i in servico.onde_procurar("VIOLENCIA")]
    assert "Violência doméstica e sexual" in nomes


def test_nome_da_comissao_desempata(servico):
    primeiro = servico.onde_procurar("violência contra a mulher")[0]
    assert primeiro.comissao.sigla == "CDDM"


def test_preposicao_nao_casa_no_meio_de_outra_palavra(servico):
    nomes = [i.tema.nome for i in servico.onde_procurar("contra")]
    assert nomes == []


def test_tema_so_casa_pela_comissao_fica_de_fora(servico):
    nomes = [i.tema.nome for i in servico.onde_procurar("mulher")]
    assert "Rede de atendimento" not in nomes


def test_filtra_por_comissao(servico):
    achados = servico.onde_procurar("violência", sigla="cdpda")
    assert {i.comissao.sigla for i in achados} == {"CDPDA"}


# ─── O arquivo do repositório ─────────────────────────────────────────────


def test_mapa_do_repositorio_carrega():
    servico = ServicoTemas(obter_config().arquivo_temas)
    servico.carregar()
    assert servico.comissao("CSAS") is not None
    assert servico.onde_procurar("saneamento")
