"""Tabelas auxiliares — diretórios que o SQL pode unir, mas nunca escolher.

E a garantia de que toda consulta de exemplo do repositório só cita tabelas
que o validador da etapa 4 vai aceitar: do catálogo ou auxiliares.
"""

import re

import pytest

from app.core.config import obter_config
from app.domain.errors import CatalogoInvalido
from app.services.catalog_service import ARQUIVO_AUXILIARES, ServicoCatalogo
from tests.conftest import TABELA_VALIDA

CAMINHO = "educacao/br_teste_dataset__tabela.yaml"

AUXILIAR_VALIDA = """\
auxiliares:
  - id: br_bd_diretorios_brasil__municipio
    dataset_id: br_bd_diretorios_brasil
    table_id: municipio
    descricao: Diretório de municípios.
    como_unir: JOIN por id_municipio.
    colunas:
      - nome: id_municipio
        tipo: STRING
        descricao: Código IBGE.
"""


def test_auxiliar_entra_na_whitelist_e_fica_fora_do_indice(catalogo_temp):
    catalogo = catalogo_temp({CAMINHO: TABELA_VALIDA, ARQUIVO_AUXILIARES: AUXILIAR_VALIDA})

    assert catalogo.whitelist() == {
        "basedosdados.br_teste_dataset.tabela",
        "basedosdados.br_bd_diretorios_brasil.municipio",
    }
    assert [t.id for t in catalogo.indice()] == ["br_teste_dataset__tabela"]
    assert [a.id for a in catalogo.auxiliares()] == ["br_bd_diretorios_brasil__municipio"]


def test_sem_arquivo_de_auxiliares_tambem_funciona(catalogo_temp):
    catalogo = catalogo_temp({CAMINHO: TABELA_VALIDA})
    assert catalogo.auxiliares() == []


def test_auxiliar_invalida_aponta_o_arquivo(catalogo_temp):
    sem_colunas = AUXILIAR_VALIDA.split("    colunas:")[0] + "    colunas: []\n"
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: TABELA_VALIDA, ARQUIVO_AUXILIARES: sem_colunas})
    assert ARQUIVO_AUXILIARES in (e.value.detalhe or "")


def test_id_da_auxiliar_precisa_bater_com_dataset_e_tabela(catalogo_temp):
    errado = AUXILIAR_VALIDA.replace("id: br_bd_diretorios_brasil__municipio", "id: municipios")
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: TABELA_VALIDA, ARQUIVO_AUXILIARES: errado})
    assert "br_bd_diretorios_brasil__municipio" in (e.value.detalhe or "")


# ─── O catálogo do repositório ────────────────────────────────────────────

_REFERENCIA = re.compile(r"`(basedosdados\.[\w]+\.[\w]+)`")


def test_consultas_de_exemplo_so_citam_tabelas_permitidas():
    """Um nome de tabela digitado errado num exemplo ensinaria o modelo a
    gerar SQL que o validador rejeita. Rascunhos contam: vão virar ativos."""
    catalogo = ServicoCatalogo(obter_config().dir_catalogo)
    catalogo.carregar()
    permitidas = {t.referencia_bigquery for t in catalogo.todas(incluir_rascunhos=True)}
    permitidas |= {a.referencia_bigquery for a in catalogo.auxiliares()}

    fora = {
        f"{t.id}: {ref}"
        for t in catalogo.todas(incluir_rascunhos=True)
        for c in t.consultas_exemplo
        for ref in _REFERENCIA.findall(c.sql)
        if ref not in permitidas
    }
    assert not fora, "tabelas fora do catálogo e das auxiliares:\n" + "\n".join(sorted(fora))
