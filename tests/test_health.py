"""Ordem de montagem do `main` e sinal de vida.

É o único ponto do esqueleto onde dá para errar de um jeito silencioso: uma
rota da API engolida pelo catch-all devolveria HTML com status 200, e o front
quebraria no `JSON.parse` sem dizer por quê.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import _resolver_dentro, app

cliente = TestClient(app)


def test_health_responde_ok():
    r = cliente.get("/api/v1/health")
    assert r.status_code == 200

    corpo = r.json()
    assert corpo["status"] == "ok"
    assert corpo["versao"]
    # Os cinco gabaritos do repositório são rascunhos: contam como pendentes,
    # não como tabelas disponíveis.
    assert corpo["tabelas_carregadas"] >= 0
    assert corpo["tabelas_rascunho"] >= 5


def test_rota_api_inexistente_devolve_json_e_nao_o_index():
    r = cliente.get("/api/v1/nao-existe")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["erro"]["codigo"] == "nao_encontrado"


def test_rota_desconhecida_do_front_cai_no_index():
    # Roteamento no cliente: um F5 em /painel precisa devolver o index.
    r = cliente.get("/painel")
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert r.headers["content-type"].startswith("text/html")


def test_travessia_de_diretorio_nao_vaza_arquivo(tmp_path: Path):
    # A guarda de verdade é `_resolver_dentro`; testá-la por HTTP é frágil
    # porque o cliente normaliza `../` antes de a requisição sair.
    base = tmp_path / "static"
    (base / "assets").mkdir(parents=True)
    (base / "index.html").write_text("ok", encoding="utf-8")
    (tmp_path / "segredo.txt").write_text("nao deveria sair daqui", encoding="utf-8")

    assert _resolver_dentro(base, "index.html") is not None
    assert _resolver_dentro(base, "assets") is not None

    # Tudo que escapa da base precisa ser recusado.
    for tentativa in ("../segredo.txt", "../../segredo.txt", "assets/../../segredo.txt"):
        assert _resolver_dentro(base, tentativa) is None, tentativa


def test_travessia_codificada_na_url_nao_vaza_arquivo():
    # `%2e%2e%2f` chega ao servidor sem ser normalizado pelo cliente.
    r = cliente.get("/%2e%2e%2fpyproject.toml")
    assert "[project]" not in r.text
    assert "requires-python" not in r.text
