# Consulta a dados públicos

Aplicação que traduz perguntas em português para consultas SQL sobre o datalake
público da [Base dos Dados](https://basedosdados.org/) no BigQuery, submete o
plano à aprovação do usuário e entrega o resultado num painel analítico.

O briefing completo está em [claude_code/plano-consulta-dados-publicos.md](claude_code/plano-consulta-dados-publicos.md).

**Estado: Fase 1 — catálogo.** O cadastro de tabelas está de pé, com cinco
gabaritos esperando preenchimento. O roadmap segue na seção final.

---

## Como rodar

Requisitos: Python 3.12+ e Node 22+.

```bash
make instalar          # cria a .venv, instala Python e Node
```

Sem `make` no Windows, os mesmos passos à mão:

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt
cd web && npm install
```

### Desenvolvimento — dois processos

O front e o back rodam separados, com o Vite fazendo proxy de `/api` para o
uvicorn. Recarregamento instantâneo dos dois lados.

```bash
make dev-api    # uvicorn na 8000, com reload
make dev-web    # vite na 5173  ← abra esta
```

### Como roda em produção — um processo

O front compilado vira arquivo estático servido pelo próprio FastAPI. Para
reproduzir isso localmente antes de publicar:

```bash
make build      # compila o front para static/ e sobe o uvicorn na 8000
```

### Testes e lint

```bash
make testar     # pytest
make lint       # ruff (Python) + biome (TypeScript)
```

---

## Cadastrar uma tabela

O catálogo é a única fonte do que a aplicação sabe responder. Não há banco de
dados: são arquivos YAML versionados junto com o código, um por tabela, em
`src/app/catalog/<area>/<id>.yaml`.

O formato está documentado campo a campo em
[`src/app/catalog/_schema.yaml`](src/app/catalog/_schema.yaml), com o porquê de
cada regra. Os cinco gabaritos já estão criados, com `TODO` nos campos.

```bash
make validar-catalogo
```

Roda a mesma validação do startup, sem subir servidor, e aponta arquivo e campo
de cada erro. Use a cada arquivo salvo.

**O ciclo:**

1. Abra um gabarito e preencha. Ele nasce com `status: rascunho`.
2. `make validar-catalogo` até passar limpo.
3. Troque para `status: ativo`. Só então a validação estrita entra e a tabela
   passa a aparecer no índice que o modelo lê.

**Por que a validação é chata.** O que está no YAML é literalmente o que o
modelo lê para decidir qual tabela usar e como escrever o SQL. Um resumo vago
vira escolha errada de tabela; uma partição não declarada vira consulta que
varre a tabela inteira e estoura o teto de custo. O erro é muito mais barato
aqui do que na conta do BigQuery.

**Um YAML quebrado derruba o startup.** É deliberado: ignorar em silêncio faria
a tabela sumir do índice, e a aplicação passaria a responder "não tenho
cobertura para isso" sem ninguém entender por quê.

---

## Mapa de temas das comissões

Diz, para cada tema acompanhado por uma comissão da ALEPE, em quais conjuntos
de dados da Base dos Dados procurar. O catálogo acima descreve tabelas prontas
para gerar SQL; o mapa aponta a fonte certa para um assunto — inclusive as que
ainda não têm tabela cadastrada, e os temas que ainda não têm fonte nenhuma.

A fonte é a planilha [`dados/temas_comissoes_alepe.xlsx`](dados/temas_comissoes_alepe.xlsx),
editada no Excel. A aplicação lê a versão em texto,
[`src/app/temas/comissoes.yaml`](src/app/temas/comissoes.yaml), gerada por:

```bash
make importar-temas
```

Rode a cada alteração na planilha e versione os dois arquivos juntos. O
comando recusa a importação e aponta a linha quando falta a sigla da
comissão (`Nome - SIGLA`), quando o conjunto vem sem link ou quando o link não
é de `basedosdados.org/dataset/`. Qualquer anotação numa coluna além da D vira
`nota` do tema.

Para conferir o que a aplicação encontraria para um assunto:

```bash
.venv/Scripts/python -m app.cli onde-procurar "violência contra a mulher"
```

A busca é por palavras, sem acento e sem caixa — não entende sinônimo
("creche" não acha "Educação básica"). Na Fase 2 o mapa inteiro vai ao Gemini
junto com a pergunta, e é ele quem faz essa ponte.

---

## Estrutura

```
src/app/            backend FastAPI
  core/             configuração, log estruturado, handlers de erro
  api/v1/           rotas HTTP
  domain/           entidades e erros puros, sem I/O
  services/         catálogo, planejador, LLM, SQL, BigQuery
  catalog/          cadastro das tabelas em YAML (Fase 1)
  temas/            mapa comissão → tema → conjuntos, gerado da planilha
  prompts/          prompts do Gemini (Fase 2)
dados/              planilha de temas das comissões (fonte do mapa)
web/                frontend Vite + React 19 + TypeScript
tests/              pytest
modelos/            referência de design e código — não faz parte do build
static/             artefato do build do front (gerado, fora do git)
```

**Regra de dependência:** `api` → `services` → `domain`. A camada `api` não
importa cliente de BigQuery nem de Gemini. A `services` não conhece HTTP. A
`domain` não importa nada do projeto. É o que permite testar validador e
planejador sem subir servidor nem tocar na nuvem.

---

## Configuração

Copie `.env.example` para `.env` e preencha. O `.env` nunca entra no
repositório nem na imagem Docker — em produção o Cloud Run injeta as variáveis
e a chave do Gemini vem do Secret Manager.

---

## Publicação — Cloud Run

Projeto alvo: `consultas-consuleg`, região `southamerica-east1`.

### Uma vez por projeto

Habilita as APIs e cria a service account com exatamente dois papéis —
`bigquery.jobUser` e `bigquery.dataViewer`. Sem chave JSON: o Cloud Run injeta
a identidade no container.

```bash
make preparar-gcp
```

### A cada publicação

```bash
make implantar
```

O que o comando faz: envia o código para o Cloud Build, que executa o
`Dockerfile` multi-stage (Node compila o front, a imagem final é só Python) e
publica o serviço com 1 GiB, escala de 0 a 5 instâncias e timeout de 300s.

Depois, para conferir:

```bash
curl https://<url-do-servico>/api/v1/health
make logs
```

---

## Roadmap

| Fase | Escopo | Estado |
|---|---|---|
| 0 | Esqueleto, Dockerfile, `/health`, front servido pelo FastAPI | **feito** — falta o deploy |
| 1 | Catálogo: `TableMeta`, carga dos YAML, endpoints, gabaritos | **feito** — falta cadastrar as tabelas |
| 2 | Planejamento: Gemini, prompts, validador sqlglot, dry run, SSE | |
| 3 | Conversa: chat, cartão de plano, execução, tabela de resultados | |
| 4 | Painel: conjuntos, Arquero, filtros, gráficos, pivot, mapa de PE, exportação `.xlsx` | |
| 5 | Design: passagem completa de direção de arte | |
| 6 | Endurecimento: cache, rate limit, retentativa, telemetria | |

---

## Desvios do plano original

Registrados aqui para não virarem descoberta arqueológica depois.

- **Python 3.14 em vez de 3.12** no Dockerfile. É a única versão instalada na
  máquina de desenvolvimento, e manter venv e container iguais evita a classe
  de bug que só aparece dentro da imagem.
- **pip + `requirements.txt` com versões fixas em vez de uv + `uv.lock`**,
  por decisão do desenvolvedor. Não há lockfile de resolução transitiva; as
  versões diretas estão fixadas.
- **Sem `docker` local.** A imagem não foi construída nesta máquina — o
  `Dockerfile` será exercitado pelo Cloud Build no primeiro `make implantar`.
- **Campo `status` no cadastro**, fora do formato descrito no plano. Sem ele os
  gabaritos com `TODO` derrubariam o startup, e o plano pede as duas coisas ao
  mesmo tempo: gabarito com `TODO` no repositório e falha dura em YAML
  inválido. `rascunho` valida a estrutura mas fica fora do índice; `ativo`
  passa pela validação estrita.
- **Campo `sem_particao`**, para a tabela que realmente não tem partição
  declarar isso de propósito, em vez de a lista vazia passar por esquecimento.
