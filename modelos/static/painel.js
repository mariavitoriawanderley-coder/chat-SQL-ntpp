// painel.js — filtros + tabela dinâmica + atualização pela inflação (IPCA).
// Opera sobre o resultado da pesquisa principal (em cache no servidor), obtido
// pelo token na URL. Filtros e pivot são calculados no navegador.

const TOKEN = typeof window !== "undefined" ? window.PAINEL_TOKEN : null;

let ORIGINAIS = [];        // registros originais
let DADOS = [];            // registros "efetivos" (com/sem IPCA)
let COLUNAS = [];
let ANOS = [];
let CAMPO_NE = null;
let COLS_MONETARIAS = [];
let FATORES_IPCA = null;
const FILTROS = {};        // coluna -> {tipo:'valores', set:Set} | {tipo:'texto', texto:string}

const FONTES = {
  portal_transparencia: "Portal da Transparência de PE",
  dados_abertos_tce: "Dados Abertos do TCE-PE",
};

// Coluna criada por pesquisa.py para separar a execução do exercício dos
// empenhos inscritos em restos a pagar (só existe no Portal).
const COL_EXERCICIO = "exercicio";
const EXERCICIO_RP = "Restos a pagar";

// ---------- utilidades ----------
function ehMonetaria(col) { return /vlr|valor/i.test(col); }

function faixaAnos(anos) {
  const ord = [...anos].map(Number).sort((a, b) => a - b);
  return ord[0] === ord[ord.length - 1] ? String(ord[0]) : `${ord[0]}–${ord[ord.length - 1]}`;
}

function parseNumero(v) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return v;
  let t = String(v).replace(/R\$/g, "").replace(/\s/g, "");
  if (t.includes(",") && t.includes(".")) t = t.replace(/\./g, "").replace(",", ".");
  else if (t.includes(",")) t = t.replace(",", ".");
  const n = parseFloat(t);
  return Number.isNaN(n) ? null : n;
}

function anoDaLinha(row) {
  if (row._ano_consulta) return String(row._ano_consulta);
  if (CAMPO_NE && row[CAMPO_NE]) return String(row[CAMPO_NE]).slice(0, 4);
  return "";
}

function distintos(col) {
  const s = new Set();
  for (const r of ORIGINAIS) s.add(r[col] === null || r[col] === undefined ? "" : String(r[col]));
  return [...s].sort();
}

function numero(n) { return Number(n || 0).toLocaleString("pt-BR"); }
function plural(n, um, varios) { return `${n} ${n === 1 ? um : varios}`; }
function texto(id, valor) { document.getElementById(id).textContent = valor; }

// ---------- carregamento ----------
async function iniciar() {
  const resp = await fetch(`/api/resultado/${TOKEN}`);
  if (!resp.ok) {
    const e = await resp.json().catch(() => ({}));
    return mostrarErro(e.erro || "Não foi possível carregar o resultado.");
  }
  const d = await resp.json();
  ORIGINAIS = d.registros || [];
  COLUNAS = d.colunas || [];
  ANOS = d.anos || [];
  CAMPO_NE = d.campo_ne;
  COLS_MONETARIAS = COLUNAS.filter(ehMonetaria);
  DADOS = ORIGINAIS;

  const rotuloFonte = FONTES[d.fonte] || d.fonte || "";
  texto("titulo-painel", d.titulo || "Painel de Empenhos");
  texto("resumo", `${numero(ORIGINAIS.length)} linhas · ${rotuloFonte}`);

  // Resultado grande: o painel abre com um recorte (a planilha vem inteira).
  if (d.truncado) {
    const av = document.getElementById("aviso-painel");
    av.hidden = false;
    av.textContent =
      `⚠️ Resultado extenso: o painel está mostrando as primeiras ` +
      `${numero(ORIGINAIS.length)} linhas de ${numero(d.total_registros)}. ` +
      `A planilha .xlsx baixada contém todas as linhas.`;
  }

  // Restos a pagar (só o Portal identifica): indicador próprio.
  const rp = ORIGINAIS.filter((r) => r[COL_EXERCICIO] === EXERCICIO_RP).length;
  if (COLUNAS.includes(COL_EXERCICIO)) {
    document.getElementById("kpi-rp-caixa").hidden = false;
    texto("kpi-rp", numero(rp));
    texto("kpi-rp-nota", `${numero(ORIGINAIS.length - rp)} do exercício`);
  }
  texto("kpi-colunas", numero(COLUNAS.length));
  texto("kpi-periodo", ANOS.length ? faixaAnos(ANOS) : "—");
  texto("kpi-fonte", rotuloFonte);
  if (d.titulo) document.title = `Painel — ${d.titulo}`;
  document.getElementById("carregando").hidden = true;
  document.getElementById("area").hidden = false;

  montarFiltros();
  montarControlesPivot();
  ligarEventos();
  aplicar();
}

function mostrarErro(msg) {
  document.getElementById("carregando").hidden = true;
  const el = document.getElementById("erro");
  el.hidden = false;
  el.textContent = "⚠️ " + msg;
}

// ---------- filtros ----------
const LIMITE_RENDER = 300;

function montarFiltros() {
  const cont = document.getElementById("filtros");
  cont.innerHTML = "";
  for (const col of COLUNAS) {
    const valores = distintos(col);
    const div = document.createElement("div");
    div.className = "filtro";

    const topo = document.createElement("div");
    topo.className = "filtro-topo";
    const nome = document.createElement("span");
    nome.className = "filtro-nome";
    nome.textContent = col;
    nome.title = `${col} — ${plural(valores.length, "valor distinto", "valores distintos")}`;
    const tag = document.createElement("span");
    tag.className = "filtro-tag";
    tag.hidden = true;
    topo.append(nome, tag);
    div.appendChild(topo);

    const busca = document.createElement("input");
    busca.type = "text";
    busca.className = "filtro-busca";
    busca.placeholder = `buscar entre ${valores.length}…`;
    busca.setAttribute("aria-label", `Buscar em ${col}`);
    div.appendChild(busca);

    // Ações do filtro: aparecem quando o usuário entra no campo de busca.
    // Agem sobre os valores À VISTA — com uma busca digitada, "marcar todos"
    // marca exatamente o que está listado, que é o uso natural.
    const acoes = document.createElement("div");
    acoes.className = "filtro-acoes";
    acoes.hidden = true;
    const btnTodos = document.createElement("button");
    btnTodos.type = "button";
    btnTodos.className = "btn-link";
    const visiveis = document.createElement("span");
    visiveis.className = "filtro-visiveis";
    acoes.append(btnTodos, visiveis);
    div.appendChild(acoes);

    const wrap = document.createElement("div");
    wrap.className = "filtro-valores";
    div.appendChild(wrap);

    const marcados = () => (FILTROS[col] && FILTROS[col].set) || new Set();
    let listaAtual = [];

    function atualizarAcoes() {
      const set = marcados();
      const total = listaAtual.length;
      const todosMarcados = total > 0 && listaAtual.every((v) => set.has(v));
      btnTodos.textContent = todosMarcados ? "Desmarcar todos" : "Marcar todos";
      btnTodos.disabled = total === 0;
      visiveis.textContent = total ? plural(total, "valor à vista", "valores à vista") : "digite para buscar";
      // Selo com a contagem de selecionados no cabeçalho do filtro.
      tag.hidden = set.size === 0;
      tag.textContent = set.size;
      div.classList.toggle("filtro-ativo", set.size > 0);
    }

    function render(termo) {
      wrap.innerHTML = "";
      const t = (termo || "").trim().toLowerCase();
      let lista = t ? valores.filter((v) => v.toLowerCase().includes(t)) : valores;

      // Muitos valores e sem busca: pede para digitar (mostra só os selecionados).
      if (!t && valores.length > LIMITE_RENDER) {
        const dica = document.createElement("div");
        dica.className = "filtro-dica";
        dica.textContent = `Digite para buscar entre ${valores.length} valores.`;
        wrap.appendChild(dica);
        lista = [...marcados()];
      } else if (lista.length > LIMITE_RENDER) {
        lista = lista.slice(0, LIMITE_RENDER);
      }
      listaAtual = lista;

      const set = marcados();
      for (const v of lista) {
        const lab = document.createElement("label");
        lab.title = v || "(vazio)";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = v;
        cb.checked = set.has(v);
        cb.addEventListener("change", () => {
          const s = marcados();
          if (cb.checked) s.add(v); else s.delete(v);
          FILTROS[col] = s.size ? { tipo: "valores", set: s } : undefined;
          atualizarAcoes();
          aplicar();
        });
        lab.appendChild(cb);
        lab.appendChild(document.createTextNode(" " + (v || "(vazio)")));
        wrap.appendChild(lab);
      }
      atualizarAcoes();
    }

    // mousedown antes do click: sem isto o botão perderia o foco da busca e
    // sumiria (focusout) antes do clique chegar.
    btnTodos.addEventListener("mousedown", (e) => e.preventDefault());
    btnTodos.addEventListener("click", () => {
      const s = marcados();
      const todosMarcados = listaAtual.length > 0 && listaAtual.every((v) => s.has(v));
      for (const v of listaAtual) {
        if (todosMarcados) s.delete(v); else s.add(v);
      }
      FILTROS[col] = s.size ? { tipo: "valores", set: s } : undefined;
      render(busca.value);
      aplicar();
    });

    busca.addEventListener("focus", () => { acoes.hidden = false; atualizarAcoes(); });
    div.addEventListener("focusout", (e) => {
      if (div.contains(e.relatedTarget)) return;   // foco ainda dentro do filtro
      if (busca.value.trim()) return;              // busca em andamento: mantém à vista
      acoes.hidden = true;
    });
    busca.addEventListener("input", () => { acoes.hidden = false; render(busca.value); });

    render("");
    cont.appendChild(div);
  }
}

// Chips dos filtros ativos: com dezenas de colunas, é o único jeito de ver
// num relance o que está filtrado sem varrer a grade toda.
function renderChips() {
  const cont = document.getElementById("filtros-ativos");
  const ativos = Object.keys(FILTROS).filter((c) => FILTROS[c]);
  cont.innerHTML = "";
  cont.hidden = ativos.length === 0;
  for (const col of ativos) {
    const set = FILTROS[col].set;
    const lista = [...set];
    const chip = document.createElement("span");
    chip.className = "chip";
    const rot = document.createElement("span");
    rot.className = "chip-txt";
    const resumo = lista.length <= 2
      ? lista.map((v) => v || "(vazio)").join(", ")
      : plural(lista.length, "valor", "valores");
    rot.innerHTML = "";
    const b = document.createElement("b");
    b.textContent = col;
    rot.append(b, document.createTextNode(": " + resumo));
    rot.title = lista.map((v) => v || "(vazio)").join(", ");
    const x = document.createElement("button");
    x.className = "chip-x";
    x.type = "button";
    x.textContent = "×";
    x.title = `Remover o filtro de ${col}`;
    x.setAttribute("aria-label", `Remover o filtro de ${col}`);
    x.addEventListener("click", () => {
      delete FILTROS[col];
      montarFiltros();
      aplicar();
    });
    chip.append(rot, x);
    cont.appendChild(chip);
  }
}

function passaFiltros(row) {
  for (const col of Object.keys(FILTROS)) {
    const f = FILTROS[col];
    if (!f) continue;
    const val = row[col] === null || row[col] === undefined ? "" : String(row[col]);
    if (f.tipo === "valores" && !f.set.has(val)) return false;
    if (f.tipo === "texto" && !val.toLowerCase().includes(f.texto)) return false;
  }
  return true;
}

// ---------- pivot (mesma semântica de pivot.py) ----------
function metrica(regs, valor, agg) {
  if (agg === "contagem") return regs.length;
  const brutos = valor ? regs.map((r) => r[valor]) : [];
  if (agg === "contagem_distinta") return new Set(brutos.filter((v) => v !== null && v !== undefined && v !== "")).size;
  const nums = brutos.map(parseNumero).filter((n) => n !== null);
  if (agg === "media") return nums.length ? arredonda(nums.reduce((a, b) => a + b, 0) / nums.length) : 0;
  return arredonda(nums.reduce((a, b) => a + b, 0));
}
function arredonda(n) { return Math.round(n * 100) / 100; }
function nomeMetrica(valor, agg) { return agg === "contagem" ? "contagem" : (valor ? `${agg}(${valor})` : agg); }

function construirPivot(regs, linhas, coluna, valor, agg) {
  const grupos = new Map();
  for (const r of regs) {
    const chave = linhas.map((c) => (r[c] === null || r[c] === undefined ? "" : String(r[c]))).join("\u0001");
    if (!grupos.has(chave)) grupos.set(chave, []);
    grupos.get(chave).push(r);
  }
  if (coluna) {
    const valsCol = [];
    for (const r of regs) {
      const cv = r[coluna] === null || r[coluna] === undefined ? "" : String(r[coluna]);
      if (!valsCol.includes(cv)) valsCol.push(cv);
    }
    const cols = [...linhas, ...valsCol, "Total"];
    const saida = [];
    for (const [chave, gregs] of grupos) {
      const partes = chave.split("\u0001");
      const linha = {};
      linhas.forEach((c, i) => (linha[c] = partes[i]));
      for (const cv of valsCol) {
        const cel = gregs.filter((r) => (r[coluna] === null || r[coluna] === undefined ? "" : String(r[coluna])) === cv);
        linha[cv] = metrica(cel, valor, agg);
      }
      linha["Total"] = metrica(gregs, valor, agg);
      saida.push(linha);
    }
    return { registros: saida, colunas: cols };
  }
  const nome = nomeMetrica(valor, agg);
  const cols = [...linhas, nome];
  const saida = [];
  for (const [chave, gregs] of grupos) {
    const partes = chave.split("\u0001");
    const linha = {};
    linhas.forEach((c, i) => (linha[c] = partes[i]));
    linha[nome] = metrica(gregs, valor, agg);
    saida.push(linha);
  }
  return { registros: saida, colunas: cols };
}

function montarControlesPivot() {
  const opts = COLUNAS.map((c) => `<option value="${escapar(c)}">${escapar(c)}</option>`).join("");
  const selLinhas = document.getElementById("pv-linhas");
  const selValor = document.getElementById("pv-valor");
  selLinhas.innerHTML = opts;
  document.getElementById("pv-coluna").innerHTML = '<option value="">(nenhuma)</option>' + opts;
  selValor.innerHTML = '<option value="">(contagem)</option>' + opts;

  // Abre com uma tabela que já diz alguma coisa (soma do valor por ano), em vez
  // de uma linha vazia esperando configuração.
  const tempo = COLUNAS.includes("_ano_consulta") ? "_ano_consulta" : COLUNAS[0];
  [...selLinhas.options].forEach((o) => { o.selected = o.value === tempo; });
  const monetaria = COLUNAS.find(ehMonetaria);
  if (monetaria) selValor.value = monetaria;
}

let PIVOT_ATUAL = { registros: [], colunas: [] };
let PIVOT_CONFIG = { linhas: [], coluna: null, valor: null, agregacao: "soma" };

function gerarPivot() {
  const linhas = [...document.getElementById("pv-linhas").selectedOptions].map((o) => o.value);
  const coluna = document.getElementById("pv-coluna").value || null;
  const valor = document.getElementById("pv-valor").value || null;
  const agg = document.getElementById("pv-agg").value;
  const filtrados = DADOS.filter(passaFiltros);
  PIVOT_CONFIG = { linhas, coluna, valor, agregacao: agg };
  PIVOT_ATUAL = construirPivot(filtrados, linhas, coluna, valor, agg);
  renderTabela(PIVOT_ATUAL);
}

function renderTabela({ registros, colunas }) {
  const tab = document.getElementById("pivot");
  texto("pivot-sub", registros.length
    ? `${plural(registros.length, "linha", "linhas")} · ${plural(colunas.length, "coluna", "colunas")}`
    : "Escolha ao menos uma coluna em “Linhas” e clique em Gerar.");
  if (!registros.length) {
    tab.innerHTML = "";
    return;
  }
  const ehNum = (c) => /soma|contagem|media|total/i.test(c) || /^\d/.test(String(registros[0] && registros[0][c]));
  const thead = `<thead><tr>${colunas.map((c) => `<th class="${ehNum(c) ? "num" : ""}">${escapar(c)}</th>`).join("")}</tr></thead>`;
  const linhas = registros
    .map((r) => `<tr>${colunas.map((c) => `<td class="${typeof r[c] === "number" ? "num" : ""}">${escapar(formatar(r[c]))}</td>`).join("")}</tr>`)
    .join("");
  tab.innerHTML = thead + `<tbody>${linhas}</tbody>`;
}

// Os valores vêm da fonte pública e são injetados como HTML: escapa para que
// um campo com "<" não quebre nem injete nada na tabela.
function escapar(v) {
  return String(v === undefined || v === null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatar(v) {
  if (typeof v === "number") return v.toLocaleString("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  return v === undefined || v === null ? "" : v;
}

// ---------- IPCA ----------
async function aplicarIpca(ativo) {
  if (!ativo) { DADOS = ORIGINAIS; aplicar(); return; }
  if (!FATORES_IPCA) {
    const resp = await fetch(`/api/ipca?anos=${ANOS.join(",")}`);
    const d = await resp.json();
    if (!resp.ok) { mostrarErro(d.erro || "Falha ao obter IPCA."); return; }
    FATORES_IPCA = d.fatores || {};
  }
  DADOS = ORIGINAIS.map((row) => {
    const fator = FATORES_IPCA[anoDaLinha(row)] || 1.0;
    if (fator === 1.0) return row;
    const novo = { ...row };
    for (const col of COLS_MONETARIAS) {
      const n = parseNumero(row[col]);
      if (n !== null) novo[col] = arredonda(n * fator);
    }
    return novo;
  });
  aplicar();
}

// ---------- eventos / aplicação ----------
const _assinantes = [];
function _notificar(filtrados) {
  for (const cb of _assinantes) {
    try { cb(filtrados, COLUNAS); } catch (e) { console.error(e); }
  }
}

function aplicar() {
  const filtrados = DADOS.filter(passaFiltros);
  const ativos = Object.keys(FILTROS).filter((c) => FILTROS[c]).length;

  texto("kpi-exibidos", numero(filtrados.length));
  texto("kpi-total", filtrados.length === DADOS.length
    ? "todos os registros da pesquisa"
    : `de ${numero(DADOS.length)} registros`);
  texto("kpi-filtros", String(ativos));
  texto("kpi-filtros-nota", ativos ? plural(ativos, "coluna filtrada", "colunas filtradas") : "nenhum filtro");

  renderChips();
  gerarPivot();
  _notificar(filtrados);
}

function ligarEventos() {
  document.getElementById("gerar-pivot").addEventListener("click", gerarPivot);
  document.getElementById("ipca-toggle").addEventListener("change", (e) => aplicarIpca(e.target.checked));
  document.getElementById("baixar-pivot").addEventListener("click", baixarPivotCsv);
  const btnExportar = document.getElementById("exportar-tudo");
  btnExportar.disabled = false;   // só depois que os dados chegaram
  btnExportar.addEventListener("click", exportarPastaTrabalho);
  document.getElementById("limpar-filtros").addEventListener("click", () => {
    for (const k of Object.keys(FILTROS)) delete FILTROS[k];
    montarFiltros();
    aplicar();
  });
}

// ---------- exportação da pasta de trabalho (xlsx) ----------
// Reúne o estado da tela (filtros do painel, IPCA, tabela dinâmica e os dados
// já agregados de cada gráfico) e pede ao servidor a pasta de trabalho. Os
// filtros da PESQUISA INICIAL são recuperados no servidor, pelo token.
function estadoExportacao() {
  const filtros = Object.keys(FILTROS)
    .filter((c) => FILTROS[c])
    .map((c) => {
      const f = FILTROS[c];
      return f.tipo === "valores"
        ? { coluna: c, tipo: "valores", valores: [...f.set] }
        : { coluna: c, tipo: "texto", texto: f.texto };
    });
  const ipcaAtivo = document.getElementById("ipca-toggle").checked;
  return {
    token: TOKEN,
    filtros,
    ipca: { ativo: ipcaAtivo, fatores: ipcaAtivo ? FATORES_IPCA || {} : {} },
    registros_exibidos: DADOS.filter(passaFiltros).length,
    registros_total: ORIGINAIS.length,
    pivot: { config: PIVOT_CONFIG, colunas: PIVOT_ATUAL.colunas, registros: PIVOT_ATUAL.registros },
    graficos: window.PAINEL_GRAFICOS ? window.PAINEL_GRAFICOS.estado() : [],
  };
}

function nomeDoCabecalho(resp) {
  const m = /filename="?([^";]+)"?/.exec(resp.headers.get("Content-Disposition") || "");
  return m ? m[1] : null;
}

async function exportarPastaTrabalho() {
  const botao = document.getElementById("exportar-tudo");
  const rotulo = botao.textContent;
  botao.disabled = true;
  botao.textContent = "Gerando…";
  try {
    const resp = await fetch("/api/painel/exportar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(estadoExportacao()),
    });
    if (!resp.ok) {
      const e = await resp.json().catch(() => ({}));
      throw new Error(e.erro || `Erro ${resp.status}`);
    }
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = nomeDoCabecalho(resp) || "painel.xlsx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  } catch (erro) {
    mostrarErro("Não foi possível exportar a pasta de trabalho: " + erro.message);
  } finally {
    botao.disabled = false;
    botao.textContent = rotulo;
  }
}

function baixarPivotCsv() {
  const { registros, colunas } = PIVOT_ATUAL;
  const linhas = [colunas.join(";")].concat(
    registros.map((r) => colunas.map((c) => String(r[c] ?? "").replace(/;/g, ",")).join(";"))
  );
  const blob = new Blob(["\ufeff" + linhas.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "tabela_dinamica.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

if (typeof window !== "undefined") {
  window.PAINEL = {
    aoAtualizar(cb) {
      _assinantes.push(cb);
      if (DADOS.length) cb(DADOS.filter(passaFiltros), COLUNAS);
    },
    getDados() { return DADOS.filter(passaFiltros); },
    getColunas() { return COLUNAS; },
    util: { parseNumero, arredonda },
  };
  iniciar();
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = { construirPivot, metrica, parseNumero, nomeMetrica };
}
