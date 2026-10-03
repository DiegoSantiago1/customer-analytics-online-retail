"""Gera o relatório Power BI em formato de projeto (PBIP): modelo em TMDL e páginas em PBIR.

Uso:
    python powerbi/gerar_pbip.py

Por que gerar por código: o relatório inteiro (tabelas, relacionamentos, medidas DAX,
páginas e visuais) fica descrito neste arquivo, revisável no git como o resto do
projeto, e os identificadores (lineageTag, logicalId) são UUIDs determinísticos: gerar
de novo não muda nada que não tenha mudado aqui.

O Power BI importa as views e tabelas do schema analise (e dq.resultado) com o usuário
somente leitura. Nenhum número é recalculado no DAX além de somas, contagens e
divisões sobre o que o SQL já calculou.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PASTA = Path(__file__).resolve().parent
NOME = "customer_analytics"
# Sem ":5432" de propósito (a porta padrão é a mesma): o Power BI guarda a credencial
# por endereço, e "127.0.0.1:5432" já tem a do usuário do BI do Projeto 2.
SERVIDOR = "127.0.0.1"
BANCO = "retail"
_ESPACO = uuid.UUID("6f1d3c2a-8b4e-4f5a-9c7d-0e1f2a3b4c5d")

SCHEMA_VISUAL = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
    "visualContainer/2.4.0/schema.json"
)
SCHEMA_PAGINA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
    "page/2.0.0/schema.json"
)

# Cores do relatório (as mesmas dos gráficos do notebook).
AZUL, LARANJA, VERDE_AGUA = "#2A78D6", "#EB6834", "#1BAF7A"
TEXTO, TEXTO_2 = "#0B0B0B", "#52514E"


TEMA: dict[str, Any] = {
    "name": "Customer Analytics",
    # Ordem fixa da paleta categórica (validada para daltonismo nos pares vizinhos).
    "dataColors": [
        AZUL,
        LARANJA,
        VERDE_AGUA,
        "#EDA100",
        "#E87BA4",
        "#008300",
        "#4A3AA7",
        "#E34948",
    ],
    "background": "#FFFFFF",
    "foreground": TEXTO,
    "tableAccent": AZUL,
    "good": "#008300",
    "neutral": "#EDA100",
    "bad": "#E34948",
    "maximum": "#184F95",
    "center": "#86B6EF",
    "minimum": "#F3F7FD",
    "null": "#E4E3DF",
    # Textos escuros e legíveis: sem isto, o tema personalizado deixava títulos e
    # rótulos em cinza-claro (visto na captura do Power BI Desktop).
    "visualStyles": {
        "*": {
            "*": {
                "title": [{"fontColor": {"solid": {"color": TEXTO}}, "bold": True, "fontSize": 12}],
                "categoryAxis": [{"labelColor": {"solid": {"color": TEXTO_2}}}],
                "valueAxis": [{"labelColor": {"solid": {"color": TEXTO_2}}}],
                "legend": [{"labelColor": {"solid": {"color": TEXTO_2}}}],
            }
        },
        "card": {
            "*": {
                "labels": [{"color": {"solid": {"color": TEXTO}}}],
                "categoryLabels": [{"color": {"solid": {"color": TEXTO_2}}}],
            }
        },
    },
}


def tag(*partes: str) -> str:
    """UUID determinístico: o mesmo objeto recebe sempre o mesmo identificador."""
    return str(uuid.uuid5(_ESPACO, "/".join(partes)))


# ============================================================== modelo (TMDL)


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo: str  # int64, double, decimal, string, boolean, dateTime
    formato: str | None = None
    resumo: str = "none"
    oculta: bool = False
    ordenar_por: str | None = None
    descricao: str | None = None


@dataclass(frozen=True)
class Tabela:
    nome: str
    schema: str
    objeto: str
    colunas: list[Coluna]
    descricao: str


@dataclass(frozen=True)
class Medida:
    nome: str
    dax: str
    formato: str
    descricao: str


@dataclass(frozen=True)
class Relacao:
    de: str  # tabela.coluna (lado muitos)
    para: str  # tabela.coluna (lado um)


LIBRAS = "\\£#,0"
LIBRAS_2 = "\\£#,0.00"
PCT = "0.0%"
INT = "#,0"
DATA = "dd/mm/yyyy"
MES = "mmm/yyyy"

TABELAS = [
    Tabela(
        "receita_mes",
        "analise",
        "vw_receita_mes",
        [
            Coluna("mes", "dateTime", MES),
            Coluna("mes_parcial", "boolean"),
            Coluna("venda_produto_com_cliente", "decimal", LIBRAS, "sum"),
            Coluna("venda_produto_sem_cliente", "decimal", LIBRAS, "sum"),
            Coluna("cancelamento_produto", "decimal", LIBRAS, "sum"),
            Coluna("receita_produto_liquida", "decimal", LIBRAS, "sum"),
            Coluna("frete_taxas_e_ajustes", "decimal", LIBRAS, "sum"),
            Coluna("pedidos", "int64", INT, "sum"),
            Coluna("pedidos_com_cliente", "int64", INT, "sum"),
            Coluna("clientes_ativos", "int64", INT, "sum"),
            Coluna("clientes_novos", "int64", INT, "sum"),
        ],
        "Receita mensal por origem, pedidos e clientes (analise.vw_receita_mes).",
    ),
    Tabela(
        "segmento",
        "analise",
        "segmento",
        [
            Coluna("segmento", "string", ordenar_por="ordem"),
            Coluna("ordem", "int64", "0", oculta=True),
            Coluna("acao", "string", descricao="Ação sugerida para o CRM."),
        ],
        "Os 10 segmentos RFM, na ordem de exibição, com a ação sugerida.",
    ),
    Tabela(
        "cliente",
        "analise",
        "vw_cliente",
        [
            Coluna("cliente_id", "int64", "0"),
            Coluna("pais", "string"),
            Coluna("primeira_compra", "dateTime", DATA),
            Coluna("ultima_compra", "dateTime", DATA),
            Coluna("recencia_dias", "int64", INT, "average"),
            Coluna("frequencia", "int64", INT, "average"),
            Coluna("receita_bruta", "decimal", LIBRAS, "sum"),
            Coluna("valor_cancelado", "decimal", LIBRAS, "sum"),
            Coluna("receita_liquida", "decimal", LIBRAS, "sum"),
            Coluna("ticket_medio", "decimal", LIBRAS_2, "average"),
            Coluna("taxa_cancelamento", "decimal", PCT, "average"),
            Coluna("unidades_por_pedido", "decimal", "#,0.0", "average"),
            Coluna("r", "int64", "0"),
            Coluna("f", "int64", "0"),
            Coluna("m", "int64", "0"),
            Coluna("segmento", "string", oculta=True),
            Coluna("eh_atacado", "boolean"),
            Coluna("liquido_nao_positivo", "boolean"),
            Coluna("em_churn", "boolean"),
            Coluna("receita_12m", "decimal", LIBRAS, "sum"),
            Coluna("clv_previsto_6m", "decimal", LIBRAS, "sum"),
            Coluna("p_ativo_6m", "decimal", PCT, "average"),
            Coluna("segmento_ordem", "int64", "0", oculta=True),
            Coluna("segmento_acao", "string", oculta=True),
            Coluna("perfil", "string"),
            Coluna("faixa_recencia", "string", ordenar_por="faixa_recencia_ordem"),
            Coluna("faixa_recencia_ordem", "int64", "0", oculta=True),
        ],
        "Um cliente por linha no fim da base (10/12/2011): RFM, churn e CLV.",
    ),
    Tabela(
        "churn_validacao",
        "analise",
        "churn_validacao",
        [
            Coluna("corte", "dateTime", DATA),
            Coluna("janela_meses", "int64", "0"),
            Coluna("dias", "int64", "0"),
            Coluna("clientes", "int64", INT, "sum"),
            Coluna("nao_voltaram", "int64", INT, "sum"),
            Coluna("marcados", "int64", INT, "sum"),
            Coluna("vp", "int64", INT, "sum"),
            Coluna("fp", "int64", INT, "sum"),
            Coluna("fn", "int64", INT, "sum"),
            Coluna("vn", "int64", INT, "sum"),
            Coluna("precisao", "decimal", PCT, "average"),
            Coluna("recall", "decimal", PCT, "average"),
            Coluna("f1", "decimal", "0.000", "average"),
            Coluna("acuracia", "decimal", PCT, "average"),
            Coluna("escolhido", "boolean"),
        ],
        "Validação temporal da regra de churn: vários X em dois cortes.",
    ),
    Tabela(
        "coorte",
        "analise",
        "coorte_retencao",
        [
            Coluna("coorte", "dateTime", MES),
            Coluna("pre_existente", "boolean"),
            Coluna("tamanho", "int64", INT, "sum"),
            Coluna("meses_desde", "int64", "0"),
            Coluna("mes", "dateTime", MES),
            Coluna("mes_parcial", "boolean"),
            Coluna("ativos", "int64", INT, "sum"),
            Coluna("retencao", "decimal", PCT, "average"),
            Coluna("receita_liquida", "decimal", LIBRAS, "sum"),
        ],
        "Retenção mensal por coorte (mês da primeira compra).",
    ),
    Tabela(
        "clv_validacao",
        "analise",
        "clv_validacao",
        [
            Coluna("modelo", "string"),
            Coluna("clientes", "int64", INT, "sum"),
            Coluna("total_previsto", "decimal", LIBRAS, "sum"),
            Coluna("total_real", "decimal", LIBRAS, "sum"),
            Coluna(
                "erro_total_pct",
                "decimal",
                "0.0",
                "none",
                descricao="Erro no total, em pontos percentuais.",
            ),
            Coluna("erro_medio_abs", "decimal", LIBRAS_2, "none"),
            Coluna("captura_top20", "decimal", "0.000", "none"),
        ],
        "Resumo da validação do CLV: modelo contra o ingênuo.",
    ),
    Tabela(
        "clv_validacao_cliente",
        "analise",
        "clv_validacao_cliente",
        [
            Coluna("cliente_id", "int64", "0"),
            Coluna("segmento", "string", oculta=True),
            Coluna("previsto", "decimal", LIBRAS, "sum"),
            Coluna("ingenuo", "decimal", LIBRAS, "sum"),
            Coluna("real", "decimal", LIBRAS, "sum"),
        ],
        "Previsão do CLV feita em 10/06/2011, ingênuo e real, por cliente.",
    ),
    Tabela(
        "qualidade",
        "dq",
        "resultado",
        [
            Coluna("verificacao", "string"),
            Coluna("camada", "string"),
            Coluna("descricao", "string"),
            Coluna("esperado", "string"),
            Coluna("obtido", "string"),
            Coluna("ok", "boolean"),
            Coluna("verificado_em", "dateTime", "dd/mm/yyyy hh:nn"),
        ],
        "Resultado das 16 checagens de qualidade (dq.verificar).",
    ),
]

RELACOES = [
    Relacao("cliente.segmento", "segmento.segmento"),
    Relacao("clv_validacao_cliente.segmento", "segmento.segmento"),
]

MEDIDAS = [
    Medida(
        "Receita de produto",
        "SUM ( receita_mes[receita_produto_liquida] )",
        LIBRAS,
        "Receita de produto líquida de cancelamentos, com e sem cliente identificado.",
    ),
    Medida(
        "Venda com cliente",
        "SUM ( receita_mes[venda_produto_com_cliente] )",
        LIBRAS,
        "Venda de produto de clientes identificados (antes dos cancelamentos).",
    ),
    Medida(
        "Venda sem cliente",
        "SUM ( receita_mes[venda_produto_sem_cliente] )",
        LIBRAS,
        "Venda de produto sem Customer ID: receita real, não atribuível a cliente.",
    ),
    Medida(
        "% sem cliente",
        "DIVIDE ( [Venda sem cliente], [Venda com cliente] + [Venda sem cliente] )",
        PCT,
        "Parte da venda de produto sem cliente identificado.",
    ),
    Medida("Clientes", "COUNTROWS ( cliente )", INT, "Clientes com ao menos uma compra."),
    Medida(
        "Receita líquida",
        "SUM ( cliente[receita_liquida] )",
        LIBRAS,
        "Compras menos cancelamentos dos clientes no filtro.",
    ),
    Medida(
        "% dos clientes",
        "DIVIDE ( [Clientes], CALCULATE ( [Clientes], ALLSELECTED ( segmento ) ) )",
        PCT,
        "Parte dos clientes do filtro (o slicer de perfil continua valendo).",
    ),
    Medida(
        "% da receita",
        "DIVIDE ( [Receita líquida], CALCULATE ( [Receita líquida], ALLSELECTED ( segmento ) ) )",
        PCT,
        "Parte da receita líquida do filtro.",
    ),
    Medida(
        "Ticket médio",
        "DIVIDE ( [Receita líquida], SUM ( cliente[frequencia] ) )",
        LIBRAS_2,
        "Receita líquida por compra.",
    ),
    Medida(
        "Clientes em churn",
        "CALCULATE ( [Clientes], cliente[em_churn] = TRUE () )",
        INT,
        "Mais de 90 dias sem comprar no fim da base.",
    ),
    Medida(
        "% em churn",
        "DIVIDE ( [Clientes em churn], [Clientes] )",
        PCT,
        "Parte dos clientes em churn.",
    ),
    Medida(
        "Receita em risco",
        "CALCULATE ( SUM ( cliente[receita_12m] ), cliente[em_churn] = TRUE () )",
        LIBRAS,
        "Receita líquida dos últimos 12 meses dos clientes hoje em churn.",
    ),
    Medida(
        "CLV previsto (6 meses)",
        "SUM ( cliente[clv_previsto_6m] )",
        LIBRAS,
        "Receita líquida esperada nos 6 meses seguintes ao fim da base.",
    ),
    Medida(
        "Precisão da regra",
        "CALCULATE ( [Precisão], churn_validacao[escolhido] = TRUE (), "
        "churn_validacao[corte] = DATE ( 2011, 6, 10 ) )",
        PCT,
        "Precisão do X escolhido (90 dias) no corte principal, 10/06/2011.",
    ),
    Medida(
        "Precisão",
        "AVERAGE ( churn_validacao[precisao] )",
        PCT,
        "Dos clientes marcados como churn no corte, quantos de fato não voltaram em 6 meses.",
    ),
    Medida(
        "Recall",
        "AVERAGE ( churn_validacao[recall] )",
        PCT,
        "Dos clientes que não voltaram em 6 meses, quantos a regra marcou no corte.",
    ),
    Medida(
        "Retenção",
        "DIVIDE ( SUM ( coorte[ativos] ), SUM ( coorte[tamanho] ) )",
        PCT,
        "Clientes da coorte que compraram no mês, sobre o tamanho da coorte.",
    ),
    Medida(
        "CLV previsto (validação)",
        "SUM ( clv_validacao_cliente[previsto] )",
        LIBRAS,
        "Previsão feita em 10/06/2011 para os 6 meses seguintes.",
    ),
    Medida(
        "CLV ingênuo (validação)",
        "SUM ( clv_validacao_cliente[ingenuo] )",
        LIBRAS,
        "Modelo ingênuo: repete os 6 meses anteriores ao corte.",
    ),
    Medida(
        "Receita real (validação)",
        "SUM ( clv_validacao_cliente[real] )",
        LIBRAS,
        "Receita líquida real de 10/06 a 10/12/2011.",
    ),
    Medida(
        "Checagens ok",
        'COUNTROWS ( FILTER ( qualidade, qualidade[ok] ) ) & " de " & COUNTROWS ( qualidade )',
        "",
        "Checagens de qualidade aprovadas na última execução.",
    ),
]


def _nome_tmdl(nome: str) -> str:
    """Nomes com espaço, acento ou símbolo vão entre aspas simples no TMDL."""
    return nome if nome.replace("_", "").isalnum() and nome.isascii() else f"'{nome}'"


def tmdl_tabela(t: Tabela) -> str:
    linhas = [f"/// {t.descricao}", f"table {t.nome}", f"\tlineageTag: {tag('tabela', t.nome)}", ""]
    for c in t.colunas:
        if c.descricao:
            linhas.append(f"\t/// {c.descricao}")
        linhas.append(f"\tcolumn {_nome_tmdl(c.nome)}")
        linhas.append(f"\t\tdataType: {c.tipo}")
        if c.oculta:
            linhas.append("\t\tisHidden")
        if c.formato:
            linhas.append(f"\t\tformatString: {c.formato}")
        linhas.append(f"\t\tlineageTag: {tag('coluna', t.nome, c.nome)}")
        linhas.append(f"\t\tsummarizeBy: {c.resumo}")
        linhas.append(f"\t\tsourceColumn: {c.nome}")
        if c.ordenar_por:
            linhas.append(f"\t\tsortByColumn: {c.ordenar_por}")
        if c.tipo == "dateTime":
            linhas += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
        linhas.append("")
    linhas += [
        f"\tpartition {t.nome} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    Fonte = PostgreSQL.Database("{SERVIDOR}", "{BANCO}"),',
        f'\t\t\t\t    Tabela = Fonte{{[Schema = "{t.schema}", Item = "{t.objeto}"]}}[Data]',
        "\t\t\t\tin",
        "\t\t\t\t    Tabela",
        "",
    ]
    return "\n".join(linhas)


def tmdl_medidas() -> str:
    linhas = ["table Medidas", f"\tlineageTag: {tag('tabela', 'Medidas')}", ""]
    for m in MEDIDAS:
        linhas.append(f"\t/// {m.descricao}")
        linhas.append(f"\tmeasure {_nome_tmdl(m.nome)} = {m.dax}")
        if m.formato:
            linhas.append(f"\t\tformatString: {m.formato}")
        linhas.append(f"\t\tlineageTag: {tag('medida', m.nome)}")
        linhas.append("")
    # Tabela só de medidas: uma coluna oculta e uma partição M vazia (mesmo formato
    # do Projeto 2, que o Power BI Desktop abriu e salvou sem alterar).
    linhas += [
        "\tcolumn Coluna",
        "\t\tdataType: string",
        "\t\tisHidden",
        f"\t\tlineageTag: {tag('coluna', 'Medidas', 'Coluna')}",
        "\t\tsummarizeBy: none",
        "\t\tsourceColumn: Coluna",
        "",
        "\tpartition Medidas = m",
        "\t\tmode: import",
        "\t\tsource = #table(type table [Coluna = text], {})",
        "",
    ]
    return "\n".join(linhas)


def tmdl_modelo() -> str:
    nomes = [t.nome for t in TABELAS] + ["Medidas"]
    linhas = [
        "model Model",
        "\tculture: pt-BR",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: pt-BR",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        f"annotation PBI_QueryOrder = {json.dumps(nomes, ensure_ascii=False)}",
        "",
        'annotation PBI_ProTooling = ["DevMode"]',
        "",
        *[f"ref table {n}" for n in nomes],
        "",
        "ref cultureInfo pt-BR",
        "",
    ]
    return "\n".join(linhas)


def tmdl_relacoes() -> str:
    linhas = []
    for r in RELACOES:
        linhas += [
            f"relationship {tag('relacao', r.de, r.para)}",
            f"\tfromColumn: {r.de}",
            f"\ttoColumn: {r.para}",
            "",
        ]
    return "\n".join(linhas)


# ============================================================== relatório (PBIR)


def _ref(entidade: str, propriedade: str, medida: bool) -> dict[str, Any]:
    tipo = "Measure" if medida else "Column"
    return {tipo: {"Expression": {"SourceRef": {"Entity": entidade}}, "Property": propriedade}}


def campo(texto: str, rotulo: str | None = None) -> dict[str, Any]:
    """'Medidas.Clientes' (medida) ou 'cliente.segmento' (coluna) -> projeção do PBIR."""
    entidade, propriedade = texto.split(".", 1)
    projecao: dict[str, Any] = {
        "field": _ref(entidade, propriedade, entidade == "Medidas"),
        "queryRef": texto,
        "nativeQueryRef": propriedade,
    }
    if rotulo:
        projecao["displayName"] = rotulo
    return projecao


def _literal(valor: str) -> dict[str, Any]:
    return {"expr": {"Literal": {"Value": valor}}}


def titulo(texto: str) -> dict[str, Any]:
    return {"title": [{"properties": {"show": _literal("true"), "text": _literal(f"'{texto}'")}}]}


@dataclass
class Visual:
    nome: str
    tipo: str
    x: int
    y: int
    largura: int
    altura: int
    papeis: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    titulo: str | None = None
    objetos: dict[str, Any] | None = None
    filtros: list[dict[str, Any]] | None = None
    ordenar: dict[str, Any] | None = None


def _json_visual(v: Visual, z: int) -> dict[str, Any]:
    corpo: dict[str, Any] = {"visualType": v.tipo}
    if v.objetos is None and v.tipo in GRAFICOS:
        v.objetos = SEM_TITULO_EIXOS
    if v.papeis:
        estado = {papel: {"projections": proj} for papel, proj in v.papeis.items()}
        corpo["query"] = {"queryState": estado}
        if v.ordenar:
            corpo["query"]["sortDefinition"] = v.ordenar
    if v.objetos:
        corpo["objects"] = v.objetos
    if v.titulo:
        corpo["visualContainerObjects"] = titulo(v.titulo)
    resultado: dict[str, Any] = {
        "$schema": SCHEMA_VISUAL,
        "name": v.nome,
        "position": {
            "x": v.x,
            "y": v.y,
            "z": z,
            "width": v.largura,
            "height": v.altura,
            "tabOrder": z,
        },
        "visual": corpo,
    }
    if v.filtros:
        resultado["filterConfig"] = {"filters": v.filtros}
    return resultado


def cabecalho(texto: str, subtitulo: str) -> Visual:
    paragrafos = [
        {
            "textRuns": [
                {
                    "value": texto,
                    "textStyle": {"fontWeight": "bold", "fontSize": "20pt", "color": TEXTO},
                }
            ]
        },
        {"textRuns": [{"value": subtitulo, "textStyle": {"fontSize": "11pt", "color": TEXTO_2}}]},
    ]
    return Visual(
        "cabecalho",
        "textbox",
        16,
        8,
        1248,
        64,
        objetos={"general": [{"properties": {"paragraphs": paragrafos}}]},
    )


def nota(nome: str, x: int, y: int, largura: int, altura: int, texto: str) -> Visual:
    paragrafos = [
        {"textRuns": [{"value": texto, "textStyle": {"fontSize": "10pt", "color": TEXTO_2}}]}
    ]
    return Visual(
        nome,
        "textbox",
        x,
        y,
        largura,
        altura,
        objetos={"general": [{"properties": {"paragraphs": paragrafos}}]},
    )


def cartao(nome: str, x: int, medida: str, rotulo: str, y: int = 80, largura: int = 300) -> Visual:
    # labelDisplayUnits 1D = sem abreviar ("£18.981.262", e não "£19 Mi").
    rotulos = {"labels": [{"properties": {"labelDisplayUnits": _literal("1D")}}]}
    return Visual(
        nome, "card", x, y, largura, 104, {"Values": [campo(medida, rotulo)]}, objetos=rotulos
    )


# Gráficos sem título nos eixos: o título do visual já diz o que é.
GRAFICOS = {"columnChart", "clusteredBarChart", "lineChart", "clusteredColumnChart"}
SEM_TITULO_EIXOS = {
    "valueAxis": [{"properties": {"showAxisTitle": _literal("false")}}],
    "categoryAxis": [{"properties": {"showAxisTitle": _literal("false")}}],
}


def filtro_booleano(nome: str, coluna: str, valor: bool) -> dict[str, Any]:
    return filtro_valores(nome, coluna, ["true" if valor else "false"])


def filtro_valores(nome: str, coluna: str, literais: list[str]) -> dict[str, Any]:
    """Filtro de visual "coluna IN (literais)"; literais no formato do PBIR (1L, true...)."""
    entidade, propriedade = coluna.split(".", 1)
    ref = _ref(entidade, propriedade, False)
    return {
        "name": nome,
        "field": ref,
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "t", "Entity": entidade, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [
                                {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Source": "t"}},
                                        "Property": propriedade,
                                    }
                                }
                            ],
                            "Values": [[{"Literal": {"Value": v}}] for v in literais],
                        }
                    }
                }
            ],
        },
    }


def ordenar_por(coluna: str, direcao: str = "Ascending") -> dict[str, Any]:
    entidade, propriedade = coluna.split(".", 1)
    return {
        "sort": [
            {"field": _ref(entidade, propriedade, entidade == "Medidas"), "direction": direcao}
        ]
    }


PAGINAS: list[tuple[str, str, list[Visual]]] = [
    (
        "visao_geral",
        "Visão geral",
        [
            cabecalho(
                "Visão geral",
                "Online Retail II (UCI), dez/2009 a dez/2011. Receita de produto, "
                "clientes e a qualidade dos dados.",
            ),
            cartao("cartao_receita", 16, "Medidas.Receita de produto", "Receita de produto"),
            cartao("cartao_clientes", 332, "Medidas.Clientes", "Clientes"),
            cartao("cartao_sem_cliente", 648, "Medidas.% sem cliente", "Venda sem cliente"),
            cartao("cartao_dq", 964, "Medidas.Checagens ok", "Checagens de qualidade"),
            Visual(
                "colunas_mes",
                "columnChart",
                16,
                192,
                820,
                516,
                {
                    "Category": [campo("receita_mes.mes", "Mês")],
                    "Y": [
                        campo("Medidas.Venda com cliente", "Com cliente"),
                        campo("Medidas.Venda sem cliente", "Sem cliente"),
                    ],
                },
                titulo="Venda de produto por mês (dez/2011 vai só até o dia 9)",
                ordenar=ordenar_por("receita_mes.mes"),
            ),
            Visual(
                "tab_qualidade",
                "tableEx",
                852,
                192,
                412,
                516,
                {
                    "Values": [
                        campo("qualidade.camada", "Camada"),
                        campo("qualidade.verificacao", "Checagem"),
                        campo("qualidade.ok", "Ok"),
                    ]
                },
                titulo="Checagens de qualidade (schema dq)",
            ),
        ],
    ),
    (
        "segmentos",
        "Segmentos RFM",
        [
            cabecalho(
                "Segmentos RFM",
                "Quem são os melhores clientes? Notas de 1 a 5 em recência, frequência e "
                "valor; segmento pelo mapa R x F.",
            ),
            Visual(
                "seg_perfil",
                "slicer",
                16,
                80,
                300,
                96,
                {"Values": [campo("cliente.perfil", "Perfil")]},
            ),
            cartao("cartao_clientes", 332, "Medidas.Clientes", "Clientes"),
            cartao("cartao_receita", 648, "Medidas.Receita líquida", "Receita líquida"),
            cartao("cartao_ticket", 964, "Medidas.Ticket médio", "Ticket médio"),
            Visual(
                "barras_segmento",
                "clusteredBarChart",
                16,
                192,
                600,
                516,
                {
                    "Category": [campo("segmento.segmento", "Segmento")],
                    "Y": [
                        campo("Medidas.% dos clientes", "% dos clientes"),
                        campo("Medidas.% da receita", "% da receita"),
                    ],
                },
                titulo="Parte dos clientes e da receita por segmento",
                ordenar=ordenar_por("segmento.segmento"),
            ),
            Visual(
                "tab_segmento",
                "tableEx",
                632,
                192,
                632,
                516,
                {
                    "Values": [
                        campo("segmento.segmento", "Segmento"),
                        campo("Medidas.Clientes", "Clientes"),
                        campo("Medidas.Receita líquida", "Receita líquida"),
                        campo("Medidas.Clientes em churn", "Em churn"),
                        campo("Medidas.CLV previsto (6 meses)", "CLV 6 meses"),
                        campo("segmento.acao", "Ação sugerida"),
                    ]
                },
                titulo="Resumo e ação por segmento",
                ordenar=ordenar_por("segmento.segmento"),
            ),
        ],
    ),
    (
        "churn",
        "Churn",
        [
            cabecalho(
                "Churn",
                "Quem está indo embora? Regra: mais de 90 dias sem comprar, validada no "
                "tempo em dois cortes.",
            ),
            cartao("cartao_churn", 16, "Medidas.Clientes em churn", "Clientes em churn"),
            cartao("cartao_pct_churn", 332, "Medidas.% em churn", "% em churn"),
            cartao("cartao_risco", 648, "Medidas.Receita em risco", "Receita em risco (12 meses)"),
            cartao(
                "cartao_precisao",
                964,
                "Medidas.Precisão da regra",
                "Precisão da regra (corte de jun/2011)",
            ),
            *[
                Visual(
                    f"linha_validacao_{sufixo}",
                    "lineChart",
                    x,
                    200,
                    404,
                    392,
                    {
                        "Category": [campo("churn_validacao.dias", "X (dias sem comprar)")],
                        "Y": [
                            campo("Medidas.Precisão", "Precisão"),
                            campo("Medidas.Recall", "Recall"),
                        ],
                    },
                    titulo=f"Precisão e recall por X: corte de {rotulo}",
                    ordenar=ordenar_por("churn_validacao.dias"),
                    filtros=[
                        filtro_valores(
                            f"filtro_corte_{sufixo}",
                            "churn_validacao.corte",
                            [f"datetime'{data}T00:00:00'"],
                        )
                    ],
                )
                for sufixo, x, rotulo, data in (
                    ("jun2011", 16, "10/06/2011", "2011-06-10"),
                    ("dez2010", 436, "10/12/2010", "2010-12-10"),
                )
            ],
            Visual(
                "barras_churn_segmento",
                "clusteredBarChart",
                856,
                200,
                408,
                392,
                {
                    "Category": [campo("segmento.segmento", "Segmento")],
                    "Y": [campo("Medidas.Clientes em churn", "Clientes em churn")],
                },
                titulo="Clientes em churn por segmento",
                ordenar=ordenar_por("segmento.segmento"),
            ),
            nota(
                "nota_sazonalidade",
                16,
                604,
                1248,
                104,
                "Limitação medida: no corte de 10/06/2011, X = 90 tem precisão de 64% e recall "
                "de 80%. Logo depois do pico de set a nov (corte de 10/12/2010), a mesma regra "
                "pega só 45% de quem some, porque muitos clientes só voltam no pico seguinte. "
                "A marcação do fim da base (também em dezembro) é, portanto, conservadora. "
                "Detalhes em docs/DECISOES.md (D17 e D18).",
            ),
        ],
    ),
    (
        "coortes_clv",
        "Coortes e CLV",
        [
            cabecalho(
                "Coortes e CLV",
                "A retenção melhora ou piora? Quanto vale cada cliente nos próximos 6 meses?",
            ),
            Visual(
                "matriz_coortes",
                "pivotTable",
                16,
                80,
                760,
                628,
                {
                    "Rows": [campo("coorte.coorte", "Coorte")],
                    "Columns": [campo("coorte.meses_desde", "Meses desde a 1ª compra")],
                    "Values": [campo("Medidas.Retenção", "Retenção")],
                },
                titulo="Retenção nos meses 1 a 12 (sem a coorte pré-existente de dez/2009)",
                filtros=[
                    filtro_booleano("filtro_pre_existente", "coorte.pre_existente", False),
                    filtro_booleano("filtro_mes_parcial", "coorte.mes_parcial", False),
                    filtro_valores(
                        "filtro_meses", "coorte.meses_desde", [f"{m}L" for m in range(1, 13)]
                    ),
                ],
            ),
            cartao(
                "cartao_clv",
                792,
                "Medidas.CLV previsto (6 meses)",
                "CLV previsto, próximos 6 meses",
                largura=472,
            ),
            Visual(
                "colunas_clv",
                "clusteredColumnChart",
                792,
                192,
                472,
                330,
                {
                    "Category": [campo("segmento.segmento", "Segmento")],
                    "Y": [
                        campo("Medidas.CLV previsto (validação)", "Previsto"),
                        campo("Medidas.CLV ingênuo (validação)", "Ingênuo"),
                        campo("Medidas.Receita real (validação)", "Real"),
                    ],
                },
                titulo="Validação: previsão de 10/06/2011 x real",
                ordenar=ordenar_por("segmento.segmento"),
            ),
            Visual(
                "tab_clv",
                "tableEx",
                792,
                534,
                472,
                174,
                {
                    "Values": [
                        campo("clv_validacao.modelo", "Modelo"),
                        campo("clv_validacao.erro_total_pct", "Erro no total (%)"),
                        campo("clv_validacao.erro_medio_abs", "Erro médio"),
                        campo("clv_validacao.captura_top20", "Captura top 20%"),
                    ]
                },
                titulo="Modelo x ingênuo",
            ),
        ],
    ),
]


# ============================================================== escrita


def _texto(conteudo: str | dict[str, Any]) -> str:
    if isinstance(conteudo, str):
        return conteudo
    return json.dumps(conteudo, ensure_ascii=False, indent=2) + "\n"


def plataforma(tipo: str) -> dict[str, Any]:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
        "platformProperties/2.0.0/schema.json",
        "metadata": {"type": tipo, "displayName": NOME},
        "config": {"version": "2.0", "logicalId": tag("item", tipo)},
    }


def gerar(destino: Path = PASTA) -> list[Path]:
    """Escreve o projeto e remove os arquivos gerados antes que não existem mais.

    Não apaga pastas inteiras: o OneDrive trava pasta recém-apagada (lição do Projeto 2),
    então os arquivos são sobrescritos e só os que sobraram são removidos.
    """
    relatorio = destino / f"{NOME}.Report"
    modelo = destino / f"{NOME}.SemanticModel"
    arquivos: dict[Path, str] = {}

    def _gravar(caminho: Path, conteudo: str | dict[str, Any]) -> None:
        arquivos[caminho] = _texto(conteudo)

    _gravar(
        destino / f"{NOME}.pbip",
        {
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{NOME}.Report"}}],
            "settings": {"enableAutoRecovery": True},
        },
    )
    _gravar(destino / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")

    # Modelo semântico
    _gravar(modelo / ".platform", plataforma("SemanticModel"))
    _gravar(modelo / "definition.pbism", {"version": "4.2", "settings": {}})
    d = modelo / "definition"
    _gravar(d / "database.tmdl", "database\n\tcompatibilityLevel: 1606\n\n")
    _gravar(d / "model.tmdl", tmdl_modelo())
    _gravar(d / "relationships.tmdl", tmdl_relacoes())
    _gravar(d / "cultures" / "pt-BR.tmdl", "cultureInfo pt-BR\n\n")
    for t in TABELAS:
        _gravar(d / "tables" / f"{t.nome}.tmdl", tmdl_tabela(t))
    _gravar(d / "tables" / "Medidas.tmdl", tmdl_medidas())

    # Relatório
    _gravar(relatorio / ".platform", plataforma("Report"))
    _gravar(
        relatorio / "definition.pbir",
        {
            "version": "4.0",
            "datasetReference": {"byPath": {"path": f"../{NOME}.SemanticModel"}},
        },
    )
    r = relatorio / "definition"
    _gravar(
        r / "version.json",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
            "definition/versionMetadata/1.0.0/schema.json",
            "version": "2.0.0",
        },
    )
    # Tema com a paleta dos gráficos do notebook (mesmo formato do Projeto 2).
    _gravar(relatorio / "StaticResources" / "RegisteredResources" / "tema-varejo.json", TEMA)
    _gravar(
        r / "report.json",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
            "definition/report/3.3.0/schema.json",
            "themeCollection": {
                "customTheme": {
                    "name": "tema-varejo.json",
                    "reportVersionAtImport": {
                        "visual": "2.13.0",
                        "report": "3.4.0",
                        "page": "2.3.1",
                    },
                    "type": "RegisteredResources",
                }
            },
            "resourcePackages": [
                {
                    "name": "RegisteredResources",
                    "type": "RegisteredResources",
                    "items": [
                        {
                            "name": "tema-varejo.json",
                            "path": "tema-varejo.json",
                            "type": "CustomTheme",
                        }
                    ],
                }
            ],
            "settings": {
                "useStylableVisualContainerHeader": True,
                "defaultDrillFilterOtherVisuals": True,
                "useEnhancedTooltips": False,
            },
        },
    )
    _gravar(
        r / "pages" / "pages.json",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
            "definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": [nome for nome, _, _ in PAGINAS],
            "activePageName": PAGINAS[0][0],
        },
    )
    for nome, exibicao, visuais in PAGINAS:
        _gravar(
            r / "pages" / nome / "page.json",
            {
                "$schema": SCHEMA_PAGINA,
                "name": nome,
                "displayName": exibicao,
                "displayOption": "FitToPage",
                "height": 720,
                "width": 1280,
            },
        )
        for z, v in enumerate(visuais):
            _gravar(
                r / "pages" / nome / "visuals" / v.nome / "visual.json", _json_visual(v, z * 1000)
            )

    for caminho, texto in arquivos.items():
        caminho.parent.mkdir(parents=True, exist_ok=True)
        if not caminho.exists() or caminho.read_text(encoding="utf-8") != texto:
            caminho.write_text(texto, encoding="utf-8", newline="\n")
    for pasta in (relatorio / "definition", modelo / "definition", relatorio / "StaticResources"):
        for antigo in pasta.rglob("*"):
            if antigo.is_file() and antigo not in arquivos:
                antigo.unlink()
    return sorted(arquivos)


if __name__ == "__main__":
    arquivos = gerar()
    print(f"{len(arquivos)} arquivos gerados em {PASTA}")
