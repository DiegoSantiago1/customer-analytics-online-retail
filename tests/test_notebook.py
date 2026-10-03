"""O notebook versionado precisa estar em sincronia com o gerador (montar_notebook.py)."""

import importlib.util
import sys

import nbformat

from varejo.config import RAIZ_PROJETO


def test_celulas_do_ipynb_sao_as_do_gerador() -> None:
    caminho = RAIZ_PROJETO / "notebooks" / "montar_notebook.py"
    spec = importlib.util.spec_from_file_location("montar_notebook", caminho)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["montar_notebook"] = modulo
    spec.loader.exec_module(modulo)

    gerado = modulo.montar()
    versionado = nbformat.read(RAIZ_PROJETO / "notebooks" / "customer_analytics.ipynb", 4)
    assert [(c.cell_type, c.source) for c in versionado.cells] == [
        (c.cell_type, c.source) for c in gerado.cells
    ]


def test_notebook_versionado_rodou_sem_erro() -> None:
    versionado = nbformat.read(RAIZ_PROJETO / "notebooks" / "customer_analytics.ipynb", 4)
    erros = [
        o.get("ename")
        for c in versionado.cells
        if c.cell_type == "code"
        for o in c.get("outputs", [])
        if o.get("output_type") == "error"
    ]
    assert erros == []
    imagens = sum(
        1
        for c in versionado.cells
        if c.cell_type == "code"
        for o in c.get("outputs", [])
        if "image/png" in o.get("data", {})
    )
    assert imagens == 5
