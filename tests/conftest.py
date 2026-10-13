"""Utilidades compartilhadas dos testes."""

from pathlib import Path

import pytest

from app.services.catalog_service import ServicoCatalogo

_CABECALHO = """\
id: br_teste_dataset__tabela
dataset_id: br_teste_dataset
table_id: tabela
nome_exibicao: Tabela de teste
area: educacao
fonte: Órgão de teste
status: ativo
"""

# Isolado do resto porque vários testes precisam trocar o bloco inteiro —
# o resumo é a única coisa que o modelo lê ao escolher a tabela, e tem regra
# própria de tamanho mínimo.
RESUMO_VALIDO = """\
resumo: >
  Tabela usada apenas nos testes automatizados desta aplicação, com colunas
  suficientes para exercitar a validação de partições, tipos e coerência
  entre os campos declarados no cadastro.
"""

_CORPO = """\
palavras_chave: [teste]
perguntas_exemplo:
  - Uma pergunta qualquer?
grao: Uma linha por registro de teste.
cobertura_temporal: { inicio: 2010, fim: 2023 }
cobertura_geografica: nacional
particoes: [ano]
colunas:
  - nome: ano
    tipo: INT64
    descricao: Ano de referência.
    particao: true
  - nome: sigla_uf
    tipo: STRING
    descricao: Unidade da federação.
    valores_exemplo: [PE, AL]
consultas_exemplo:
  - pergunta: Quantos registros por ano?
    sql: |
      SELECT ano, COUNT(*) AS total
      FROM `basedosdados.br_teste_dataset.tabela`
      WHERE ano = 2023
      GROUP BY ano
"""

# Cadastro mínimo e válido, com `status: ativo`. Os testes partem daqui e
# quebram um campo por vez — assim cada falha isola exatamente uma regra.
TABELA_VALIDA = _CABECALHO + RESUMO_VALIDO + _CORPO


@pytest.fixture
def catalogo_temp(tmp_path: Path):
    """Devolve uma função que monta um catálogo em disco e o carrega.

    Uso: `escrever({"educacao/x.yaml": conteudo})` → ServicoCatalogo carregado,
    ou a exceção de validação, para o teste inspecionar a mensagem.
    """
    raiz = tmp_path / "catalog"

    def escrever(arquivos: dict[str, str]) -> ServicoCatalogo:
        for caminho_rel, conteudo in arquivos.items():
            destino = raiz / caminho_rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(conteudo, encoding="utf-8")
        servico = ServicoCatalogo(raiz)
        servico.carregar()
        return servico

    return escrever
