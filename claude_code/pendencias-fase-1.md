# Fase 1 — o que falta para fechar o catálogo

Revisão de 13/10/2026, feita sobre o commit `24bb79e`. As 9 tabelas estão
revisadas: resumos, grãos, partições, colunas com códigos explicados e
consultas de exemplo. O catálogo é válido e os testes passam. Todas seguem
como `rascunho`.

## Já resolvido

- [x] Partições conferidas na API de metadados da Base dos Dados.
- [x] Ids e nomes de arquivo no padrão `dataset__tabela`.
- [x] Tabelas de indicadores renomeadas, sem prometer a nota do Ideb.
- [x] Instruções de "API do IBGE" trocadas por JOIN com a tabela de
      diretórios.
- [x] Resumos das 3 tabelas do CAGED diferenciados.
- [x] Colunas enxugadas (a Escola passou de 455 para 38).
- [x] Planilha `escolas_2024.xlsx` fora do catálogo e do repositório.

## Passo a passo

### 1. Tabelas de diretórios

Nove consultas de exemplo usam duas tabelas que não estão no catálogo:
`br_bd_diretorios_brasil.municipio` (nome do município) e
`br_bd_diretorios_brasil.cid_10` (nome da causa de morte). O validador da
Fase 2 só aceita tabelas do catálogo, então essas consultas seriam
rejeitadas.

- [x] 1.1 Decidido em 14/10: lista curta de "tabelas auxiliares" que o
      validador aceita em JOIN, em `src/app/catalog/_auxiliares.yaml`.
- [x] 1.2 Aplicado: o catálogo carrega as auxiliares, elas entram na
      whitelist e ficam fora do índice. Um teste confere que toda consulta
      de exemplo só cita tabelas do catálogo ou auxiliares.

### 2. Filtro de partição na tabela de excluídas do CAGED

Nas consultas que somam as três tabelas, o trecho da
`microdados_movimentacao_excluida` filtra `ano` e `sigla_uf`, mas não `mes`,
que também é partição dela. O validador vai rejeitar.

- [ ] 2.1 Acrescentar o filtro de `mes` no trecho das excluídas (6
      consultas, nos 3 arquivos do CAGED).

### 3. Perguntas de exemplo das tabelas complementares do CAGED

As tabelas de excluídas e de fora do prazo repetem as 3 perguntas da tabela
principal, inclusive a de salário, que elas não respondem.

- [ ] 3.1 Deixar nelas só a pergunta de saldo, que precisa das três tabelas.

### 4. Conferir os valores com dados reais

Os códigos usados nos filtros (`rede = '3'`, `tipo_unidade = '73'`,
`rede = 'publica'`, etc.) vieram dos dicionários da Base dos Dados, mas
nenhuma consulta de exemplo foi rodada de verdade. Esta máquina não tem
credenciais do Google Cloud.

- [ ] 4.1 Instalar o Google Cloud CLI e fazer `gcloud auth
      application-default login` com a conta do projeto
      `consultas-consuleg`.
- [ ] 4.2 Rodar cada consulta de exemplo (são 27, e cada uma custa
      centavos), conferir se o resultado faz sentido e corrigir o que não
      fizer.

### 5. Ativar

- [ ] 5.1 Trocar para `status: ativo`, uma tabela por vez, e passar no
      `make validar-catalogo`.
- [ ] 5.2 Atualizar o README: estado da Fase 1, desvios do plano e a
      decisão do passo 1.
