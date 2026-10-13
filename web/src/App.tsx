import { useEffect, useState } from "react";
import { api, FalhaApi, type IndiceCatalogo, type ResumoTabela, type Saude } from "./lib/api";

/**
 * Fase 1 — catálogo.
 *
 * A tela mostra o que a aplicação sabe responder hoje, lendo o índice de
 * `/api/v1/catalog`. É o "o que posso perguntar" na sua forma mais crua: a
 * conversa entra na Fase 3 e o painel na Fase 4, e os dois lados da grade já
 * estão demarcados para não haver reescrita de layout depois.
 */

type Estado<T> =
  | { fase: "carregando" }
  | { fase: "ok"; dados: T }
  | { fase: "falha"; mensagem: string; detalhe?: string };

function useRecurso<T>(buscar: () => Promise<T>): Estado<T> {
  const [estado, setEstado] = useState<Estado<T>>({ fase: "carregando" });

  useEffect(() => {
    let ativo = true;
    buscar()
      .then((dados) => ativo && setEstado({ fase: "ok", dados }))
      .catch((e: unknown) => {
        if (!ativo) return;
        setEstado({
          fase: "falha",
          mensagem: e instanceof FalhaApi ? e.message : "O servidor não respondeu.",
          detalhe: e instanceof FalhaApi ? e.detalhe : undefined,
        });
      });
    return () => {
      ativo = false;
    };
    // `buscar` é estável — vem do objeto `api`, criado uma vez no módulo.
  }, [buscar]);

  return estado;
}

export function App() {
  const saude = useRecurso<Saude>(api.saude);
  const catalogo = useRecurso<IndiceCatalogo>(api.catalogo);

  return (
    <div className="flex min-h-dvh flex-col bg-papel text-tinta">
      <Cabecalho saude={saude} />

      <div className="flex flex-1 flex-col md:flex-row">
        <aside className="shrink-0 border-linha border-b md:w-96 md:border-r md:border-b-0">
          <Vaga titulo="Conversa" nota="Fase 3 — pergunta, plano de consulta e execução." />
        </aside>

        <main className="min-w-0 flex-1">
          <Catalogo estado={catalogo} />
        </main>
      </div>

      <Rodape saude={saude} />
    </div>
  );
}

function Cabecalho({ saude }: { saude: Estado<Saude> }) {
  return (
    <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-linha border-b px-4 py-3 md:px-6">
      <h1 className="font-display font-semibold text-base tracking-tight">
        Consulta a dados públicos
      </h1>
      <p className="text-tinta-2 text-xs">Educação · Saúde · Economia</p>
      <span className="ml-auto font-mono text-tinta-2 text-xs">
        {saude.fase === "ok" ? `v${saude.dados.versao}` : "—"}
      </span>
    </header>
  );
}

function Vaga({ titulo, nota }: { titulo: string; nota: string }) {
  return (
    <section className="p-4 md:p-6">
      <Titulo>{titulo}</Titulo>
      <p className="mt-2 max-w-prose text-sm text-tinta-2">{nota}</p>
    </section>
  );
}

function Titulo({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-display font-semibold text-tinta-2 text-xs uppercase tracking-widest">
      {children}
    </h2>
  );
}

/** Faixa vertical sólida na cor da área — conecta a tabela ao domínio. */
const FAIXA_POR_AREA: Record<string, string> = {
  educacao: "bg-area-educacao",
  saude: "bg-area-saude",
  economia: "bg-area-economia",
};

const NOME_AREA: Record<string, string> = {
  educacao: "Educação",
  saude: "Saúde",
  economia: "Economia",
};

function Catalogo({ estado }: { estado: Estado<IndiceCatalogo> }) {
  if (estado.fase === "carregando") {
    return (
      <section className="p-4 md:p-6">
        <Titulo>Tabelas disponíveis</Titulo>
        <p className="mt-2 text-sm text-tinta-2">Lendo o catálogo</p>
      </section>
    );
  }

  if (estado.fase === "falha") {
    return (
      <section className="p-4 md:p-6">
        <Titulo>Tabelas disponíveis</Titulo>
        <div className="mt-2 border-carmim border-l-4 bg-papel-2 py-2 pl-3">
          <p className="text-sm">{estado.mensagem}</p>
          {estado.detalhe && <ListaProblemas detalhe={estado.detalhe} />}
        </div>
      </section>
    );
  }

  const { total, tabelas } = estado.dados;

  return (
    <section className="p-4 md:p-6">
      <Titulo>Tabelas disponíveis</Titulo>

      {total === 0 ? (
        <div className="mt-3 max-w-prose border-ocre border-l-4 bg-papel-2 py-3 pl-4">
          <p className="text-sm">
            Nenhuma tabela publicada ainda. Os cinco gabaritos estão em
            <code className="mx-1 font-mono text-xs">src/app/catalog/</code>
            esperando o cadastro.
          </p>
          <p className="mt-2 text-sm text-tinta-2">
            Preencha um arquivo, troque <code className="font-mono text-xs">status</code> para
            <code className="mx-1 font-mono text-xs">ativo</code>e rode
            <code className="ml-1 font-mono text-xs">make validar-catalogo</code>.
          </p>
        </div>
      ) : (
        <ul className="mt-4 grid gap-px bg-linha">
          {tabelas.map((t) => (
            <CartaoTabela key={t.id} tabela={t} />
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Erros do catálogo, um bloco por arquivo.
 *
 * O detalhe chega como texto do validador: `  • arquivo: mensagem` seguido de
 * linhas `campo \`x\`: erro`. Erros iguais em campos vizinhos (as 25 colunas
 * sem tipo, por exemplo) viram uma linha só, com a contagem.
 */
function ListaProblemas({ detalhe }: { detalhe: string }) {
  const arquivos = detalhe
    .split(/^\s*• /m)
    .map((bloco) => bloco.trim())
    .filter(Boolean)
    .map((bloco) => {
      const [cabeca = "", ...campos] = bloco.split("\n").map((l) => l.trim());
      const separador = cabeca.indexOf(": ");
      const arquivo = separador > 0 ? cabeca.slice(0, separador) : cabeca.replace(/:$/, "");
      const geral = separador > 0 ? cabeca.slice(separador + 2) : "";
      return { arquivo, geral, campos: agruparCampos(campos.filter(Boolean)) };
    });

  return (
    <ul className="mt-3 grid gap-3 pr-3">
      {arquivos.map((a) => (
        <li key={a.arquivo}>
          <p className="font-mono text-xs">{a.arquivo}</p>
          {a.geral && <p className="mt-0.5 text-sm text-tinta-2">{a.geral}</p>}
          {a.campos.length > 0 && (
            <ul className="mt-1 grid gap-0.5">
              {a.campos.map((c) => (
                <li key={c.campos} className="text-sm text-tinta-2">
                  <code className="font-mono text-xs text-tinta">{c.campos}</code> — {c.erro}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}

function agruparCampos(linhas: string[]): { campos: string; erro: string }[] {
  const grupos = new Map<string, string[]>();
  for (const linha of linhas) {
    const m = linha.match(/^campo `([^`]+)`: (.*)$/);
    const [campo, erro] = m ? [m[1] ?? "", m[2] ?? ""] : ["", linha];
    grupos.set(erro, [...(grupos.get(erro) ?? []), campo]);
  }
  return [...grupos].map(([erro, campos]) => ({
    erro,
    campos:
      campos.length > 2 ? `${campos[0]} … ${campos.at(-1)} (${campos.length})` : campos.join(", "),
  }));
}

function CartaoTabela({ tabela }: { tabela: ResumoTabela }) {
  const cobertura =
    tabela.cobertura_inicio && tabela.cobertura_fim
      ? `${tabela.cobertura_inicio}–${tabela.cobertura_fim}`
      : null;

  return (
    <li className="flex bg-papel">
      <span
        aria-hidden="true"
        className={`w-1 shrink-0 ${FAIXA_POR_AREA[tabela.area] ?? "bg-linha"}`}
      />
      <div className="min-w-0 flex-1 px-4 py-3">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <h3 className="font-display font-semibold text-base">{tabela.nome_exibicao}</h3>
          <span className="text-tinta-2 text-xs">
            {NOME_AREA[tabela.area] ?? tabela.area} · {tabela.fonte}
          </span>
        </div>
        <p className="mt-1 max-w-prose text-sm text-tinta-2">{tabela.resumo}</p>
        <p className="mt-2 font-mono text-tinta-2 text-xs">
          {cobertura ? `${cobertura} · ` : ""}
          {tabela.total_colunas} colunas · {tabela.id}
        </p>
      </div>
    </li>
  );
}

/**
 * Barra de estado do serviço — teste de fumaça do caminho completo, visível
 * a olho nu.
 */
function Rodape({ saude }: { saude: Estado<Saude> }) {
  const { cor, texto } = descrever(saude);
  return (
    <footer className="flex items-center gap-3 border-linha border-t px-4 py-2 md:px-6">
      <span aria-hidden="true" className={`size-2 shrink-0 ${cor}`} />
      <p className="font-mono text-xs" role="status">
        {texto}
      </p>
    </footer>
  );
}

function descrever(saude: Estado<Saude>): { cor: string; texto: string } {
  switch (saude.fase) {
    case "carregando":
      return { cor: "bg-ocre", texto: "Verificando o serviço" };
    case "ok": {
      const { ambiente, tabelas_carregadas, tabelas_rascunho } = saude.dados;
      const rascunhos = tabelas_rascunho > 0 ? ` · ${tabelas_rascunho} em rascunho` : "";
      return {
        cor: "bg-musgo",
        texto: `Serviço no ar · ambiente ${ambiente} · ${tabelas_carregadas} tabelas publicadas${rascunhos}`,
      };
    }
    case "falha":
      return { cor: "bg-carmim", texto: saude.mensagem };
  }
}
