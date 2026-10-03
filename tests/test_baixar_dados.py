"""Testes do download: hash, zip adulterado, zip slip e idempotência (sem rede)."""

import hashlib
import urllib.request
import zipfile
from pathlib import Path

import pytest

from varejo import baixar_dados
from varejo.baixar_dados import DadosError, baixar, extrair_planilha, planilha_valida

CONTEUDO = b"planilha de mentira"
HASH = hashlib.sha256(CONTEUDO).hexdigest()


def criar_zip(caminho: Path, membros: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(caminho, "w") as arquivo_zip:
        for nome, conteudo in membros.items():
            arquivo_zip.writestr(nome, conteudo)
    return caminho


def test_extrai_e_confere_o_hash(tmp_path: Path) -> None:
    zip_ = criar_zip(tmp_path / "a.zip", {"online_retail_II.xlsx": CONTEUDO})
    destino = tmp_path / "raw" / "online_retail_II.xlsx"
    extrair_planilha(zip_, destino, sha256=HASH)
    assert destino.read_bytes() == CONTEUDO
    assert planilha_valida(destino, HASH)


def test_hash_diferente_e_recusado_e_nao_deixa_arquivo(tmp_path: Path) -> None:
    zip_ = criar_zip(tmp_path / "a.zip", {"online_retail_II.xlsx": b"outra versao"})
    destino = tmp_path / "online_retail_II.xlsx"
    with pytest.raises(DadosError, match="SHA-256"):
        extrair_planilha(zip_, destino, sha256=HASH)
    assert list(tmp_path.iterdir()) == [zip_]  # nem o destino nem o .parcial ficaram


def test_zip_sem_a_planilha_e_recusado(tmp_path: Path) -> None:
    zip_ = criar_zip(tmp_path / "a.zip", {"outra.xlsx": CONTEUDO})
    with pytest.raises(DadosError, match="não contém"):
        extrair_planilha(zip_, tmp_path / "online_retail_II.xlsx", sha256=HASH)


def test_zip_slip_nao_escreve_fora_da_pasta(tmp_path: Path) -> None:
    # Um membro "../online_retail_II.xlsx" não é o membro esperado: é ignorado.
    pasta = tmp_path / "dentro"
    pasta.mkdir()
    zip_ = criar_zip(pasta / "a.zip", {"../online_retail_II.xlsx": CONTEUDO})
    with pytest.raises(DadosError, match="não contém"):
        extrair_planilha(zip_, pasta / "online_retail_II.xlsx", sha256=HASH)
    assert not (tmp_path / "online_retail_II.xlsx").exists()


def test_zip_bomb_e_recusado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baixar_dados, "_TAMANHO_MAXIMO", 5)
    zip_ = criar_zip(tmp_path / "a.zip", {"online_retail_II.xlsx": CONTEUDO})
    with pytest.raises(DadosError, match="grande demais"):
        extrair_planilha(zip_, tmp_path / "online_retail_II.xlsx", sha256=HASH)


def test_nao_baixa_de_novo_se_o_arquivo_ja_confere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destino = tmp_path / "online_retail_II.xlsx"
    destino.write_bytes(CONTEUDO)
    monkeypatch.setattr(baixar_dados, "SHA256_PLANILHA", HASH)
    monkeypatch.setattr(baixar_dados.planilha_valida, "__defaults__", (destino, HASH))

    def nao_pode_baixar(*_: object) -> None:
        raise AssertionError("baixou de novo")

    monkeypatch.setattr(urllib.request, "urlretrieve", nao_pode_baixar)
    assert baixar(destino=destino) is False


def test_url_sem_https_e_recusada(tmp_path: Path) -> None:
    with pytest.raises(DadosError, match="https"):
        baixar(url="http://archive.ics.uci.edu/x.zip", destino=tmp_path / "x.xlsx")


def test_download_que_nao_e_zip_vira_erro_claro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def baixa_html(_url: str, caminho: Path) -> None:
        Path(caminho).write_text("<html>erro 500</html>", encoding="utf-8")

    monkeypatch.setattr(urllib.request, "urlretrieve", baixa_html)
    with pytest.raises(DadosError, match="zip válido"):
        baixar(destino=tmp_path / "online_retail_II.xlsx")
