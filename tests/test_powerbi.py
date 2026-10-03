"""Gerador do relatório Power BI (PBIP): determinismo e referências válidas.

O teste real do relatório foi abrir no Power BI Desktop e conferir cada número contra
o SQL (docs/POWERBI.md). Aqui fica o que dá para garantir sem a interface: o projeto
gerado é sempre o mesmo, o JSON é válido e nada aponta para tabela, coluna ou medida
que não existe no modelo.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from varejo.banco import Conexao
from varejo.config import RAIZ_PROJETO


def _carregar_gerador() -> ModuleType:
    caminho = RAIZ_PROJETO / "powerbi" / "gerar_pbip.py"
    spec = importlib.util.spec_from_file_location("gerar_pbip", caminho)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["gerar_pbip"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


gerador = _carregar_gerador()


@pytest.fixture(scope="module")
def projeto(tmp_path_factory: pytest.TempPathFactory) -> Path:
    destino = tmp_path_factory.mktemp("pbip")
    gerador.gerar(destino)
    return destino


def _conteudo(pasta: Path) -> dict[str, str]:
    return {
        str(p.relative_to(pasta)): p.read_text(encoding="utf-8")
        for p in sorted(pasta.rglob("*"))
        if p.is_file()
    }


def test_gerar_duas_vezes_da_o_mesmo_resultado(projeto: Path, tmp_path: Path) -> None:
    gerador.gerar(tmp_path)
    assert _conteudo(tmp_path) == _conteudo(projeto)


def test_arquivo_que_saiu_do_gerador_e_removido(projeto: Path, tmp_path: Path) -> None:
    gerador.gerar(tmp_path)
    sobra = tmp_path / f"{gerador.NOME}.Report" / "definition" / "pages" / "velha" / "page.json"
    sobra.parent.mkdir(parents=True)
    sobra.write_text("{}", encoding="utf-8")
    gerador.gerar(tmp_path)
    assert not sobra.exists()


def test_todo_json_e_valido(projeto: Path) -> None:
    arquivos = [p for p in projeto.rglob("*") if p.suffix in {".json", ".pbir", ".pbism", ".pbip"}]
    assert len(arquivos) > 30
    for arquivo in arquivos:
        json.loads(arquivo.read_text(encoding="utf-8"))


def _campos_do_modelo() -> tuple[dict[str, set[str]], set[str]]:
    colunas = {t.nome: {c.nome for c in t.colunas} for t in gerador.TABELAS}
    medidas = {m.nome for m in gerador.MEDIDAS}
    return colunas, medidas


def _referencias(objeto: object) -> list[tuple[str, str, str]]:
    """Todas as referências (tipo, entidade, propriedade) dentro de um visual."""
    achadas: list[tuple[str, str, str]] = []
    if isinstance(objeto, dict):
        for tipo in ("Column", "Measure"):
            ref = objeto.get(tipo)
            if isinstance(ref, dict) and "Property" in ref:
                fonte = ref["Expression"]["SourceRef"]
                entidade = fonte.get("Entity")
                if entidade:  # "Source" aponta para um alias do filtro, já resolvido acima
                    achadas.append((tipo, entidade, ref["Property"]))
        for valor in objeto.values():
            achadas += _referencias(valor)
    elif isinstance(objeto, list):
        for item in objeto:
            achadas += _referencias(item)
    return achadas


def test_visuais_so_usam_campos_que_existem(projeto: Path) -> None:
    colunas, medidas = _campos_do_modelo()
    visuais = list(projeto.rglob("visual.json"))
    assert len(visuais) >= 25
    for arquivo in visuais:
        for tipo, entidade, propriedade in _referencias(json.loads(arquivo.read_text("utf-8"))):
            if tipo == "Measure":
                assert entidade == "Medidas" and propriedade in medidas, (arquivo, propriedade)
            else:
                assert propriedade in colunas.get(entidade, set()), (arquivo, entidade, propriedade)


def test_dax_so_cita_colunas_e_medidas_que_existem() -> None:
    colunas, medidas = _campos_do_modelo()
    for medida in gerador.MEDIDAS:
        for tabela, coluna in re.findall(r"(\w+)\[(\w+)\]", medida.dax):
            assert coluna in colunas[tabela], (medida.nome, tabela, coluna)
        for citada in re.findall(r"(?<![\w\]])\[([^\]]+)\]", medida.dax):
            assert citada in medidas, (medida.nome, citada)


def test_relacionamentos_e_ordenacao_apontam_para_colunas_existentes() -> None:
    colunas, _ = _campos_do_modelo()
    for relacao in gerador.RELACOES:
        for lado in (relacao.de, relacao.para):
            tabela, coluna = lado.split(".")
            assert coluna in colunas[tabela], lado
    for tabela in gerador.TABELAS:
        for coluna in tabela.colunas:
            if coluna.ordenar_por:
                assert coluna.ordenar_por in colunas[tabela.nome]


def test_modelo_le_o_banco_retail_sem_senha(projeto: Path) -> None:
    tmdl = "\n".join(p.read_text("utf-8") for p in projeto.rglob("*.tmdl"))
    assert 'PostgreSQL.Database("127.0.0.1", "retail")' in tmdl
    assert "password" not in tmdl.lower() and "senha" not in tmdl.lower()


@pytest.mark.integracao
def test_colunas_do_modelo_existem_no_banco(bd_bi: Conexao) -> None:
    """Cada coluna do modelo existe na view/tabela que o Power BI importa (como o usuário do BI)."""
    for tabela in gerador.TABELAS:
        existentes = {
            nome
            for (nome,) in bd_bi.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s",
                (tabela.schema, tabela.objeto),
            )
        }
        faltando = {c.nome for c in tabela.colunas} - existentes
        assert not faltando, (tabela.nome, faltando)
