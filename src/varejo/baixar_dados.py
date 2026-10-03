"""Baixa o dataset Online Retail II da UCI e confere o SHA-256 da planilha.

Uso:
    python -m varejo.baixar_dados

A planilha (45 MB) não vai para o git: este script a reproduz. Se o arquivo já existe
com o hash certo, não baixa de novo. Se o hash não bate, recusa e não deixa o arquivo
no lugar: um número do README calculado sobre outra versão do dataset seria um número
errado sem ninguém saber.

Fonte: https://archive.ics.uci.edu/dataset/502/online+retail+ii (licença CC BY 4.0).
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from varejo.config import PASTA_DADOS

URL_ZIP = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
NOME_PLANILHA = "online_retail_II.xlsx"
SHA256_PLANILHA = "bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980"
CAMINHO_PLANILHA = PASTA_DADOS / NOME_PLANILHA

# A planilha descompactada tem 45,6 MB. Um limite folgado protege contra um zip
# adulterado que se expande para gigabytes ("zip bomb").
_TAMANHO_MAXIMO = 200 * 1024 * 1024
TIMEOUT_SEGUNDOS = 60


class DadosError(RuntimeError):
    """Download ou conferência do dataset falhou."""


def sha256_arquivo(caminho: Path) -> str:
    """SHA-256 do arquivo, lido em blocos (não carrega 45 MB na memória de uma vez)."""
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def planilha_valida(caminho: Path = CAMINHO_PLANILHA, sha256: str = SHA256_PLANILHA) -> bool:
    return caminho.is_file() and sha256_arquivo(caminho) == sha256


def extrair_planilha(zip_: Path, destino: Path, sha256: str = SHA256_PLANILHA) -> None:
    """Extrai só a planilha esperada do zip e confere o hash antes de pô-la no destino.

    Lê o membro pelo nome exato, em vez de `extractall`: um nome com "../" dentro do zip
    não consegue escrever fora da pasta ("zip slip"). A extração vai para um arquivo
    temporário na mesma pasta e só é renomeada para o destino com o hash conferido.
    """
    with zipfile.ZipFile(zip_) as arquivo_zip:
        try:
            info = arquivo_zip.getinfo(NOME_PLANILHA)
        except KeyError:
            raise DadosError(f"O zip não contém {NOME_PLANILHA}.") from None
        if info.file_size > _TAMANHO_MAXIMO:
            raise DadosError(f"{NOME_PLANILHA} no zip tem {info.file_size} bytes: grande demais.")
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(".parcial")
        try:
            with arquivo_zip.open(info) as origem, temporario.open("wb") as saida:
                shutil.copyfileobj(origem, saida)
        except BaseException:
            temporario.unlink(missing_ok=True)  # cópia interrompida: não deixa lixo
            raise
    obtido = sha256_arquivo(temporario)
    if obtido != sha256:
        temporario.unlink()
        raise DadosError(
            f"SHA-256 de {NOME_PLANILHA} não confere: esperado {sha256}, veio {obtido}. "
            "A UCI pode ter publicado outra versão; os números do projeto valem para a "
            "versão esperada."
        )
    temporario.replace(destino)


def baixar(url: str = URL_ZIP, destino: Path = CAMINHO_PLANILHA) -> bool:
    """Garante a planilha no destino. Devolve True se baixou, False se já estava lá."""
    if planilha_valida(destino):
        return False
    if not url.startswith("https://"):
        raise DadosError(f"URL recusada (só https): {url}")
    with tempfile.TemporaryDirectory() as pasta:
        zip_ = Path(pasta) / "online_retail_ii.zip"
        # timeout: com a rede parada, falha em vez de esperar para sempre.
        with (
            urllib.request.urlopen(url, timeout=TIMEOUT_SEGUNDOS) as resposta,  # noqa: S310 (https validado acima)
            zip_.open("wb") as saida,
        ):
            shutil.copyfileobj(resposta, saida)
        try:
            extrair_planilha(zip_, destino)
        except zipfile.BadZipFile:
            raise DadosError("O arquivo baixado não é um zip válido.") from None
    return True


def main() -> int:
    try:
        baixou = baixar()
    except (DadosError, OSError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    estado = "baixada e conferida" if baixou else "já estava no lugar, hash conferido"
    print(f"{CAMINHO_PLANILHA}: {estado}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
