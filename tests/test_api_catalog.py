"""Endpoints do catálogo, com um catálogo controlado no lugar do real.

O catálogo do repositório só tem gabaritos (rascunhos), então o índice real é
vazio. Aqui a dependência é substituída para exercitar as respostas de fato.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import obter_catalogo
from app.main import app
from tests.conftest import TABELA_VALIDA


@pytest.fixture
def cliente(catalogo_temp):
    catalogo = catalogo_temp({"educacao/br_teste_dataset__tabela.yaml": TABELA_VALIDA})
    app.dependency_overrides[obter_catalogo] = lambda: catalogo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_indice_traz_resumo_sem_colunas(cliente):
    r = cliente.get("/api/v1/catalog")
    assert r.status_code == 200

    corpo = r.json()
    assert corpo["total"] == 1
    assert corpo["areas"] == ["educacao"]

    tabela = corpo["tabelas"][0]
    assert tabela["id"] == "br_teste_dataset__tabela"
    assert tabela["cobertura_inicio"] == 2010
    assert tabela["total_colunas"] == 2
    # O índice é o que vai no prompt da etapa 2. Coluna ali dentro seria
    # prompt caro à toa.
    assert "colunas" not in tabela


def test_detalhe_traz_colunas_e_a_referencia_do_bigquery(cliente):
    r = cliente.get("/api/v1/catalog/br_teste_dataset__tabela")
    assert r.status_code == 200

    corpo = r.json()
    assert corpo["referencia_bigquery"] == "basedosdados.br_teste_dataset.tabela"
    assert corpo["particoes"] == ["ano"]
    assert [c["nome"] for c in corpo["colunas"]] == ["ano", "sigla_uf"]
    assert corpo["consultas_exemplo"][0]["pergunta"] == "Quantos registros por ano?"


def test_detalhe_de_tabela_inexistente(cliente):
    r = cliente.get("/api/v1/catalog/br_nao_existe__nada")
    assert r.status_code == 404
    assert r.json()["erro"]["codigo"] == "nao_encontrado"


def test_health_reflete_o_catalogo_injetado(cliente):
    corpo = cliente.get("/api/v1/health").json()
    assert corpo["tabelas_carregadas"] == 1
    assert corpo["tabelas_rascunho"] == 0
