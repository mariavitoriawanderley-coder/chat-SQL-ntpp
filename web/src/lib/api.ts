/**
 * Cliente tipado da API.
 *
 * Todo caminho é relativo. Em desenvolvimento o proxy do Vite manda `/api`
 * para o uvicorn; em produção front e back são o mesmo processo. Uma URL
 * absoluta aqui quebraria um dos dois cenários.
 */

/** Formato único de erro do servidor — ver `core/exceptions.py`. */
export type ErroApi = {
  codigo: string;
  mensagem: string;
  /** Só vem no ambiente local — ex.: a lista de erros do catálogo. */
  detalhe?: string;
};

export class FalhaApi extends Error {
  readonly codigo: string;
  readonly status: number;
  readonly detalhe?: string;

  constructor(erro: ErroApi, status: number) {
    super(erro.mensagem);
    this.name = "FalhaApi";
    this.codigo = erro.codigo;
    this.status = status;
    this.detalhe = erro.detalhe;
  }
}

async function pedir<T>(caminho: string, init?: RequestInit): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(`/api/v1${caminho}`, {
      headers: { Accept: "application/json", ...init?.headers },
      ...init,
    });
  } catch {
    // Rede fora do ar, servidor não subiu, DNS. Nunca chegou resposta.
    throw new FalhaApi(
      { codigo: "sem_conexao", mensagem: "Não foi possível falar com o servidor." },
      0,
    );
  }

  if (!resposta.ok) {
    const erro = await resposta
      .json()
      .then((c) => c?.erro as ErroApi | undefined)
      .catch(() => undefined);
    throw new FalhaApi(
      erro ?? { codigo: "erro_interno", mensagem: `O servidor respondeu ${resposta.status}.` },
      resposta.status,
    );
  }

  return (await resposta.json()) as T;
}

export type Saude = {
  status: string;
  versao: string;
  ambiente: string;
  tabelas_carregadas: number;
  tabelas_rascunho: number;
};

export type Area =
  | "educacao"
  | "saude"
  | "economia"
  | "seguranca_publica"
  | "meio_ambiente"
  | "agropecuaria"
  | "assistencia_social"
  | "financas_publicas"
  | "eleicoes"
  | "ciencia_tecnologia";

/** Item do índice do catálogo — sem colunas, de propósito. */
export type ResumoTabela = {
  id: string;
  nome_exibicao: string;
  area: Area;
  fonte: string;
  resumo: string;
  palavras_chave: string[];
  perguntas_exemplo: string[];
  cobertura_inicio: number | null;
  cobertura_fim: number | null;
  total_colunas: number;
};

export type IndiceCatalogo = {
  total: number;
  areas: Area[];
  tabelas: ResumoTabela[];
};

export const api = {
  saude: () => pedir<Saude>("/health"),
  catalogo: () => pedir<IndiceCatalogo>("/catalog"),
  tabela: (id: string) => pedir<ResumoTabela>(`/catalog/${encodeURIComponent(id)}`),
};
