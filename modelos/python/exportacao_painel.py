"""
exportacao_painel.py
====================
Exportação da PASTA DE TRABALHO do painel (Etapa 6).

Monta um único .xlsx com tudo o que está na tela do painel, separado por abas:

  - "Filtros"          : filtros da pesquisa inicial (fonte, anos, classificação
                         validada / palavras-chave) + filtros aplicados no painel
                         + estado da atualização pelo IPCA;
  - "Tabela dinâmica"  : a configuração (linhas/coluna/valor/agregação) e a
                         tabela como está no painel;
  - uma aba por gráfico: os dados AGREGADOS que alimentam o gráfico e um gráfico
                         NATIVO do Excel (editável, ligado às células) com a
                         mesma paleta e o mesmo tipo do painel.

O tree map não tem equivalente nativo no openpyxl: vira um gráfico de barras
horizontais com a hierarquia achatada ("Grupo 1 / Grupo 2"), preservando os
valores exibidos no painel.

Os dados chegam prontos do navegador (já filtrados, já atualizados pelo IPCA e
já agregados por painel.js / painel_graficos.js). Aqui só há formatação.
"""

import io
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.marker import DataPoint
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from exportacao import valor_celula

_FONTE = "Arial"
_MAX_LARGURA = 60
_MIN_LARGURA = 10

# Mesma paleta categórica de painel_graficos.js (PALETA), em hexadecimal — os
# dois arquivos mudam juntos. A ORDEM é o mecanismo de segurança para daltonismo
# (validada sobre fundo branco): não reordene sem revalidar.
PALETA = ["1A6BB5", "E2691F", "0F9C8A", "C33A35", "E0A800", "7A5CC4", "0B7A3B", "D4548C"]

_AZUL = "14508C"
_CINZA = "F1F4F8"

# Séries maiores que isto viram um gráfico ilegível (e uma planilha lenta).
_MAX_PONTOS = 500

_ROTULO_TIPO = {
    "linha": "Linhas",
    "barra": "Barras",
    "treemap": "Tree map",
    "pizza": "Pizza",
}

_ROTULO_FONTE = {
    "portal_transparencia": "Portal da Transparência de PE",
    "dados_abertos_tce": "Dados Abertos do TCE-PE",
}

_ROTULO_AGREGACAO = {
    "soma": "Soma",
    "contagem": "Contagem",
    "contagem_distinta": "Contagem distinta",
    "media": "Média",
}

# Níveis da classificação orçamentária, na ordem em que fazem sentido para ler.
_NIVEIS: Tuple[Tuple[str, str], ...] = (
    ("funcao", "Função"),
    ("subfuncao", "Subfunção"),
    ("programa", "Programa"),
    ("acao", "Ação"),
    ("subacao", "Subação"),
    ("categoria", "Categoria econômica"),
    ("grupo", "Grupo de despesa"),
    ("modalidade", "Modalidade de aplicação"),
    ("elemento", "Elemento de despesa"),
    ("orgao", "Órgão"),
    ("uo", "Unidade orçamentária"),
    ("ug", "Unidade gestora"),
    ("fonte", "Fonte de recursos"),
    ("ficha", "Ficha"),
)


# ---------------------------------------------------------------------------
# Formatação básica
# ---------------------------------------------------------------------------
def _titulo_aba(ws, texto: str, linha: int = 1) -> int:
    """Escreve o título da aba (barra azul em A{linha}) e devolve a linha seguinte."""
    c = ws.cell(row=linha, column=1, value=valor_celula(texto))
    c.font = Font(name=_FONTE, bold=True, size=13, color="FFFFFF")
    c.fill = PatternFill("solid", start_color=_AZUL)
    c.alignment = Alignment(vertical="center")
    ws.row_dimensions[linha].height = 22
    return linha + 2


def _secao(ws, texto: str, linha: int) -> int:
    """Subtítulo de seção (faixa cinza) — devolve a linha seguinte."""
    c = ws.cell(row=linha, column=1, value=valor_celula(texto))
    c.font = Font(name=_FONTE, bold=True, size=11, color=_AZUL)
    c.fill = PatternFill("solid", start_color=_CINZA)
    return linha + 1


def _par(ws, rotulo: str, valor: Any, linha: int, recuo: int = 0, formato: str = "") -> int:
    """Linha "rótulo | valor" — devolve a linha seguinte."""
    r = ws.cell(row=linha, column=1 + recuo, value=valor_celula(rotulo))
    r.font = Font(name=_FONTE, bold=True)
    r.alignment = Alignment(vertical="top")
    v = ws.cell(row=linha, column=2 + recuo, value=valor_celula(valor))
    v.font = Font(name=_FONTE)
    v.alignment = Alignment(vertical="top", wrap_text=True)
    if formato:
        v.number_format = formato
    return linha + 1


def _tabela(
    ws,
    colunas: List[str],
    registros: List[Dict[str, Any]],
    linha: int,
    autofiltro: bool = True,
) -> int:
    """
    Escreve cabeçalho + dados a partir de `linha`. Devolve a linha seguinte à
    última escrita (ou seja, o fim da tabela + 1).
    """
    if not colunas:
        return linha

    negrito = Font(name=_FONTE, bold=True, color="FFFFFF")
    fundo = PatternFill("solid", start_color=_AZUL)
    borda = Border(bottom=Side(style="thin", color="D8DEE7"))
    for i, col in enumerate(colunas, start=1):
        c = ws.cell(row=linha, column=i, value=valor_celula(col))
        c.font = negrito
        c.fill = fundo
        c.alignment = Alignment(vertical="center", wrap_text=True)

    fonte_padrao = Font(name=_FONTE)
    for j, reg in enumerate(registros, start=1):
        for i, col in enumerate(colunas, start=1):
            c = ws.cell(row=linha + j, column=i, value=valor_celula(reg.get(col)))
            c.font = fonte_padrao
            c.border = borda
            if isinstance(c.value, float):
                c.number_format = "#,##0.00"
            elif isinstance(c.value, int) and not isinstance(c.value, bool):
                c.number_format = "#,##0"

    fim = linha + len(registros)
    if autofiltro and registros:
        ws.auto_filter.ref = f"A{linha}:{get_column_letter(len(colunas))}{fim}"
    return fim + 1


def _larguras(ws, colunas: List[str], registros: List[Dict[str, Any]], coluna_inicial: int = 1) -> None:
    """Larguras aproximadas a partir de uma amostra (não custa caro)."""
    amostra = registros[:200]
    for i, col in enumerate(colunas, start=coluna_inicial):
        largura = len(str(col))
        for reg in amostra:
            largura = max(largura, len(str(reg.get(col, ""))))
        ws.column_dimensions[get_column_letter(i)].width = max(
            _MIN_LARGURA, min(_MAX_LARGURA, largura + 2)
        )


def _nome_aba(wb: Workbook, base: str) -> str:
    """Nome de aba válido (≤31 caracteres, sem []:*?/\\) e único na pasta."""
    limpo = "".join(" " if ch in "[]:*?/\\" else ch for ch in str(base)).strip() or "Aba"
    nome = limpo[:31]
    n = 2
    while nome in wb.sheetnames:
        sufixo = f" ({n})"
        nome = limpo[: 31 - len(sufixo)] + sufixo
        n += 1
    return nome


# ---------------------------------------------------------------------------
# Aba 1 — Filtros
# ---------------------------------------------------------------------------
def _rotulo_item(item: Any) -> str:
    """{'codigo': '12', 'nome': '12 - EDUCAÇÃO'} -> '12 - EDUCAÇÃO' (sem duplicar)."""
    if not isinstance(item, dict):
        return "" if item is None else str(item)
    codigo = str(item.get("codigo") or "").strip()
    nome = str(item.get("nome") or "").strip()
    if codigo and nome and not nome.startswith(codigo):
        return f"{codigo} - {nome}"
    return nome or codigo


def _aba_filtros(wb: Workbook, dados: Dict[str, Any]) -> None:
    ws = wb.create_sheet(_nome_aba(wb, "Filtros"))
    linha = _titulo_aba(ws, f"Filtros — {dados.get('titulo') or 'Painel de empenhos'}")

    # --- Pesquisa inicial (o que foi pedido ao chat e executado na fonte) ---
    pedido = dados.get("pesquisa") or {}
    linha = _secao(ws, "PESQUISA INICIAL", linha)
    fonte = dados.get("fonte") or pedido.get("fonte") or ""
    linha = _par(ws, "Fonte de dados", _ROTULO_FONTE.get(fonte, fonte), linha)
    anos = dados.get("anos") or pedido.get("anos") or []
    linha = _par(ws, "Anos pesquisados", ", ".join(str(a) for a in anos), linha)
    modo = pedido.get("modo") or "classificacao"
    linha = _par(
        ws,
        "Modo de busca",
        "Classificação orçamentária" if modo == "classificacao" else "Histórico (palavras-chave)",
        linha,
    )
    if dados.get("campo_ug") or dados.get("campo_ne"):
        linha = _par(
            ws,
            "Chave única (deduplicação)",
            f"{dados.get('campo_ug') or '?'} + {dados.get('campo_ne') or '?'}",
            linha,
        )
    linha += 1

    if modo == "historico":
        linha = _secao(ws, "PALAVRAS-CHAVE", linha)
        palavras = pedido.get("palavras_chave") or []
        if palavras:
            for p in palavras:
                linha = _par(ws, "Palavra-chave", p, linha)
        else:
            linha = _par(ws, "Palavra-chave", "(nenhuma registrada)", linha)
    else:
        linha = _secao(ws, "CLASSIFICAÇÃO ORÇAMENTÁRIA VALIDADA", linha)
        classificacoes = pedido.get("classificacoes") or (
            [pedido["classificacao"]] if pedido.get("classificacao") else []
        )
        if not classificacoes:
            linha = _par(ws, "Classificação", "(nenhuma registrada)", linha)
        for i, classif in enumerate(classificacoes, start=1):
            rotulo = (classif or {}).get("rotulo")
            c = ws.cell(row=linha, column=1, value=valor_celula(f"Classificação {i}"))
            c.font = Font(name=_FONTE, bold=True, color=_AZUL)
            if rotulo:
                ws.cell(row=linha, column=2, value=valor_celula(rotulo)).font = Font(
                    name=_FONTE, italic=True
                )
            linha += 1
            niveis_preenchidos = 0
            for chave, nome_nivel in _NIVEIS:
                item = (classif or {}).get(chave)
                if not item:
                    continue
                linha = _par(ws, nome_nivel, _rotulo_item(item), linha, recuo=1)
                niveis_preenchidos += 1
            if not niveis_preenchidos:
                linha = _par(ws, "(sem níveis)", "", linha, recuo=1)
            linha += 1
    linha += 1

    # --- Filtros aplicados no painel ---
    linha = _secao(ws, "FILTROS APLICADOS NO PAINEL", linha)
    filtros = dados.get("filtros") or []
    if not filtros:
        linha = _par(ws, "(nenhum filtro aplicado)", "todos os registros da pesquisa", linha)
    else:
        cabecalho = ["Coluna", "Valores selecionados", "Qtd. de valores"]
        registros = [
            {
                "Coluna": f.get("coluna"),
                "Valores selecionados": "; ".join(
                    str(v) if str(v) != "" else "(vazio)" for v in (f.get("valores") or [])
                )
                or f.get("texto")
                or "",
                "Qtd. de valores": len(f.get("valores") or []),
            }
            for f in filtros
        ]
        linha = _tabela(ws, cabecalho, registros, linha, autofiltro=False)
    linha += 1

    # --- IPCA e contagens ---
    linha = _secao(ws, "ATUALIZAÇÃO PELA INFLAÇÃO (IPCA)", linha)
    ipca = dados.get("ipca") or {}
    ativo = bool(ipca.get("ativo"))
    linha = _par(ws, "Valores atualizados pelo IPCA", "Sim" if ativo else "Não", linha)
    fatores = ipca.get("fatores") or {}
    if ativo and fatores:
        for ano in sorted(fatores, key=str):
            linha = _par(ws, f"Fator {ano}", fatores[ano], linha, recuo=1, formato="0.0000")
    linha += 1

    linha = _secao(ws, "REGISTROS", linha)
    linha = _par(ws, "Registros exibidos (após filtros)", dados.get("registros_exibidos"), linha)
    linha = _par(ws, "Registros na pesquisa", dados.get("registros_total"), linha)
    linha = _par(ws, "Gerado em", datetime.now().strftime("%d/%m/%Y %H:%M"), linha)

    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["C"].width = 46
    ws.column_dimensions["D"].width = 18


# ---------------------------------------------------------------------------
# Aba 2 — Tabela dinâmica
# ---------------------------------------------------------------------------
def _aba_pivot(wb: Workbook, pivot: Dict[str, Any]) -> None:
    ws = wb.create_sheet(_nome_aba(wb, "Tabela dinâmica"))
    linha = _titulo_aba(ws, "Tabela dinâmica")

    cfg = pivot.get("config") or {}
    linha = _secao(ws, "CONFIGURAÇÃO", linha)
    linha = _par(ws, "Linhas", ", ".join(cfg.get("linhas") or []) or "(nenhuma)", linha)
    linha = _par(ws, "Coluna", cfg.get("coluna") or "(nenhuma)", linha)
    linha = _par(ws, "Valor", cfg.get("valor") or "(contagem)", linha)
    linha = _par(
        ws,
        "Agregação",
        _ROTULO_AGREGACAO.get(cfg.get("agregacao"), cfg.get("agregacao") or ""),
        linha,
    )
    linha += 1

    colunas = pivot.get("colunas") or []
    registros = pivot.get("registros") or []
    inicio = linha
    linha = _tabela(ws, colunas, registros, linha)
    ws.freeze_panes = ws.cell(row=inicio + 1, column=1).coordinate
    _larguras(ws, colunas, registros)


# ---------------------------------------------------------------------------
# Abas 3..n — um gráfico por aba
# ---------------------------------------------------------------------------
def _cor(i: int) -> str:
    return PALETA[i % len(PALETA)]


def _pintar_series(gr, tipo: str) -> None:
    """Aplica a paleta do painel às séries (linha = traço; demais = preenchimento)."""
    for i, serie in enumerate(gr.series):
        cor = _cor(i)
        if tipo == "linha":
            serie.graphicalProperties = GraphicalProperties(
                ln=LineProperties(solidFill=cor, w=28000)  # ~2,2 pt, como no painel
            )
            serie.smooth = False
        else:
            serie.graphicalProperties = GraphicalProperties(solidFill=cor)


def _pintar_fatias(serie, n: int) -> None:
    """Pizza: uma cor por fatia (o Excel só colore por ponto de dados)."""
    serie.data_points = [
        DataPoint(idx=i, spPr=GraphicalProperties(solidFill=_cor(i))) for i in range(n)
    ]


def _montar_grafico(tipo: str, orientacao: str, titulo: str):
    if tipo == "linha":
        gr = LineChart()
        gr.style = 2
    elif tipo == "pizza":
        gr = PieChart()
        # Como no painel: o rótulo fica na fatia (categoria + %), sem legenda.
        gr.dataLabels = DataLabelList()
        gr.dataLabels.showCatName = True
        gr.dataLabels.showPercent = True
        gr.legend = None
    else:  # barra e treemap (achatado)
        gr = BarChart()
        # Tree map vira barras horizontais: os rótulos de hierarquia são longos.
        gr.type = "bar" if (tipo == "treemap" or orientacao == "h") else "col"
        gr.gapWidth = 40
    gr.title = titulo
    gr.height = 12
    gr.width = 26
    if gr.legend is not None:
        gr.legend.position = "b"
    return gr


def _aba_grafico(wb: Workbook, g: Dict[str, Any], indice: int) -> None:
    tipo = g.get("tipo") or "barra"
    rotulo_tipo = _ROTULO_TIPO.get(tipo, tipo)
    ws = wb.create_sheet(_nome_aba(wb, f"{indice}. {rotulo_tipo}"))

    titulo = g.get("titulo") or rotulo_tipo
    linha = _titulo_aba(ws, f"{rotulo_tipo} — {titulo}")

    # Configuração usada no painel (mesmos campos dos seletores da tela).
    cfg = g.get("config") or {}
    linha = _secao(ws, "CONFIGURAÇÃO", linha)
    for rotulo, chave in (
        ("Tempo (categoria)", "tempo"),
        ("Valores", "valores"),
        ("Orientação", "orientacao"),
        ("Grupos", "grupos"),
        ("Valor", "valor"),
        ("Detalhando", "detalhe"),
    ):
        if chave not in cfg or cfg.get(chave) in (None, "", []):
            continue
        v = cfg[chave]
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        elif chave == "orientacao":
            v = "Vertical" if v == "v" else "Horizontal"
        linha = _par(ws, rotulo, v, linha)
    if tipo == "treemap":
        linha = _par(
            ws,
            "Observação",
            "O Excel não tem tree map equivalente: a hierarquia foi achatada em "
            "barras horizontais, com os mesmos valores do painel.",
            linha,
        )
    linha += 1

    colunas = list(g.get("colunas") or [])
    registros = list(g.get("registros") or [])
    truncado = len(registros) > _MAX_PONTOS
    if truncado:
        registros = sorted(
            registros,
            key=lambda r: abs(_soma_numerica(r, colunas[1:])),
            reverse=True,
        )[:_MAX_PONTOS]
        linha = _par(
            ws,
            "Observação",
            f"Série com mais de {_MAX_PONTOS} categorias: o gráfico mostra as "
            f"{_MAX_PONTOS} de maior valor. Use a aba da tabela dinâmica para o total.",
            linha,
        )
        linha += 1

    linha_cabecalho = linha
    linha = _tabela(ws, colunas, registros, linha, autofiltro=False)
    _larguras(ws, colunas, registros)

    if len(colunas) < 2 or not registros:
        _par(ws, "Sem dados", "o gráfico não pôde ser montado (série vazia).", linha)
        return

    linha_fim = linha_cabecalho + len(registros)
    gr = _montar_grafico(tipo, (cfg.get("orientacao") or "v"), titulo)
    dados_ref = Reference(
        ws, min_col=2, max_col=len(colunas), min_row=linha_cabecalho, max_row=linha_fim
    )
    categorias = Reference(ws, min_col=1, min_row=linha_cabecalho + 1, max_row=linha_fim)
    gr.add_data(dados_ref, titles_from_data=True)
    gr.set_categories(categorias)

    if isinstance(gr, PieChart):
        if gr.series:
            _pintar_fatias(gr.series[0], len(registros))
    else:
        _pintar_series(gr, tipo)

    # Ancorado à direita da tabela, para não cobrir os dados.
    ancora = f"{get_column_letter(len(colunas) + 2)}{linha_cabecalho}"
    ws.add_chart(gr, ancora)


def _soma_numerica(registro: Dict[str, Any], colunas: List[str]) -> float:
    total = 0.0
    for c in colunas:
        v = registro.get(c)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            total += float(v)
    return total


# ---------------------------------------------------------------------------
# Montagem da pasta de trabalho
# ---------------------------------------------------------------------------
def construir_workbook(dados: Dict[str, Any]) -> Workbook:
    """
    Monta a pasta de trabalho a partir do "estado do painel" enviado pelo
    navegador (ver painel.js -> exportarPastaTrabalho), acrescido do pedido da
    pesquisa inicial recuperado no servidor.
    """
    wb = Workbook()
    wb.remove(wb.active)  # a aba padrão é substituída pelas nossas

    _aba_filtros(wb, dados)
    _aba_pivot(wb, dados.get("pivot") or {})
    for i, g in enumerate(dados.get("graficos") or [], start=1):
        _aba_grafico(wb, g, i)

    return wb


def exportar_xlsx(dados: Dict[str, Any], caminho: Optional[str] = None) -> Any:
    """
    Gera a pasta de trabalho. Com `caminho`, salva e devolve o caminho; sem ele,
    devolve os bytes (para download via web).
    """
    wb = construir_workbook(dados)
    if caminho:
        wb.save(caminho)
        return caminho
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def nome_arquivo(dados: Dict[str, Any]) -> str:
    """Nome sugerido do arquivo: painel_<titulo>_<faixa de anos>.xlsx."""
    titulo = str(dados.get("titulo") or "painel").lower()
    titulo = "".join(ch if ch.isalnum() else "_" for ch in titulo).strip("_") or "painel"
    anos = [str(a) for a in (dados.get("anos") or [])]
    faixa = f"{min(anos)}-{max(anos)}" if anos else "sem_ano"
    return f"painel_{titulo}_{faixa}.xlsx"
