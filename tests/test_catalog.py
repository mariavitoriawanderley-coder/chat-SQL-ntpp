"""Fase 1 — carga e validação do catálogo.

O catálogo é preenchido à mão, então o que se testa aqui é sobretudo a
QUALIDADE DA MENSAGEM DE ERRO: ela precisa dizer qual arquivo e qual campo.
Um erro genérico obriga quem está cadastrando a caçar o problema no olho.
"""

import pytest

from app.domain.errors import CatalogoInvalido, RecursoNaoEncontrado
from app.domain.table_meta import TableMeta
from tests.conftest import RESUMO_VALIDO, TABELA_VALIDA

CAMINHO = "educacao/br_teste_dataset__tabela.yaml"


def _com(troca: dict[str, str]) -> str:
    """Aplica substituições de texto sobre o cadastro válido."""
    conteudo = TABELA_VALIDA
    for de, para in troca.items():
        assert de in conteudo, f"trecho `{de}` não existe no cadastro de teste"
        conteudo = conteudo.replace(de, para)
    return conteudo


# ─── Caminho feliz ────────────────────────────────────────────────────────


def test_carrega_cadastro_valido(catalogo_temp):
    catalogo = catalogo_temp({CAMINHO: TABELA_VALIDA})

    assert len(catalogo.indice()) == 1
    tabela = catalogo.obter("br_teste_dataset__tabela")
    assert tabela.nome_exibicao == "Tabela de teste"
    assert tabela.particoes == ["ano"]
    assert tabela.coluna("ano") is not None
    assert tabela.coluna("inexistente") is None


def test_referencia_bigquery_e_whitelist(catalogo_temp):
    catalogo = catalogo_temp({CAMINHO: TABELA_VALIDA})

    # É desta string que sai a whitelist do validador de SQL da etapa 4.
    assert catalogo.obter("br_teste_dataset__tabela").referencia_bigquery == (
        "basedosdados.br_teste_dataset.tabela"
    )
    assert catalogo.whitelist() == {"basedosdados.br_teste_dataset.tabela"}


def test_tabela_inexistente_levanta_nao_encontrado(catalogo_temp):
    catalogo = catalogo_temp({CAMINHO: TABELA_VALIDA})

    with pytest.raises(RecursoNaoEncontrado) as e:
        catalogo.obter("br_nao_existe__nada")
    assert "br_nao_existe__nada" in e.value.mensagem


def test_arquivo_com_prefixo_underscore_e_ignorado(catalogo_temp):
    # `_schema.yaml` é documentação do formato, não cadastro.
    catalogo = catalogo_temp(
        {CAMINHO: TABELA_VALIDA, "_schema.yaml": "isto: nao e um cadastro valido"}
    )
    assert len(catalogo.indice()) == 1


# ─── Rascunho: existe, mas fica fora do índice ────────────────────────────


def test_rascunho_carrega_mas_nao_entra_no_indice(catalogo_temp):
    # O gabarito recém-criado tem TODO em tudo. Ele precisa poder existir no
    # repositório sem derrubar o serviço, e sem ser oferecido ao modelo.
    catalogo = catalogo_temp({CAMINHO: _com({"status: ativo": "status: rascunho"})})

    assert catalogo.indice() == []
    assert catalogo.whitelist() == set()
    assert len(catalogo.todas(incluir_rascunhos=True)) == 1


def test_rascunho_dispensa_o_rigor_do_cadastro_completo(catalogo_temp):
    catalogo = catalogo_temp(
        {
            CAMINHO: _com(
                {
                    "status: ativo": "status: rascunho",
                    "grao: Uma linha por registro de teste.": "grao: TODO",
                }
            )
        }
    )
    assert len(catalogo.todas(incluir_rascunhos=True)) == 1


def test_gabaritos_do_repositorio_sao_validos():
    """Guarda contra gabarito quebrado entrando no repositório.

    Se este teste falhar, `make validar-catalogo` diz exatamente onde.
    """
    from app.core.config import obter_config
    from app.services.catalog_service import ServicoCatalogo

    servico = ServicoCatalogo(obter_config().dir_catalogo)
    servico.carregar()
    assert len(servico.todas(incluir_rascunhos=True)) >= 5


# ─── Erros de estrutura ───────────────────────────────────────────────────


def test_yaml_malformado_aponta_o_arquivo_e_a_linha(catalogo_temp):
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: "id: x\n  indentacao: errada\n:\n"})

    detalhe = e.value.detalhe or ""
    assert "br_teste_dataset__tabela.yaml" in detalhe
    assert "Linha" in detalhe


def test_arquivo_vazio_e_recusado(catalogo_temp):
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: "\n"})
    assert "vazio" in (e.value.detalhe or "")


def test_campo_obrigatorio_ausente_aponta_o_campo(catalogo_temp):
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: _com({"grao: Uma linha por registro de teste.\n": ""})})

    detalhe = e.value.detalhe or ""
    assert "`grao`" in detalhe
    assert "br_teste_dataset__tabela.yaml" in detalhe


def test_campo_desconhecido_e_recusado(catalogo_temp):
    # Erro de digitação num nome de campo passaria despercebido se o modelo
    # aceitasse extras — o valor cadastrado simplesmente não teria efeito.
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: TABELA_VALIDA + "\nplavras_chave: [erro de digitacao]\n"})
    assert "plavras_chave" in (e.value.detalhe or "")


def test_tipo_de_coluna_invalido_aponta_o_indice_da_coluna(catalogo_temp):
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: _com({"tipo: STRING": "tipo: VARCHAR"})})

    detalhe = e.value.detalhe or ""
    assert "colunas[1].tipo" in detalhe


# ─── Convenções de nome e de pasta ────────────────────────────────────────


def test_nome_do_arquivo_precisa_bater_com_o_id(catalogo_temp):
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({"educacao/outro_nome.yaml": TABELA_VALIDA})

    detalhe = e.value.detalhe or ""
    assert "outro_nome" in detalhe
    assert "br_teste_dataset__tabela" in detalhe


def test_id_precisa_ser_dataset_mais_tabela(catalogo_temp):
    conteudo = _com({"id: br_teste_dataset__tabela\n": "id: apelido_qualquer\n"})
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({"educacao/apelido_qualquer.yaml": conteudo})

    assert "br_teste_dataset__tabela" in (e.value.detalhe or "")


def test_pasta_precisa_bater_com_a_area(catalogo_temp):
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({"saude/br_teste_dataset__tabela.yaml": TABELA_VALIDA})

    detalhe = e.value.detalhe or ""
    assert "saude" in detalhe
    assert "educacao" in detalhe


def test_id_duplicado_em_dois_arquivos(catalogo_temp):
    # Mesmo id em áreas diferentes: o segundo sobrescreveria o primeiro em
    # silêncio se não houvesse esta checagem.
    outro = _com({"area: educacao": "area: saude"})
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp(
            {CAMINHO: TABELA_VALIDA, "saude/br_teste_dataset__tabela.yaml": outro}
        )
    assert "já está em uso" in (e.value.detalhe or "")


# ─── Coerência interna do cadastro ────────────────────────────────────────


def test_particao_declarada_que_nao_existe_entre_as_colunas(catalogo_temp):
    # É o erro mais caro do cadastro: o validador da etapa 4 passaria a exigir
    # um filtro por coluna inexistente e nenhuma consulta seria aprovada.
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: _com({"particoes: [ano]": "particoes: [ano, mes]"})})
    assert "mes" in (e.value.detalhe or "")


def test_coluna_marcada_como_particao_fora_da_lista(catalogo_temp):
    conteudo = _com(
        {
            "    descricao: Unidade da federação.\n": (
                "    descricao: Unidade da federação.\n    particao: true\n"
            )
        }
    )
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: conteudo})
    assert "sigla_uf" in (e.value.detalhe or "")


def test_colunas_repetidas(catalogo_temp):
    conteudo = _com(
        {
            "consultas_exemplo:": (
                "  - nome: ano\n"
                "    tipo: INT64\n"
                "    descricao: Duplicada por engano.\n"
                "    particao: true\n"
                "consultas_exemplo:"
            )
        }
    )
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: conteudo})
    assert "repetidas" in (e.value.detalhe or "")


def test_cobertura_temporal_invertida(catalogo_temp):
    invertida = _com({"{ inicio: 2010, fim: 2023 }": "{ inicio: 2023, fim: 2010 }"})
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: invertida})
    assert "posterior" in (e.value.detalhe or "")


# ─── Rigor exigido de tabela ativa ────────────────────────────────────────


def test_ativa_com_resumo_curto_demais(catalogo_temp):
    # O resumo é o único texto que o modelo lê ao escolher a tabela. Curto
    # demais e a escolha vira sorteio.
    conteudo = _com({RESUMO_VALIDO: "resumo: Dados de teste.\n"})
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: conteudo})
    assert "20 palavras" in (e.value.detalhe or "")


def test_ativa_com_campo_ainda_em_todo(catalogo_temp):
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: _com({"grao: Uma linha por registro de teste.": "grao: TODO"})})
    assert "grao" in (e.value.detalhe or "")


def test_ativa_sem_particao_precisa_reconhecer_o_custo(catalogo_temp):
    conteudo = _com({"particoes: [ano]": "particoes: []", "    particao: true\n": ""})
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: conteudo})
    assert "sem_particao" in (e.value.detalhe or "")


def test_ativa_sem_particao_e_aceita_quando_declarado(catalogo_temp):
    conteudo = _com(
        {
            "particoes: [ano]": "particoes: []\nsem_particao: true",
            "    particao: true\n": "",
        }
    )
    catalogo = catalogo_temp({CAMINHO: conteudo})
    assert len(catalogo.indice()) == 1


# ─── Vários problemas de uma vez ──────────────────────────────────────────


def test_acumula_erros_de_arquivos_diferentes(catalogo_temp):
    # Quem cadastra cinco tabelas quer ver os cinco problemas numa execução,
    # não descobrir um por vez.
    segundo = _com(
        {
            "id: br_teste_dataset__tabela": "id: br_outro__tabela",
            "dataset_id: br_teste_dataset": "dataset_id: br_outro",
            "area: educacao": "area: saude",
            "tipo: INT64": "tipo: INTEIRO",
        }
    )
    with pytest.raises(CatalogoInvalido) as e:
        catalogo_temp({CAMINHO: "conteudo: [invalido", "saude/br_outro__tabela.yaml": segundo})

    detalhe = e.value.detalhe or ""
    assert "br_teste_dataset__tabela.yaml" in detalhe
    assert "br_outro__tabela.yaml" in detalhe


def test_pasta_do_catalogo_inexistente(tmp_path):
    from app.services.catalog_service import ServicoCatalogo

    with pytest.raises(CatalogoInvalido) as e:
        ServicoCatalogo(tmp_path / "nao_existe").carregar()
    assert "não existe" in e.value.mensagem


# ─── Modelo de domínio, sem passar por arquivo ────────────────────────────


def test_valores_exemplo_numericos_viram_texto():
    # No YAML, `valores_exemplo: [2020, 2021]` chega como int. Como o valor só
    # serve de amostra no prompt, converter evita erro de tipo no cadastro.
    tabela = TableMeta.model_validate(
        {
            "id": "br_x__y",
            "dataset_id": "br_x",
            "table_id": "y",
            "nome_exibicao": "X",
            "area": "economia",
            "fonte": "Fonte",
            "resumo": "curto",
            "grao": "linha",
            "colunas": [
                {"nome": "ano", "tipo": "INT64", "descricao": "d", "valores_exemplo": [2020, 2021]}
            ],
        }
    )
    assert tabela.colunas[0].valores_exemplo == ["2020", "2021"]
