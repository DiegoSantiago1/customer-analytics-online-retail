"""Exporta os agregados que a página estática (site/) mostra, a partir das views do banco.

Uso (depois de python -m varejo.processar):
    python -m varejo.exportar_site

O site do GitHub Pages não tem banco: ele lê site/dados.json, gerado aqui. Só saem
agregados (por mês, segmento, corte e coorte), nenhum dado de cliente individual.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from varejo.banco import Conexao, conectar
from varejo.config import RAIZ_PROJETO, ConfigError, carregar_config_banco

DESTINO = RAIZ_PROJETO / "site" / "dados.json"


def _linhas(con: Conexao, consulta: str) -> list[dict[str, Any]]:
    cur = con.execute(consulta)
    if cur.description is None:  # só acontece se a consulta não for um SELECT
        raise RuntimeError(f"consulta sem colunas: {consulta[:60]}")
    nomes = [d.name for d in cur.description]
    return [dict(zip(nomes, linha, strict=True)) for linha in cur.fetchall()]


def _json(valor: object) -> object:
    """Decimal vira float (com no máximo 4 casas) e datas viram texto ISO."""
    if isinstance(valor, Decimal):
        return round(float(valor), 4)
    if hasattr(valor, "isoformat"):
        return valor.isoformat()[:10]
    return valor


def _limpar(objeto: object) -> object:
    if isinstance(objeto, dict):
        return {k: _limpar(v) for k, v in objeto.items()}
    if isinstance(objeto, list):
        return [_limpar(v) for v in objeto]
    return _json(objeto)


class ExportarError(RuntimeError):
    """O banco não está em condição de ser publicado."""


def montar(con: Conexao) -> dict[str, Any]:
    reprovadas = con.execute("SELECT count(*) FILTER (WHERE NOT ok), count(*) FROM dq.resultado")
    falhas, total = reprovadas.fetchone() or (0, 0)
    if total == 0 or falhas:
        raise ExportarError(
            f"dq.resultado tem {falhas} falha(s) em {total} checagens: rode "
            "python -m varejo.processar até passar antes de exportar o site."
        )
    resumo = _linhas(
        con,
        """
        SELECT (SELECT sum(receita_produto_liquida) FROM analise.vw_receita_mes) AS receita_produto,
               (SELECT coalesce(sum(venda_produto_sem_cliente), 0)
                       / nullif(coalesce(sum(venda_produto_com_cliente), 0)
                                + coalesce(sum(venda_produto_sem_cliente), 0), 0)
                FROM analise.vw_receita_mes) AS pct_sem_cliente,
               count(*) AS clientes,
               sum(receita_liquida) AS receita_liquida,
               avg((frequencia >= 2)::int) AS pct_recompra,
               count(*) FILTER (WHERE em_churn) AS em_churn,
               count(*) FILTER (WHERE status_churn = 'em_risco') AS em_risco,
               count(*) FILTER (WHERE status_churn = 'inativo') AS inativos,
               coalesce(sum(receita_12m) FILTER (WHERE status_churn = 'em_risco'), 0)
                   AS receita_em_risco,
               sum(clv_previsto_6m) AS clv_6m,
               (SELECT count(*) FILTER (WHERE ok) FROM dq.resultado) AS dq_ok,
               (SELECT count(*) FROM dq.resultado) AS dq_total
        FROM analise.cliente
        """,
    )[0]
    top10 = _linhas(
        con,
        """
        SELECT sum(receita_liquida) FILTER (WHERE r <= 0.1) / sum(receita_liquida) AS pct
        FROM (SELECT receita_liquida,
                     cume_dist() OVER (ORDER BY receita_liquida DESC) AS r
              FROM analise.cliente) x
        """,
    )[0]
    resumo["pct_receita_top10"] = top10["pct"]
    return _limpar(  # type: ignore[return-value]
        {
            "resumo": resumo,
            "receita_mes": _linhas(
                con,
                "SELECT mes, mes_parcial, venda_produto_com_cliente, venda_produto_sem_cliente, "
                "cancelamento_produto, clientes_ativos, clientes_novos "
                "FROM analise.vw_receita_mes ORDER BY mes",
            ),
            "segmentos": _linhas(
                con,
                "SELECT ordem, segmento, acao, clientes, pct_clientes, receita_liquida, "
                "pct_receita, recencia_media, frequencia_media, em_churn, "
                "receita_12m_em_risco, clv_previsto_6m, atacado "
                "FROM analise.vw_segmento_resumo ORDER BY ordem",
            ),
            "churn": _linhas(
                con,
                "SELECT corte, dias, clientes, nao_voltaram, marcados, precisao, recall, f1, "
                "acuracia, escolhido FROM analise.churn_validacao ORDER BY corte DESC, dias",
            ),
            "churn_faixa": _linhas(
                con,
                "SELECT corte, ordem, faixa, clientes, nao_voltaram, taxa_nao_voltou "
                "FROM analise.churn_faixa ORDER BY corte DESC, ordem",
            ),
            "coortes": _linhas(
                con,
                "SELECT coorte, tamanho, meses_desde, retencao FROM analise.coorte_retencao "
                "WHERE NOT pre_existente AND NOT mes_parcial AND meses_desde BETWEEN 1 AND 12 "
                "ORDER BY coorte, meses_desde",
            ),
            "clv_validacao": _linhas(
                con,
                "SELECT modelo, clientes, total_previsto, total_real, erro_total_pct, "
                "erro_medio_abs, captura_top20 FROM analise.clv_validacao "
                "ORDER BY CASE modelo WHEN 'previsto' THEN 1 WHEN 'ingenuo_sazonal' THEN 2 "
                "ELSE 3 END",
            ),
            "clv_segmento": _linhas(
                con,
                "SELECT s.ordem, v.segmento, sum(v.previsto) AS previsto, "
                "sum(v.ingenuo) AS ingenuo, sum(v.ingenuo_sazonal) AS ingenuo_sazonal, "
                "sum(v.real) AS real "
                "FROM analise.clv_validacao_cliente v JOIN analise.segmento s USING (segmento) "
                "GROUP BY s.ordem, v.segmento ORDER BY s.ordem",
            ),
        }
    )


def exportar(destino: Path = DESTINO) -> dict[str, Any]:
    with conectar(carregar_config_banco()) as con:
        dados = montar(con)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    return dados


def main() -> int:
    try:
        dados = exportar()
    except (ConfigError, ExportarError, psycopg.Error) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    print(f"{DESTINO}: {len(dados['receita_mes'])} meses, {len(dados['segmentos'])} segmentos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
