# Plano de desenvolvimento — Aplicação de consulta a dados públicos brasileiros

> Documento de briefing para o Claude Code. Leia por inteiro antes de escrever qualquer código.
> Onde houver decisão já tomada, siga. Onde houver `[DECIDIR]`, pergunte ao desenvolvedor.

---

## 1. Objetivo da aplicação

Permitir que qualquer pessoa — sem saber SQL — obtenha dados públicos brasileiros nas áreas de **educação, saúde e economia** descrevendo em linguagem natural o que precisa, e transforme esses dados em um painel analítico próprio.

A aplicação faz três coisas:

1. **Traduz** uma pergunta em português para uma consulta SQL sobre o datalake público da [Base dos Dados](https://basedosdados.org/), hospedado no Google BigQuery.
2. **Explica e submete à aprovação** — mostra ao usuário o SQL gerado, uma explicação em linguagem leiga do que a consulta faz, e o custo estimado de execução. Nada roda sem confirmação.
3. **Entrega um painel** onde o usuário monta quantos gráficos quiser, filtra os dados e cria tabelas dinâmicas.

### Princípios não negociáveis

- **A aplicação não mantém banco de dados próprio.** Toda informação vem da Base dos Dados via BigQuery. O catálogo de tabelas é um conjunto de arquivos YAML versionados no repositório. O estado da conversa vive no navegador.
- **Transparência antes de execução.** O usuário sempre vê o SQL e entende o que ele faz antes de qualquer consulta ser executada. Isso é funcionalidade central, não etapa administrativa.
- **Custo é limite rígido.** O BigQuery cobra por bytes escaneados. Toda consulta passa por `dry run` e por um teto de bytes faturáveis antes de executar.
- **Serviço único.** Um container no Cloud Run serve a API e o front. Se no futuro houver outro cliente da API, cria-se um segundo serviço — não agora.

### Público

Jornalistas de dados, gestores públicos municipais, pesquisadores, estudantes de pós-graduação e servidores que precisam de evidência para relatórios. Pessoas alfabetizadas em dados, mas não em SQL.

---

## 2. Decisões de arquitetura

| Camada | Escolha | Motivo |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** | Ecossistema de dados, tipagem via Pydantic, ASGI para streaming |
| Frontend | **Vite + React 19 + TypeScript** | Ver nota abaixo |
| Estilo | **Tailwind CSS v4** | Tokens de design como variáveis CSS |
| Dados no navegador | **Arquero** | Filtro, group-by e pivot em memória, sem servidor |
| Gráficos | **Apache ECharts** | Composição em React, fácil de estilizar com os tokens do projeto |
| Parser SQL | **sqlglot** (dialeto `bigquery`) | Validação por árvore sintática, não por regex |
| LLM | **Gemini API** — `gemini-3.6-flash` (geração de SQL) e `gemini-3.5-flash-lite` (seleção de tabela) | Custo baixo, saída estruturada em JSON |
| Empacotamento | Dockerfile multi-stage | Node compila o front; a imagem final é só Python |
| Hospedagem | **Google Cloud Run**, região `southamerica-east1` | Identidade de service account nativa, escala a zero |
| Dependências Python | **uv** + `pyproject.toml` | Instalação rápida, lockfile determinístico |
| Lint/format | **ruff** (Python), **biome** (TS) | Ferramenta única por linguagem |

### Nota sobre Vite em vez de Next.js

O front é uma SPA autenticada por nada, sem SEO, sem renderização no servidor, servida como arquivos estáticos por trás do FastAPI. Nesse cenário o Next.js entraria apenas para ser exportado como estático (`output: 'export'`), o que desliga justamente os recursos que justificam usá-lo — Server Components com dados, Route Handlers, middleware, otimização de imagem.

Vite entrega o mesmo resultado com build mais rápido, imagem menor e menos configuração.

**Se o desenvolvedor preferir Next.js**, é uma escolha válida: use `output: 'export'`, `images.unoptimized = true`, sem middleware e sem Route Handlers — todas as chamadas de dados vão para `/api/*` do FastAPI. O restante deste plano permanece idêntico.

### Como um serviço único serve as duas coisas

O build do front gera arquivos estáticos que o FastAPI serve. Ordem de montagem no `main.py` **importa**:

1. Rotas da API sob o prefixo `/api` — declaradas primeiro.
2. Assets estáticos (`/assets`) via `StaticFiles`.
3. Catch-all que devolve `index.html` para qualquer outra rota, permitindo que o roteamento do lado do cliente funcione ao recarregar a página.

Em desenvolvimento, rode os dois separados (`vite dev` na 5173, `uvicorn --reload` na 8000) com proxy do Vite apontando `/api` para o backend. Só em produção eles se fundem.

---

## 3. Passos do processo

O caminho de uma pergunta até o painel, em sete etapas:

### Etapa 1 — Pergunta

O usuário escreve em linguagem natural. Exemplo: *"Quero comparar o número de matrículas no ensino fundamental em Alagoas e Pernambuco nos últimos dez anos."*

### Etapa 2 — Seleção de tabela (primeira chamada ao Gemini)

O modelo recebe **apenas o índice resumido** do catálogo: para cada tabela, o identificador, o nome de exibição, a área, o resumo em prosa, a cobertura temporal e as palavras-chave. **Nenhuma coluna é enviada nesta etapa.** O prompt fica pequeno e barato.

O modelo devolve as tabelas candidatas ordenadas por aderência, com justificativa. Se nenhuma tabela atender à pergunta, ele deve dizer isso explicitamente em vez de forçar a mais próxima.

Modelo: `gemini-3.5-flash-lite`. Saída estruturada:

```json
{
  "tabelas": [
    { "id": "br_inep_censo_escolar__matricula", "confianca": 0.92, "motivo": "Registra matrículas por escola, ano e UF." }
  ],
  "esclarecimento_necessario": null,
  "sem_cobertura": false
}
```

Quando `esclarecimento_necessario` vier preenchido, a aplicação faz a pergunta ao usuário no chat e não avança. Quando `sem_cobertura` for `true`, a aplicação informa que o catálogo atual não cobre o assunto e sugere as áreas disponíveis.

### Etapa 3 — Geração do SQL (segunda chamada ao Gemini)

Agora sim o prompt recebe o **detalhamento completo das colunas** — mas apenas das tabelas selecionadas na etapa anterior. Junto vão: o grão da tabela, as colunas de partição, valores de exemplo para colunas categóricas, observações de armadilha e as consultas de exemplo cadastradas.

Modelo: `gemini-3.6-flash`. Use **context caching** para o bloco de instruções fixas — ele se repete a cada mensagem e o cache reduz esse custo em cerca de 90%.

Saída estruturada (`QueryPlan`):

```json
{
  "sql": "SELECT ano, sigla_uf, SUM(quantidade_matricula) AS matriculas ...",
  "explicacao_leiga": "Esta consulta soma o total de matrículas registradas em cada ano, separando os resultados por estado, e considera apenas Alagoas e Pernambuco entre 2014 e 2023.",
  "explicacao_tecnica": "Agregação SUM com GROUP BY em ano e sigla_uf, filtrando as partições ano e sigla_uf.",
  "tabelas_usadas": ["br_inep_censo_escolar__matricula"],
  "colunas_saida": [
    { "nome": "ano", "tipo": "INT64", "descricao": "Ano do censo" },
    { "nome": "sigla_uf", "tipo": "STRING", "descricao": "Estado" },
    { "nome": "matriculas", "tipo": "INT64", "descricao": "Total de matrículas" }
  ],
  "grafico_sugerido": { "tipo": "linha", "x": "ano", "y": "matriculas", "serie": "sigla_uf" },
  "avisos": ["O Censo Escolar de 2020 foi afetado pela pandemia e pode não ser comparável."]
}
```

**Regra de escrita para `explicacao_leiga`:** frase corrida, sem jargão, sem citar nomes de coluna ou de função SQL. Descreve o que a consulta faz do ponto de vista de quem perguntou. Máximo cinco frases.

### Etapa 4 — Validação automática

Antes de qualquer contato com o BigQuery, o `sql_validator` faz o parse com sqlglot e rejeita a consulta se:

- não for uma única instrução `SELECT` (nada de DML, DDL, múltiplos statements ou ponto e vírgula extra);
- referenciar qualquer tabela fora da whitelist derivada do catálogo;
- não filtrar pelas colunas de partição declaradas para as tabelas usadas;
- não tiver `LIMIT` — o validador injeta `LIMIT 50000` quando ausente;
- contiver `SELECT *`.

Falha de validação **não** vai para o usuário como erro cru. A aplicação reenvia ao Gemini com a mensagem do validador para uma segunda tentativa (máximo duas). Se ainda falhar, informa que não conseguiu montar uma consulta segura e sugere reformular a pergunta.

### Etapa 5 — Estimativa de custo (`dry run`)

Job do BigQuery com `dry_run=True` retorna os bytes que seriam processados. A aplicação converte em custo estimado e compara com o teto configurado.

Se ultrapassar o teto, o botão de execução fica desabilitado e a aplicação explica o motivo, sugerindo reduzir o intervalo de anos ou o número de estados.

### Etapa 6 — Aprovação do usuário

O plano completo aparece no chat como um cartão: explicação leiga em destaque, SQL disponível para leitura, volume estimado, avisos. Duas ações: **Executar consulta** e **Ajustar** (que reabre o campo de texto com o contexto preservado para refinar).

Esta é a etapa central da aplicação. Ela recebe tratamento visual de destaque — ver seção 8.

### Etapa 7 — Execução e entrega ao painel

Job real com `maximum_bytes_billed` definido. O resultado volta como JSON e alimenta o painel. Cada execução bem-sucedida vira um **conjunto de dados** nomeado, que fica disponível na barra lateral do painel e pode alimentar múltiplos gráficos.

---

## 4. Estrutura de arquivos

```
.
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── .dockerignore
├── .env.example
├── README.md
├── Makefile                       # dev, build, deploy, test, lint
│
├── src/app/                       # backend
│   ├── main.py                    # app, CORS, routers, static mount
│   ├── core/
│   │   ├── config.py              # pydantic-settings
│   │   ├── logging.py             # structlog em JSON
│   │   └── exceptions.py          # handlers globais
│   ├── api/
│   │   ├── deps.py                # injeção de clientes e rate limit
│   │   └── v1/
│   │       ├── __init__.py        # agrega os routers
│   │       ├── chat.py            # POST /api/v1/chat/plan
│   │       ├── query.py           # POST /api/v1/query/execute
│   │       ├── catalog.py         # GET  /api/v1/catalog
│   │       └── health.py          # GET  /api/v1/health
│   ├── schemas/                   # contratos HTTP (Pydantic)
│   │   ├── chat.py
│   │   ├── query_plan.py
│   │   ├── chart.py
│   │   └── catalog.py
│   ├── domain/                    # entidades puras, sem I/O
│   │   ├── table_meta.py          # TableMeta, ColumnMeta
│   │   └── errors.py
│   ├── services/
│   │   ├── catalog_service.py     # carrega YAML, indexa, busca
│   │   ├── planner_service.py     # orquestra etapas 2 a 5
│   │   ├── llm/
│   │   │   ├── gemini_client.py
│   │   │   ├── prompt_builder.py
│   │   │   └── schemas.py         # response_schema do Gemini
│   │   ├── sql/
│   │   │   ├── validator.py       # sqlglot
│   │   │   └── policy.py          # whitelist, tetos, LIMIT
│   │   ├── bigquery_service.py    # dry run e execução
│   │   └── cache_service.py       # cache em memória com TTL
│   ├── prompts/
│   │   ├── 01_selecao_tabela.md
│   │   └── 02_geracao_sql.md
│   └── catalog/                   # ← CADASTRO DAS TABELAS (seção 5)
│       ├── _schema.yaml           # documentação do formato
│       └── educacao/, saude/, economia/
│
├── tests/
│   ├── test_validator.py          # prioridade máxima de cobertura
│   ├── test_catalog.py
│   ├── test_planner.py
│   └── fixtures/
│
└── web/                           # frontend
    ├── index.html
    ├── vite.config.ts
    ├── package.json
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── styles/tokens.css      # tokens da seção 8
        ├── lib/
        │   ├── api.ts             # cliente tipado
        │   ├── dataframe.ts       # wrapper do Arquero
        │   └── format.ts          # números e datas em pt-BR
        ├── stores/
        │   ├── chatStore.ts
        │   └── panelStore.ts      # datasets, gráficos, filtros, pivot
        ├── features/
        │   ├── chat/
        │   │   ├── ChatRail.tsx
        │   │   ├── MessageList.tsx
        │   │   └── QueryPlanCard.tsx   # elemento-assinatura
        │   └── panel/
        │       ├── Panel.tsx
        │       ├── DatasetList.tsx
        │       ├── FilterBar.tsx
        │       ├── ChartGrid.tsx
        │       ├── ChartBuilder.tsx
        │       ├── ChartCard.tsx
        │       ├── PivotBuilder.tsx
        │       └── PivotTable.tsx
        └── components/ui/          # botão, cartão, select, sheet
```

### Regra de dependência

`api` → `services` → `domain`. A camada `api` não importa o cliente do BigQuery nem o do Gemini. A camada `services` não conhece HTTP. A camada `domain` não importa nada do projeto. Isso permite testar validador e planejador sem subir servidor nem tocar na nuvem.

Não crie a pasta `models/`. Sem ORM, ela não tem função e vira depósito de código deslocado.

---

## 5. Cadastro das tabelas

Esta é a parte que o desenvolvedor preenche à mão. O formato precisa ser óbvio de editar.

**Um arquivo YAML por tabela**, dentro da pasta da área correspondente. O nome do arquivo é o identificador da tabela.

### Formato — `src/app/catalog/_schema.yaml`

Crie este arquivo como documentação viva do formato, com todos os campos comentados. Modelo:

```yaml
# ─── IDENTIFICAÇÃO ────────────────────────────────────────────
id: br_inep_censo_escolar__matricula      # identificador único interno
dataset_id: br_inep_censo_escolar          # dataset no BigQuery
table_id: matricula                        # tabela no BigQuery
nome_exibicao: Censo Escolar — Matrículas  # o que o usuário vê
area: educacao                             # educacao | saude | economia
fonte: INEP
url_documentacao: https://basedosdados.org/dataset/...

# ─── RESUMO (usado na ETAPA 2, seleção de tabela) ─────────────
# Escreva em prosa, 3 a 6 linhas. Descreva o que a tabela contém,
# quem produz, com que finalidade e que tipo de pergunta ela responde.
# Este texto é a única coisa que o modelo vê ao escolher a tabela —
# quanto mais específico, melhor a escolha.
resumo: >
  Registro de matrículas da educação básica brasileira, coletado
  anualmente pelo INEP. Cada linha representa uma matrícula individual,
  com informações sobre etapa de ensino, modalidade, dependência
  administrativa da escola e características do aluno. Responde
  perguntas sobre volume de matrículas, distribuição por rede
  pública e privada, e evolução do atendimento escolar por região.

palavras_chave: [matrícula, aluno, escola, ensino fundamental, ensino médio, rede pública]

perguntas_exemplo:
  - Quantas matrículas no ensino médio houve em Alagoas em 2023?
  - Como evoluiu a matrícula na rede privada no Nordeste?

# ─── CARACTERÍSTICAS DA TABELA ────────────────────────────────
grao: Uma linha por matrícula individual por ano.
cobertura_temporal: { inicio: 2007, fim: 2023 }
cobertura_geografica: nacional, com desagregação municipal
particoes: [ano, sigla_uf]      # SEMPRE filtrar por estas colunas
volume_aproximado: ~50 milhões de linhas por ano

observacoes: |
  O censo de 2020 foi afetado pela pandemia; comparações com anos
  anteriores exigem cautela. A partir de 2019 a variável de etapa
  de ensino mudou de codificação.

# ─── COLUNAS (usado na ETAPA 3, geração do SQL) ───────────────
colunas:
  - nome: ano
    tipo: INT64
    descricao: Ano de referência do censo.
    particao: true

  - nome: sigla_uf
    tipo: STRING
    descricao: Sigla da unidade da federação da escola.
    particao: true
    valores_exemplo: [AL, PE, SP, BA]

  - nome: id_municipio
    tipo: STRING
    descricao: Código IBGE de 7 dígitos do município da escola.

  - nome: etapa_ensino
    tipo: STRING
    descricao: Etapa de ensino em que o aluno está matriculado.
    valores_exemplo: [Ensino Fundamental, Ensino Médio, Educação Infantil]
    nota: A codificação mudou em 2019; ver observações da tabela.

  - nome: rede
    tipo: STRING
    descricao: Dependência administrativa da escola.
    valores_exemplo: [federal, estadual, municipal, privada]

# ─── CONSULTAS DE EXEMPLO ─────────────────────────────────────
# Poucas e boas. Servem de few-shot para o modelo e ensinam o
# padrão de filtro por partição.
consultas_exemplo:
  - pergunta: Total de matrículas no ensino médio por estado do Nordeste em 2023.
    sql: |
      SELECT sigla_uf, COUNT(*) AS matriculas
      FROM `basedosdados.br_inep_censo_escolar.matricula`
      WHERE ano = 2023
        AND sigla_uf IN ('AL','BA','CE','MA','PB','PE','PI','RN','SE')
        AND etapa_ensino = 'Ensino Médio'
      GROUP BY sigla_uf
      ORDER BY matriculas DESC
```

### Carregamento

O `catalog_service` lê todos os YAML no startup, valida cada um contra um modelo Pydantic (`TableMeta`) e monta duas estruturas em memória:

- **Índice resumido** — só identificação, resumo, palavras-chave, cobertura. É o que vai no prompt da etapa 2.
- **Detalhe completo** — indexado por `id`, recuperado sob demanda na etapa 3.

Um YAML malformado deve **falhar o startup com mensagem clara apontando arquivo e campo**, nunca ser ignorado silenciosamente. Adicione um comando `make validate-catalog` que roda essa validação isoladamente, para o desenvolvedor conferir enquanto cadastra.

Cadastre as cinco primeiras tabelas como arquivos vazios com todos os campos presentes e o valor `TODO`, para servirem de gabarito.

---

## 6. Contratos da API

```
GET  /api/v1/health              → status, versão, nº de tabelas carregadas
GET  /api/v1/catalog             → índice resumido (para a tela "o que posso perguntar")
GET  /api/v1/catalog/{id}        → detalhe de uma tabela

POST /api/v1/chat/plan
     body: { pergunta, historico[] }
     → QueryPlan + dry_run, OU pedido de esclarecimento, OU sem_cobertura

POST /api/v1/query/execute
     body: { plan_id }           # o plano fica em cache no servidor por 15 min
     → { colunas[], linhas[][], total_linhas, bytes_processados, truncado }
```

`/chat/plan` deve responder por **streaming** (SSE), emitindo eventos de progresso: `selecionando_tabela`, `gerando_sql`, `validando`, `estimando_custo`, `pronto`. A espera é de vários segundos e o usuário precisa ver o que está acontecendo.

O `plan_id` existe para que o front não devolva SQL ao servidor — o cliente nunca envia SQL, só o identificador de um plano que o próprio servidor gerou e validou.

### Variáveis de ambiente

```
GOOGLE_CLOUD_PROJECT=          # projeto de faturamento das consultas
GEMINI_API_KEY=                # via Secret Manager em produção
BQ_LOCATION=US                 # [DECIDIR] confirmar a região dos datasets da BD
BQ_MAX_BYTES_BILLED=5000000000 # 5 GB por consulta
BQ_MAX_ROWS=50000
PLAN_CACHE_TTL_SECONDS=900
RATE_LIMIT_PER_SESSION=20      # planos por hora
ALLOWED_ORIGINS=
LOG_LEVEL=INFO
```

---

## 7. Como funcionará o painel

O painel ocupa a área principal da tela e opera **inteiramente no navegador** sobre os dados já retornados. Nenhum filtro ou agregação feita ali gera nova consulta ao BigQuery.

### Conjuntos de dados

Cada execução bem-sucedida vira um conjunto de dados nomeado (nome derivado da pergunta original, editável). Ficam listados na lateral do painel com o número de linhas e a data de coleta. O usuário pode ter vários conjuntos ativos ao mesmo tempo e cada gráfico declara de qual conjunto se alimenta.

### Filtros

Barra de filtros por conjunto, derivada automaticamente dos tipos de coluna:

- **Categórica** → seleção múltipla com busca, mostrando os valores presentes e a contagem de cada um.
- **Numérica** → intervalo com campos de mínimo e máximo.
- **Temporal** → intervalo de anos ou datas.

Filtros são cumulativos e se aplicam a todos os gráficos e à tabela dinâmica que usem aquele conjunto. Um indicador permanente mostra quantas linhas restaram de quantas originais. Cada filtro ativo aparece como um marcador removível.

### Gráficos

Botão **Adicionar gráfico** abre o construtor:

| Campo | Opções |
|---|---|
| Conjunto de dados | qualquer conjunto ativo |
| Tipo | linha, barra, barra empilhada, área, dispersão, pizza, indicador numérico |
| Eixo X | qualquer coluna |
| Eixo Y | coluna numérica |
| Agregação | soma, média, contagem, mínimo, máximo, distintos |
| Série | coluna categórica opcional, gera múltiplas séries |
| Título | texto livre, com sugestão automática |

O primeiro gráfico é criado automaticamente a partir do campo `grafico_sugerido` do `QueryPlan` — o usuário chega ao painel com algo já visível, não com uma tela vazia.

Os gráficos ficam num grid responsivo, redimensionáveis entre meia e largura inteira, reordenáveis por arrastar. Cada cartão tem menu com duplicar, editar, exportar PNG e remover. Em telas estreitas, uma coluna só.

### Tabela dinâmica

Construtor com três áreas de destino para arrastar colunas: **linhas**, **colunas** e **valores** (com escolha de agregação). Renderiza com totais de linha e de coluna, células ordenáveis pelo cabeçalho e escala de cor opcional por intensidade do valor.

Implementação: `groupby` do Arquero. Limite prático de 200 colunas resultantes — acima disso, avise e sugira reduzir a granularidade.

### Exportação

Cada conjunto exporta em CSV e JSON. O painel inteiro exporta como arquivo de configuração (`.json`) que pode ser reimportado, restaurando gráficos, filtros e pivot — sem os dados, que são recoletados. Isso permite salvar análises sem que a aplicação armazene nada.

### Persistência

Tudo em `IndexedDB` no navegador, com recuperação automática ao reabrir. Nenhum dado de usuário sai do dispositivo.

---

## 8. Direção de design

> **Ao executar esta seção, assuma o papel de diretor de design de um estúdio conhecido por dar a cada cliente uma identidade que não poderia ser confundida com a de ninguém.** Trabalhe em duas passagens: primeiro escreva o plano de design (paleta, tipografia, layout, elemento-assinatura); depois critique esse plano contra o briefing e revise o que soar genérico; só então escreva código. Consulte a skill `frontend-design` antes de começar.

### Direção proposta: concretismo de dados

A referência é o design institucional brasileiro de meados do século XX — as publicações estatísticas do IBGE, o concretismo paulista, a herança geométrica de Waldemar Cordeiro e da Escola Superior de Desenho Industrial. Grade rigorosa, blocos de cor chapada, tipografia precisa, zero ornamento. É uma linguagem que já é sobre dados: gráficos são geometria, e essa tradição tratava geometria como conteúdo, não decoração.

**Evite deliberadamente** os três clichês de interface gerada por IA: fundo creme com serifa de alto contraste e acento terracota; fundo quase preto com um acento verde-ácido; e o layout tipo jornal com filetes capilares e colunas densas.

### Tokens

```css
--papel:    #F4F3EF;   /* fundo principal, branco de papel offset */
--papel-2:  #EAE8E2;   /* superfícies elevadas, cabeçalhos de tabela */
--tinta:    #16181A;   /* texto principal, quase preto quente */
--tinta-2:  #5B5F63;   /* texto secundário */
--cobalto:  #1F4E9C;   /* ação primária, links, estado ativo */
--ocre:     #D9A404;   /* destaque, avisos, medidor de custo */
--musgo:    #2E6B52;   /* confirmação, séries de dados positivas */
--carmim:   #B8352C;   /* erro, custo acima do teto */
--linha:    #C9C6BE;   /* divisórias, 1px */
```

Sequência categórica para gráficos derivada da paleta, com no mínimo 3:1 de contraste entre séries adjacentes. Modo escuro na segunda passagem, não na primeira.

### Tipografia

- **Display** — `Archivo Expanded` (600). Usada com restrição: cabeçalho da aplicação, títulos de seção do painel, o número do medidor de custo. A largura expandida dá autoridade institucional sem virar pastiche.
- **Corpo e interface** — `Chivo` (400/500). Legível em tamanhos pequenos, com personalidade suficiente para não parecer padrão de sistema.
- **Dados e código** — `IBM Plex Mono` (400). SQL, valores numéricos em tabelas, rótulos de eixo. Ativar `font-variant-numeric: tabular-nums` em toda coluna numérica.

Escala: 12 / 14 / 16 / 20 / 28 / 40. Dois pesos por família, no máximo. Sentence case sempre — nunca title case, nunca caixa alta em títulos.

### Layout

```
┌───────────────────────────────────────────────────────────────┐
│  cabeçalho — nome da aplicação · áreas cobertas · ajuda        │
├──────────────────┬────────────────────────────────────────────┤
│                  │  conjuntos ativos      [+ adicionar gráfico]│
│  CONVERSA        │  ┌──────────────────────────────────────┐  │
│  (384px fixo)    │  │ filtros: ano 2014-2023 ×  UF: AL,PE × │  │
│                  │  │ 1.204 de 8.930 linhas                 │  │
│  pergunta        │  └──────────────────────────────────────┘  │
│  ↓               │  ┌────────────────┐ ┌────────────────┐    │
│  ▓▓ PLANO DE     │  │                │ │                │    │
│  ▓▓ CONSULTA     │  │    gráfico     │ │    gráfico     │    │
│  ↓               │  │                │ │                │    │
│  resultado       │  └────────────────┘ └────────────────┘    │
│                  │  ┌──────────────────────────────────────┐  │
│  [ campo ]       │  │        tabela dinâmica                │  │
│                  │  └──────────────────────────────────────┘  │
└──────────────────┴────────────────────────────────────────────┘
```

Abaixo de 900px, conversa e painel viram duas abas em tela cheia, com o campo de pergunta fixo no rodapé da aba de conversa.

### Elemento-assinatura: o bloco de consulta

O cartão do `QueryPlan` é o momento memorável da aplicação e recebe tratamento distinto de tudo o mais. Composição:

1. **Explicação leiga em display**, 20px, ocupando a largura toda. É a primeira coisa que se lê — não o SQL.
2. **Medidor de custo concretista** — uma fileira de 20 quadrados de 8px preenchidos proporcionalmente aos bytes estimados contra o teto. Ocre até 60%, carmim acima. Ao lado, o volume em `Archivo Expanded`. Sem barra de progresso arredondada, sem gradiente.
3. **SQL como texto tipografado**, não como bloco de código genérico: fundo `--papel-2`, mono 13px, colunas e palavras-chave diferenciadas por peso em vez de por cor de sintaxe. Recolhido por padrão, com um resumo de uma linha visível — *"consulta 1 tabela, 2 filtros, 3 colunas de saída"*.
4. **Avisos** em bloco ocre com filete à esquerda, apenas quando existirem.
5. **Ações** ao pé: `Executar consulta` (cobalto, sólido) e `Ajustar` (contorno).

O tratamento do bloco todo: sem sombra, sem raio de canto além de 2px, apoiado numa faixa vertical sólida de 4px na cor da área temática (educação, saúde ou economia). Isso conecta o cartão ao domínio da pergunta sem precisar de ícone ou rótulo.

### Piso de qualidade

Responsivo até 360px. Foco de teclado visível em todo controle interativo. `prefers-reduced-motion` respeitado. Contraste mínimo AA. Estados vazios que convidam à ação, não que se desculpam. Mensagens de erro que dizem o que aconteceu e o que fazer, sem pedir desculpas e sem serem vagas.

### Redação da interface

Voz ativa, verbos concretos, nomes que descrevem o que a pessoa controla. `Executar consulta`, não `Submeter`. O botão que diz `Executar consulta` produz um estado que diz `Consulta executada`. Nada de "Aguarde..." genérico: durante o planejamento, diga o que está acontecendo — `Escolhendo a tabela`, `Escrevendo a consulta`, `Verificando o custo`.

---

## 9. Publicação

### Google Cloud Run — serviço único

**Região:** `southamerica-east1` (São Paulo), pela latência com os usuários. Note que o job do BigQuery executa na região onde os dados da Base dos Dados residem, independentemente de onde o container roda.

**Configuração:**

```
memória            1 GiB
CPU                1
timeout            300s
concorrência       40
min-instances      0        (escala a zero, custo zero em ociosidade)
max-instances      5        (teto de segurança)
ingress            all
```

**Identidade:** service account dedicada, com exatamente dois papéis — `roles/bigquery.jobUser` no projeto de faturamento e `roles/bigquery.dataViewer`. Sem chave JSON: o Cloud Run injeta a identidade no container. Nunca coloque credencial em arquivo ou variável de ambiente.

**Segredos:** `GEMINI_API_KEY` no Secret Manager, montado como variável de ambiente pelo Cloud Run.

**Dockerfile multi-stage:**

```
Estágio 1 (node:22-alpine)   → npm ci && npm run build  →  web/dist
Estágio 2 (python:3.12-slim) → uv sync --frozen
                             → COPY --from=1 web/dist  →  static/
                             → uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Respeite a variável `PORT` do Cloud Run. Rode como usuário não-root. Alvo de imagem final: abaixo de 400 MB.

**Implantação inicial:** `gcloud run deploy --source .` basta para começar. Migre para Cloud Build com gatilho no repositório quando o ciclo estabilizar.

**Domínio:** mapeamento de domínio próprio do Cloud Run, com TLS automático.

**Observabilidade:** logs estruturados em JSON vão para o Cloud Logging automaticamente. Registre por requisição: bytes estimados, bytes reais, tabelas selecionadas, tempo de cada etapa e se houve retentativa de validação. Esses números são o que vai orientar o ajuste dos resumos do catálogo.

**Custo esperado:** com escala a zero e uso moderado, o Cloud Run fica em poucos dólares por mês. O BigQuery oferece 1 TiB de consulta gratuito por mês e cobra cerca de US$ 6,25 por TiB acima disso — daí a importância do teto por consulta. O Gemini Flash em volume baixo fica na casa de centavos por dia.

---

## 10. Roadmap de implementação

Entregue em fases, cada uma funcionando de ponta a ponta.

**Fase 0 — Esqueleto**
Estrutura de pastas, `pyproject.toml`, Dockerfile, `/health` respondendo, front servido pelo FastAPI, deploy no Cloud Run funcionando. Sem funcionalidade. O objetivo é ter o caminho de publicação pronto antes de haver o que publicar.

**Fase 1 — Catálogo**
`TableMeta`, carregamento e validação dos YAML, `make validate-catalog`, endpoints de catálogo, cinco arquivos-gabarito com `TODO`.

**Fase 2 — Planejamento**
Cliente Gemini com saída estruturada, os dois prompts, seleção de tabela, geração de SQL, validador sqlglot com testes, dry run. Endpoint `/chat/plan` com SSE. Teste por linha de comando antes de existir interface.

**Fase 3 — Conversa**
Interface de chat, cartão de plano de consulta com explicação leiga, execução, tabela de resultados crua. Aqui a aplicação já é útil.

**Fase 4 — Painel**
Conjuntos de dados, camada Arquero, filtros, construtor de gráficos, grid, tabela dinâmica, exportação.

**Fase 5 — Design**
Passagem completa de direção de arte conforme a seção 8. Tokens, tipografia, elemento-assinatura, responsividade, acessibilidade, revisão de toda a redação de interface.

**Fase 6 — Endurecimento**
Cache de planos e resultados, rate limit por sessão, context caching no Gemini, retentativa de validação, tratamento de erro completo, telemetria.

### Prioridade de testes

O `sql_validator` é o componente de maior risco e recebe a cobertura mais densa: tentativas de DML, múltiplos statements, tabela fora da whitelist, ausência de filtro de partição, `SELECT *`, injeção via comentário, CTE que referencia tabela não permitida. Escreva esses testes antes da implementação.

---

## 11. Pontos que exigem decisão do desenvolvedor

- `[DECIDIR]` Região dos datasets da Base dos Dados no BigQuery, para configurar `BQ_LOCATION`.
- `[DECIDIR]` Teto de bytes por consulta. O plano sugere 5 GB como partida conservadora.
- `[DECIDIR]` Se haverá alguma forma de identificação de usuário. O plano assume acesso anônimo com rate limit por sessão anônima.
- `[DECIDIR]` As cinco tabelas iniciais — cadastro a cargo do desenvolvedor.
