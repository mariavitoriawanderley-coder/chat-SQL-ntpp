"""Linha de comando da aplicação.

Ferramentas de quem cadastra, para conferir o trabalho sem subir servidor:

    make validar-catalogo
    .venv/Scripts/python -m app.cli validar-catalogo
    .venv/Scripts/python -m app.cli importar-temas [planilha.xlsx]
    .venv/Scripts/python -m app.cli onde-procurar "violência contra a mulher"
"""

import argparse
import sys
from pathlib import Path

from app.core.config import obter_config
from app.core.logging import configurar_logging, saida_utf8
from app.domain.errors import CatalogoInvalido
from app.services.catalog_service import ServicoCatalogo
from app.services.temas_service import ServicoTemas, escrever_yaml, ler_planilha, montar_mapa


def validar_catalogo() -> int:
    # O relatório é a saída; o log de carga só atrapalharia a leitura.
    configurar_logging(nivel="WARNING", ambiente="local")

    cfg = obter_config()
    servico = ServicoCatalogo(cfg.dir_catalogo)

    try:
        servico.carregar()
    except CatalogoInvalido as e:
        print(f"\n  {e.mensagem}\n", file=sys.stderr)
        if e.detalhe:
            print(e.detalhe, file=sys.stderr)
        print("", file=sys.stderr)
        return 1

    ativas = servico.indice()
    todas = servico.todas(incluir_rascunhos=True)
    rascunhos = [t for t in todas if t.pendente]

    print(f"\n  Catálogo válido — {len(todas)} arquivos lidos.\n")

    if ativas:
        print(f"  Ativas ({len(ativas)}) — visíveis ao modelo:")
        for area, tabelas in sorted(servico.por_area().items()):
            print(f"    {area}")
            for t in tabelas:
                particao = ", ".join(t.particoes) if t.particoes else "sem partição"
                print(f"      {t.id}  ·  {len(t.colunas)} colunas  ·  {particao}")
        print("")

    if rascunhos:
        print(f"  Rascunhos ({len(rascunhos)}) — fora do índice até `status: ativo`:")
        for t in rascunhos:
            print(f"    {t.area}/{t.id}")
        print("")

    auxiliares = servico.auxiliares()
    if auxiliares:
        print(f"  Auxiliares ({len(auxiliares)}) — só para JOIN, nunca escolhidas:")
        for a in auxiliares:
            print(f"    {a.referencia_bigquery}")
        print("")

    if not ativas:
        print(
            "  Nenhuma tabela ativa. A aplicação sobe, mas vai responder que não\n"
            "  tem cobertura para qualquer pergunta.\n"
        )

    return 0


def importar_temas(planilha: Path | None) -> int:
    configurar_logging(nivel="WARNING", ambiente="local")
    cfg = obter_config()
    origem = planilha or cfg.planilha_temas

    try:
        mapa = montar_mapa(ler_planilha(origem))
    except FileNotFoundError:
        print(f"\n  Planilha não encontrada: {origem}\n", file=sys.stderr)
        return 1
    except CatalogoInvalido as e:
        print(f"\n  {e.mensagem}\n", file=sys.stderr)
        if e.detalhe:
            print(e.detalhe + "\n", file=sys.stderr)
        return 1

    escrever_yaml(mapa, cfg.arquivo_temas)

    temas = [t for c in mapa.comissoes for t in c.temas]
    sem_fonte = [t for t in temas if t.sem_fonte]
    print(f"\n  Mapa de temas gerado em src/app/temas/{cfg.arquivo_temas.name}\n")
    for c in mapa.comissoes:
        vazios = sum(1 for t in c.temas if t.sem_fonte)
        nota = f"  ·  {vazios} sem fonte" if vazios else ""
        print(f"    {c.sigla:<7} {len(c.temas):>3} temas{nota}")
    print(f"\n  Total: {len(temas)} temas, {len(sem_fonte)} ainda sem conjunto de dados.\n")
    return 0


def onde_procurar(assunto: str, sigla: str | None) -> int:
    configurar_logging(nivel="WARNING", ambiente="local")
    servico = ServicoTemas(obter_config().arquivo_temas)
    try:
        achados = servico.onde_procurar(assunto, sigla)
    except CatalogoInvalido as e:
        print(f"\n  {e.mensagem}\n", file=sys.stderr)
        return 1

    if not achados:
        print(f"\n  Nenhum tema encontrado para “{assunto}”.\n")
        return 0

    print(f"\n  Onde procurar “{assunto}”:\n")
    for i in achados:
        print(f"    {i.comissao.sigla} · {i.tema.nome}")
        if i.tema.sem_fonte:
            print("        (tema ainda sem conjunto de dados)")
        for cj in i.tema.conjuntos:
            print(f"        {cj.nome}  —  {cj.url}")
    print("")
    return 0


def main() -> int:
    saida_utf8()
    parser = argparse.ArgumentParser(prog="app", description="Ferramentas da aplicação.")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("validar-catalogo", help="Valida os YAML do catálogo e lista o que foi lido.")
    p_importar = sub.add_parser(
        "importar-temas", help="Gera src/app/temas/comissoes.yaml a partir da planilha."
    )
    p_importar.add_argument("planilha", nargs="?", type=Path, help="padrão: dados/…alepe.xlsx")
    p_procurar = sub.add_parser("onde-procurar", help="Mostra os temas e conjuntos de um assunto.")
    p_procurar.add_argument("assunto")
    p_procurar.add_argument("--comissao", help="restringe a uma sigla, ex.: CSAS")

    args = parser.parse_args()
    if args.comando == "validar-catalogo":
        return validar_catalogo()
    if args.comando == "importar-temas":
        return importar_temas(args.planilha)
    if args.comando == "onde-procurar":
        return onde_procurar(args.assunto, args.comissao)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
