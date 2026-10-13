// painel_graficos.js — gráficos do painel (amCharts 5).
// Tipos: linhas, barras (V/H), tree map (até 2 níveis, drill), pizza (até 2, drill).
// Até 3 de cada. Operam sobre os dados filtrados/atualizados do painel.
// A agregação é pura (testável em Node); o rendering exige o amCharts (navegador).

// ---------- utilidades puras (testáveis) ----------
function _num(v) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return v;
  let t = String(v).replace(/R\$/g, "").replace(/\s/g, "");
  if (t.includes(",") && t.includes(".")) t = t.replace(/\./g, "").replace(",", ".");
  else if (t.includes(",")) t = t.replace(",", ".");
  const n = parseFloat(t);
  return Number.isNaN(n) ? null : n;
}
function _round(n) { return Math.round(n * 100) / 100; }
function _str(v) { return v === null || v === undefined ? "" : String(v); }
function _soma(regs, campo) { return _round(regs.reduce((a, r) => a + (_num(r[campo]) || 0), 0)); }

// Linhas/barras: soma de cada campo de valor por categoria de tempo.
function agregarTempo(dados, campoTempo, camposValor) {
  const cats = [...new Set(dados.map((r) => _str(r[campoTempo])))].sort();
  return cats.map((cat) => {
    const sub = dados.filter((r) => _str(r[campoTempo]) === cat);
    const linha = { cat };
    for (const v of camposValor) linha[v] = _soma(sub, v);
    return linha;
  });
}

// Tree map: hierarquia {name, value|children} com 1 ou 2 níveis de agrupamento.
function hierarquia(dados, grupos, valor) {
  function agrupa(regs, nivel) {
    const mapa = new Map();
    for (const r of regs) {
      const k = _str(r[grupos[nivel]]);
      if (!mapa.has(k)) mapa.set(k, []);
      mapa.get(k).push(r);
    }
    const filhos = [];
    for (const [k, sub] of mapa) {
      if (nivel + 1 < grupos.length) filhos.push({ name: k, children: agrupa(sub, nivel + 1) });
      else filhos.push({ name: k, value: _soma(sub, valor) });
    }
    return filhos;
  }
  return agrupa(dados, 0);
}

// Achata a hierarquia do tree map em linhas "Grupo 1 / Grupo 2" -> valor.
// Usada na exportação: o Excel não tem tree map nativo, então a hierarquia
// vira barras horizontais preservando os valores exibidos.
function achatarHierarquia(nos, prefixo) {
  const linhas = [];
  for (const no of nos || []) {
    const caminho = prefixo ? `${prefixo} / ${no.name}` : no.name;
    if (no.children && no.children.length) linhas.push(...achatarHierarquia(no.children, caminho));
    else linhas.push({ caminho, valor: no.value });
  }
  return linhas;
}

// Pizza: soma por um grupo (drill filtra por grupo1 e agrega por grupo2).
function agregarPorGrupo(dados, grupo, valor) {
  const mapa = new Map();
  for (const r of dados) {
    const k = _str(r[grupo]);
    mapa.set(k, (mapa.get(k) || []).concat([r]));
  }
  return [...mapa.entries()].map(([name, sub]) => ({ name, value: _soma(sub, valor) }));
}

// ============================================================
// A partir daqui: interface + amCharts (só no navegador).
// ============================================================
if (typeof document !== "undefined") {
  const LIMITE = 3;
  const contagem = { linha: 0, barra: 0, treemap: 0, pizza: 0 };
  const graficos = [];

  const temAm5 = () => typeof am5 !== "undefined";
  const temExport = () => typeof am5plugins_exporting !== "undefined";

  // Paleta categórica institucional, validada para daltonismo sobre fundo
  // branco (ΔE CVD adjacente 11.5; visão normal 26.2). A ORDEM é o mecanismo
  // de segurança: não reordene nem acrescente uma 9ª cor sem revalidar.
  // Espelhada em exportacao_painel.PALETA — mude os dois juntos.
  const PALETA = [0x1a6bb5, 0xe2691f, 0x0f9c8a, 0xc33a35, 0xe0a800, 0x7a5cc4, 0x0b7a3b, 0xd4548c];
  const cores = (root) => PALETA.map((c) => am5.color(c));

  // Cromo do gráfico: recessivo, uma casa acima da superfície.
  const GRADE = 0xe4e9f0;
  const TINTA_EIXO = 0x64748b;

  function novaRaiz(divId) {
    const root = am5.Root.new(divId);
    root.setThemes([am5themes_Animated.new(root)]);
    if (typeof am5locales_pt_BR !== "undefined") root.locale = am5locales_pt_BR;
    root.numberFormatter.set("numberFormat", "#,###.##");
    return root;
  }

  function ativarExport(root, botao) {
    if (!temExport()) { botao.disabled = true; botao.title = "Plugin de exportação não carregou"; return; }
    const exporting = am5plugins_exporting.Exporting.new(root, { filePrefix: "grafico" });
    botao.disabled = false;
    botao.onclick = async () => {
      botao.disabled = true;
      try {
        const uri = await exporting.export("png");   // data URI base64
        const a = document.createElement("a");
        a.href = uri;
        a.download = "grafico.png";
        document.body.appendChild(a);
        a.click();
        a.remove();
      } catch (e) {
        console.error("Falha ao exportar:", e);
        alert("Não foi possível exportar a imagem.");
      } finally {
        botao.disabled = false;
      }
    };
  }

  function selColunas(sel, colunas, incluirVazio) {
    const opts = colunas.map((c) => `<option value="${c}">${c}</option>`).join("");
    sel.innerHTML = (incluirVazio ? '<option value="">(nenhuma)</option>' : "") + opts;
  }
  function novoDiv(cls) { const d = document.createElement("div"); if (cls) d.className = cls; return d; }

  // Nome de coluna livre de colisão (ex.: campo de tempo que também é valor).
  function chaveUnica(base, usadas) {
    let nome = base;
    let n = 2;
    while (usadas.includes(nome)) nome = `${base} (${n++})`;
    return nome;
  }

  function rotulo(texto, controle) {
    const l = document.createElement("label");
    l.className = "grafico-rot"; l.textContent = texto; l.appendChild(controle);
    return l;
  }

  function criarGrafico(tipo) {
    if (contagem[tipo] >= LIMITE) return;
    contagem[tipo] += 1;
    const colunas = window.PAINEL.getColunas();
    const monetarias = colunas.filter((c) => /vlr|valor/i.test(c));
    const tempoPadrao = colunas.includes("_ano_consulta") ? "_ano_consulta" : colunas[0];

    const card = novoDiv("grafico-card");
    const topo = novoDiv("grafico-topo");
    const cfg = novoDiv("grafico-cfg");
    const barra = novoDiv("grafico-barra");
    const alvo = novoDiv("grafico-area");
    alvo.id = `grafico-${tipo}-${contagem[tipo]}-${Date.now()}`;

    const btnVoltar = document.createElement("button");
    btnVoltar.className = "btn-sec"; btnVoltar.textContent = "\u25c0 Voltar"; btnVoltar.style.display = "none";
    const btnPng = document.createElement("button");
    btnPng.className = "btn-sec"; btnPng.textContent = "Exportar PNG";
    const remover = document.createElement("button");
    remover.className = "btn-sec"; remover.textContent = "Remover";
    barra.append(btnVoltar, btnPng, remover);

    let ler;
    if (tipo === "linha" || tipo === "barra") {
      const selTempo = document.createElement("select");
      const selValores = document.createElement("select");
      selValores.multiple = true; selValores.size = 3;
      selColunas(selTempo, colunas, false);
      selColunas(selValores, colunas, false);
      selTempo.value = tempoPadrao;
      [...selValores.options].forEach((o) => { if (monetarias.includes(o.value)) o.selected = true; });
      cfg.append(rotulo("Tempo", selTempo), rotulo("Valores", selValores));
      let selOrient = null;
      if (tipo === "barra") {
        selOrient = document.createElement("select");
        selOrient.innerHTML = '<option value="v">Vertical</option><option value="h">Horizontal</option>';
        cfg.append(rotulo("Orientação", selOrient));
      }
      ler = () => ({
        tempo: selTempo.value,
        valores: [...selValores.selectedOptions].map((o) => o.value),
        orientacao: selOrient ? selOrient.value : "v",
      });
      [selTempo, selValores, selOrient].forEach((sl) => sl && sl.addEventListener("change", () => item.renderizar()));
    } else {
      const selG1 = document.createElement("select");
      const selG2 = document.createElement("select");
      const selValor = document.createElement("select");
      selColunas(selG1, colunas, false);
      selColunas(selG2, colunas, true);
      selColunas(selValor, colunas, false);
      // Seleção inicial do grupo 1: o ano, não o nº do empenho (evita milhares
      // de grupos, que atrasam o carregamento e poluem a visualização).
      selG1.value = colunas.includes("_ano_consulta") ? "_ano_consulta" : colunas[0];
      selValor.value = monetarias[0] || colunas[0];
      cfg.append(rotulo("Grupo 1", selG1), rotulo("Grupo 2 (opcional)", selG2), rotulo("Valor", selValor));
      ler = () => ({ grupos: [selG1.value].concat(selG2.value ? [selG2.value] : []), valor: selValor.value });
      [selG1, selG2, selValor].forEach((sl) => sl.addEventListener("change", () => item.renderizar()));
    }

    topo.append(cfg, barra);
    card.append(topo, alvo);
    document.getElementById("graficos").appendChild(card);

    const item = {
      tipo, root: null,
      renderizar() {
        const dados = window.PAINEL.getDados();
        if (this.root) { this.root.dispose(); this.root = null; }
        btnVoltar.style.display = "none"; btnVoltar.onclick = null;
        // `exportacao` guarda os dados agregados desta renderização, para a
        // pasta de trabalho (uma aba por gráfico) montada no servidor.
        this.exportacao = null;
        if (!temAm5()) { alvo.innerHTML = '<p class="placeholder">amCharts não carregou (verifique acesso à CDN).</p>'; btnPng.disabled = true; return; }
        const ctx = { alvo, btnVoltar, btnPng, registrar: (info) => { item.exportacao = info; } };
        try {
          if (tipo === "linha") this.root = renderXY(dados, ler(), false, ctx);
          else if (tipo === "barra") this.root = renderXY(dados, ler(), true, ctx);
          else if (tipo === "treemap") this.root = renderTreemap(dados, ler(), ctx);
          else if (tipo === "pizza") this.root = renderPizza(dados, ler(), ctx);
          if (this.root) ativarExport(this.root, btnPng);
        } catch (e) { alvo.innerHTML = `<p class="placeholder">Erro no gráfico: ${e.message}</p>`; }
      },
    };
    remover.addEventListener("click", () => {
      if (item.root) item.root.dispose();
      card.remove();
      contagem[tipo] -= 1;
      const i = graficos.indexOf(item); if (i >= 0) graficos.splice(i, 1);
      atualizarVazio();
    });
    graficos.push(item);
    item.renderizar();
    atualizarVazio();
  }

  function atualizarVazio() {
    const vazio = document.getElementById("graficos-vazio");
    if (vazio) vazio.hidden = graficos.length > 0;
    // Desabilita o botão do tipo que já atingiu o limite de 3.
    document.querySelectorAll(".grafico-add button").forEach((b) => {
      b.disabled = contagem[b.dataset.tipo] >= LIMITE;
    });
  }

  // ---------- rendering amCharts 5 ----------
  function renderXY(dados, cfg, barras, ctx) {
    const root = novaRaiz(ctx.alvo.id);
    const horizontal = barras && cfg.orientacao === "h";
    const chart = root.container.children.push(
      am5xy.XYChart.new(root, { panX: false, panY: false, wheelX: "none", wheelY: "none",
        paddingLeft: 8, paddingRight: 16, layout: root.verticalLayout })
    );
    chart.set("colors", am5.ColorSet.new(root, { colors: cores(root), reuse: false }));
    const data = agregarTempo(dados, cfg.tempo, cfg.valores);

    // Eixos e grade recessivos: hairline sólido, sem linha de categoria.
    function vestirEixo(eixo, comGrade) {
      const r = eixo.get("renderer");
      r.grid.template.setAll({ stroke: am5.color(GRADE), strokeWidth: 1, strokeOpacity: comGrade ? 1 : 0 });
      r.labels.template.setAll({ fill: am5.color(TINTA_EIXO), fontSize: 11.5 });
      r.setAll({ strokeOpacity: 0 });
      return eixo;
    }

    let eixoCat, eixoVal;
    if (horizontal) {
      eixoCat = chart.yAxes.push(am5xy.CategoryAxis.new(root, { categoryField: "cat", renderer: am5xy.AxisRendererY.new(root, { minGridDistance: 18 }) }));
      eixoVal = chart.xAxes.push(am5xy.ValueAxis.new(root, { min: 0, renderer: am5xy.AxisRendererX.new(root, {}) }));
    } else {
      eixoCat = chart.xAxes.push(am5xy.CategoryAxis.new(root, { categoryField: "cat", renderer: am5xy.AxisRendererX.new(root, { minGridDistance: 40 }) }));
      eixoVal = chart.yAxes.push(am5xy.ValueAxis.new(root, { min: 0, renderer: am5xy.AxisRendererY.new(root, {}) }));
    }
    vestirEixo(eixoCat, false);   // categoria não precisa de grade
    vestirEixo(eixoVal, true);
    eixoCat.data.setAll(data);

    for (const v of cfg.valores) {
      const cls = barras ? am5xy.ColumnSeries : am5xy.LineSeries;
      const opts = horizontal
        ? { name: v, xAxis: eixoVal, yAxis: eixoCat, valueXField: v, categoryYField: "cat" }
        : { name: v, xAxis: eixoCat, yAxis: eixoVal, valueYField: v, categoryXField: "cat" };
      opts.tooltip = am5.Tooltip.new(root, { labelText: "{name}: {valueX}{valueY}" });
      const series = chart.series.push(cls.new(root, opts));
      if (!barras) {
        // Linha 2px; marcador >= 8px com anel de 2px na cor da superfície,
        // para continuar legível onde as séries se cruzam.
        series.strokes.template.setAll({ strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" });
        series.bullets.push(() =>
          am5.Bullet.new(root, {
            sprite: am5.Circle.new(root, {
              radius: 4, fill: series.get("fill"),
              stroke: am5.color(0xffffff), strokeWidth: 2,
            }),
          })
        );
      } else {
        // Barra fina com ponta arredondada e quadrada na linha de base; o vão
        // entre barras vizinhas é a superfície fazendo a separação.
        // A espessura é limitada SÓ no eixo transversal: no eixo do valor a
        // barra precisa crescer livre (limitar ali vira um quadrado flutuante).
        const forma = horizontal
          ? { cornerRadiusTR: 4, cornerRadiusBR: 4, cornerRadiusTL: 0, cornerRadiusBL: 0,
              height: am5.percent(62), maxHeight: 24 }
          : { cornerRadiusTL: 4, cornerRadiusTR: 4, cornerRadiusBL: 0, cornerRadiusBR: 0,
              width: am5.percent(62), maxWidth: 24 };
        series.columns.template.setAll({ ...forma, strokeOpacity: 0 });
      }
      series.data.setAll(data);
      series.appear(600);
    }
    chart.set("cursor", am5xy.XYCursor.new(root, { behavior: "none" }));
    // Legenda sempre presente a partir de 2 séries: identidade nunca depende
    // só da cor. Com uma série só, o título do card já diz o que está plotado.
    if (cfg.valores.length > 1) {
      const legenda = chart.children.push(
        am5.Legend.new(root, { centerX: am5.p50, x: am5.p50, marginTop: 14 })
      );
      legenda.labels.template.setAll({ fontSize: 12, fill: am5.color(0x334155) });
      legenda.markers.template.setAll({ width: 12, height: 12 });
      legenda.data.setAll(chart.series.values);
    }

    const colCat = chaveUnica(cfg.tempo, cfg.valores);
    ctx.registrar({
      tipo: barras ? "barra" : "linha",
      titulo: `${cfg.valores.join(", ")} por ${cfg.tempo}`,
      config: { tempo: cfg.tempo, valores: cfg.valores, orientacao: cfg.orientacao },
      colunas: [colCat, ...cfg.valores],
      registros: data.map((d) => {
        const linha = { [colCat]: d.cat };
        for (const v of cfg.valores) linha[v] = d[v];
        return linha;
      }),
    });
    return root;
  }

  function renderTreemap(dados, cfg, ctx) {
    const root = novaRaiz(ctx.alvo.id);
    const container = root.container.children.push(am5.Container.new(root, { width: am5.p100, height: am5.p100, layout: root.verticalLayout }));
    const series = container.children.push(
      am5hierarchy.Treemap.new(root, {
        downDepth: 1, initialDepth: cfg.grupos.length > 1 ? 1 : 0, topDepth: 0,
        valueField: "value", categoryField: "name", childDataField: "children",
        nodePaddingOuter: 3, nodePaddingInner: 2,
      })
    );
    series.get("colors").set("colors", cores(root));
    // Sem contorno: quem separa os blocos é o vão da superfície (nodePadding),
    // não um traço em volta da marca.
    series.rectangles.template.setAll({
      cornerRadiusTL: 4, cornerRadiusTR: 4, cornerRadiusBL: 4, cornerRadiusBR: 4,
      strokeOpacity: 0,
    });
    series.labels.template.setAll({ fontSize: 12, fill: am5.color(0xffffff), oversizedBehavior: "fit" });
    const filhos = hierarquia(dados, cfg.grupos, cfg.valor);
    const data = [{ name: "Total", children: filhos }];
    series.data.setAll(data);
    series.set("selectedDataItem", series.dataItems[0]);

    if (cfg.grupos.length > 1) {
      ctx.btnVoltar.style.display = "";
      ctx.btnVoltar.onclick = () => series.set("selectedDataItem", series.dataItems[0]);
    }

    const colCat = chaveUnica(cfg.grupos.join(" / "), [cfg.valor]);
    ctx.registrar({
      tipo: "treemap",
      titulo: `${cfg.valor} por ${cfg.grupos.join(" / ")}`,
      config: { grupos: cfg.grupos, valor: cfg.valor },
      colunas: [colCat, cfg.valor],
      registros: achatarHierarquia(filhos, "").map((l) => ({
        [colCat]: l.caminho,
        [cfg.valor]: l.valor,
      })),
    });
    return root;
  }

  function renderPizza(dados, cfg, ctx) {
    const root = novaRaiz(ctx.alvo.id);
    const chart = root.container.children.push(am5percent.PieChart.new(root, { layout: root.verticalLayout }));
    const series = chart.series.push(am5percent.PieSeries.new(root, { valueField: "value", categoryField: "name" }));
    series.get("colors").set("colors", cores(root));
    series.slices.template.setAll({ stroke: am5.color(0xffffff), strokeWidth: 2 });
    series.labels.template.setAll({ fontSize: 12, text: "{category}" });
    series.slices.template.set("tooltipText", "{category}: {value} ({valuePercentTotal.formatNumber('0.0')}%)");

    const [g1, g2] = cfg.grupos;
    let filtroG1 = null;

    function atualizar() {
      let grupoAtual = g1;
      let agregado;
      if (g2 && filtroG1 !== null) {
        const sub = dados.filter((r) => _str(r[g1]) === filtroG1);
        grupoAtual = g2;
        agregado = agregarPorGrupo(sub, g2, cfg.valor);
        series.data.setAll(agregado);
        titulo.set("text", `${g1}: ${filtroG1}  →  ${g2}`);
        ctx.btnVoltar.style.display = "";
      } else {
        agregado = agregarPorGrupo(dados, g1, cfg.valor);
        series.data.setAll(agregado);
        titulo.set("text", "");
        ctx.btnVoltar.style.display = "none";
      }
      // Exporta o que está VISÍVEL agora (respeita o drill aplicado na tela).
      const colCat = chaveUnica(grupoAtual, [cfg.valor]);
      ctx.registrar({
        tipo: "pizza",
        titulo: `${cfg.valor} por ${grupoAtual}`,
        config: {
          grupos: cfg.grupos,
          valor: cfg.valor,
          detalhe: filtroG1 !== null ? `${g1}: ${filtroG1}` : "",
        },
        colunas: [colCat, cfg.valor],
        registros: agregado.map((d) => ({ [colCat]: d.name, [cfg.valor]: d.value })),
      });
    }

    const titulo = chart.children.unshift(am5.Label.new(root, { text: "", fontSize: 13, fontWeight: "600", x: am5.p50, centerX: am5.p50 }));
    ctx.btnVoltar.onclick = () => { filtroG1 = null; atualizar(); };
    if (g2) {
      series.slices.template.set("cursorOverStyle", "pointer");
      series.slices.template.events.on("click", (ev) => {
        if (filtroG1 !== null) return;
        filtroG1 = ev.target.dataItem.get("category");
        atualizar();
      });
    }
    series.appear(600);
    atualizar();
    return root;
  }

  // ---------- ligação ----------
  document.querySelectorAll(".grafico-add button").forEach((b) => {
    b.addEventListener("click", () => criarGrafico(b.dataset.tipo));
  });
  atualizarVazio();
  window.PAINEL.aoAtualizar(() => graficos.forEach((g) => g.renderizar()));

  // Consumido por painel.js na exportação da pasta de trabalho: os dados
  // agregados de cada gráfico, na ordem em que aparecem na tela.
  window.PAINEL_GRAFICOS = {
    estado() {
      return graficos.map((g) => g.exportacao).filter(Boolean);
    },
  };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { agregarTempo, hierarquia, agregarPorGrupo, achatarHierarquia };
}
