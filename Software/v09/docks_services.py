import datetime
import json
import math
import textwrap

STATUS_AGUARDANDO = "aguardando"
STATUS_EM_RETIRADA = "em_retirada"
STATUS_RETIRADA = "retirada"
STATUS_EM_ANDAMENTO = "em_andamento"
STATUS_CONCLUIDO = "concluido"
STATUS_INTERROMPIDO = "interrompido"
STATUS_INICIANDO = "iniciando"
STATUS_GRAVANDO = "gravando"
STATUS_FALHA = "falha"
STATUS_PENDENTE = "pendente"
STATUS_PROCESSANDO = "processando"

def resposta_api(success, message, data=None, code="OK"):
    return {
        "success": bool(success),
        "message": str(message or ""),
        "data": data,
        "code": str(code),
    }

def codigo_erro_http(status):
    return {
        400: "DADOS_INVALIDOS",
        401: "NAO_AUTORIZADO",
        403: "ACESSO_NEGADO",
        404: "NAO_ENCONTRADO",
        409: "CONFLITO",
        413: "ARQUIVO_MUITO_GRANDE",
        429: "MUITAS_TENTATIVAS",
        500: "ERRO_INTERNO",
        503: "SERVICO_INDISPONIVEL",
    }.get(status, "ERRO")

def envolver_resposta_v1(payload, status):
    if isinstance(payload, dict) and {"success", "message", "data", "code"} <= set(payload):
        return payload
    payload = payload if isinstance(payload, dict) else {"resultado": payload}
    sucesso = 200 <= status < 400 and payload.get("success", True) is not False
    mensagem = (
        payload.get("message")
        or payload.get("error")
        or ("Operação concluída." if sucesso else "Não foi possível concluir a operação.")
    )
    codigo = payload.get("code") or ("OK" if sucesso else codigo_erro_http(status))
    dados = {k: v for k, v in payload.items() if k not in {"success", "message", "error", "code"}}
    return resposta_api(sucesso, mensagem, dados or None, codigo)

def dias_desde(data_texto):
    try:
        data = datetime.datetime.strptime(data_texto, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return 0
    return max(0, (datetime.datetime.now() - data).days)

def setor_prateleira(prateleira):
    try:
        numero = int(str(prateleira).upper().replace("PA", ""))
    except ValueError:
        return "desconhecido"
    if numero <= 20:
        return "pequeno"
    if numero <= 40:
        return "médio"
    return "grande"

def serializar_payload(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

def desserializar_payload(payload):
    try:
        return json.loads(payload or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}

def atraso_fila(tentativas):
    return min(900, int(math.pow(2, max(0, tentativas))) * 15)

def _pdf_texto(valor):
    texto = str(valor if valor not in (None, "") else "-")
    texto = texto.encode("latin-1", "replace").decode("latin-1")
    return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

def _pdf_quebrar(valor, largura, tamanho=7.4):
    limite = max(4, int((largura - 10) / (tamanho * 0.52)))
    linhas = textwrap.wrap(
        str(valor if valor not in (None, "") else "-"),
        width=limite,
        break_long_words=True,
        break_on_hyphens=True,
    ) or ["-"]
    if len(linhas) > 9:
        linhas = linhas[:9]
        linhas[-1] = linhas[-1][:-3] + "..."
    return linhas

def _pdf_comando_texto(texto, x, y, tamanho, fonte="F1", cor=(0.12, 0.16, 0.24)):
    return (
        f"BT {cor[0]:.3f} {cor[1]:.3f} {cor[2]:.3f} rg "
        f"/{fonte} {tamanho:.1f} Tf {x:.2f} {y:.2f} Td ({_pdf_texto(texto)}) Tj ET"
    )

def gerar_pdf(titulo, colunas, linhas, gerado_em):
    paisagem = len(colunas) >= 6
    largura_pagina, altura_pagina = (842, 595) if paisagem else (595, 842)
    margem = 32
    largura_tabela = largura_pagina - margem * 2
    amostra = linhas[:250]
    pesos = []
    for indice, coluna in enumerate(colunas):
        maior = max(
            [len(str(coluna))]
            + [len(str(linha[indice] if indice < len(linha) else "")) for linha in amostra]
        )
        pesos.append(max(5, min(34, maior)))
    soma_pesos = sum(pesos) or 1
    larguras = [largura_tabela * peso / soma_pesos for peso in pesos]
    minimo = 44 if paisagem else 48
    deficit = sum(max(0, minimo - largura) for largura in larguras)
    if deficit:
        disponivel = sum(max(0, largura - minimo) for largura in larguras)
        larguras = (
            [
                (
                    minimo
                    if largura < minimo
                    else largura - deficit * ((largura - minimo) / disponivel)
                )
                for largura in larguras
            ]
            if disponivel
            else [largura_tabela / len(colunas)] * len(colunas)
        )
    registros = []
    for linha in linhas:
        celulas = [
            _pdf_quebrar(linha[i] if i < len(linha) else "-", larguras[i])
            for i in range(len(colunas))
        ]
        altura = max(22, max(len(celula) for celula in celulas) * 9 + 8)
        registros.append((celulas, altura))
    paginas = []
    pagina = []
    restante = altura_pagina - 165
    for registro in registros:
        if pagina and registro[1] > restante:
            paginas.append(pagina)
            pagina = []
            restante = altura_pagina - 165
        pagina.append(registro)
        restante -= registro[1]
    if pagina or not paginas:
        paginas.append(pagina)
    objetos = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    }
    ids_paginas = []
    for indice_pagina, registros_pagina in enumerate(paginas):
        conteudo_id = 5 + indice_pagina * 2
        pagina_id = conteudo_id + 1
        ids_paginas.append(pagina_id)
        comandos = [
            f"0.063 0.098 0.169 rg 0 {altura_pagina - 78} {largura_pagina} 78 re f",
            f"0.145 0.388 0.922 rg 0 {altura_pagina - 82} {largura_pagina} 4 re f",
            _pdf_comando_texto("DOCKS", margem, altura_pagina - 30, 9, "F2", (0.45, 0.68, 1)),
            _pdf_comando_texto(titulo, margem, altura_pagina - 52, 17, "F2", (1, 1, 1)),
            _pdf_comando_texto(
                f"Gerado em {gerado_em}", margem, altura_pagina - 68, 7.5, "F1", (0.78, 0.83, 0.91)
            ),
            f"0.145 0.388 0.922 rg {margem} {altura_pagina - 112} {largura_tabela} 27 re f",
        ]
        x = margem
        for coluna, largura in zip(colunas, larguras):
            comandos.append(
                _pdf_comando_texto(coluna, x + 5, altura_pagina - 102, 7.2, "F2", (1, 1, 1))
            )
            x += largura
        y = altura_pagina - 112
        if not registros_pagina:
            comandos.append(
                _pdf_comando_texto(
                    "Nenhum registro encontrado.", margem + 8, y - 25, 9, "F1", (0.38, 0.43, 0.52)
                )
            )
        for indice_registro, (celulas, altura) in enumerate(registros_pagina):
            y -= altura
            if indice_registro % 2 == 0:
                comandos.append(f"0.965 0.973 0.988 rg {margem} {y} {largura_tabela} {altura} re f")
            comandos.append(
                f"0.820 0.847 0.890 RG 0.45 w {margem} {y} {largura_tabela} {altura} re S"
            )
            x = margem
            for celula, largura in zip(celulas, larguras):
                comandos.append(f"0.820 0.847 0.890 RG 0.35 w {x} {y} m {x} {y + altura} l S")
                linha_y = y + altura - 12
                for texto_linha in celula:
                    comandos.append(_pdf_comando_texto(texto_linha, x + 5, linha_y, 7.4))
                    linha_y -= 9
                x += largura
            comandos.append(
                f"0.820 0.847 0.890 RG 0.35 w {margem + largura_tabela} {y} m {margem + largura_tabela} {y + altura} l S"
            )
        comandos.extend(
            [
                _pdf_comando_texto(
                    f"Página {indice_pagina + 1} de {len(paginas)}",
                    largura_pagina - margem - 62,
                    18,
                    7.5,
                    "F1",
                    (0.38, 0.43, 0.52),
                ),
                _pdf_comando_texto(
                    "Relatório gerado pelo sistema Docks", margem, 18, 7.5, "F1", (0.38, 0.43, 0.52)
                ),
            ]
        )
        stream = "\n".join(comandos).encode("latin-1", "replace")
        objetos[conteudo_id] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        objetos[pagina_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {largura_pagina} {altura_pagina}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {conteudo_id} 0 R >>"
        ).encode()
    referencias = b" ".join(f"{pagina_id} 0 R".encode() for pagina_id in ids_paginas)
    objetos[2] = (
        b"<< /Type /Pages /Kids ["
        + referencias
        + b"] /Count "
        + str(len(ids_paginas)).encode()
        + b" >>"
    )
    saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {0: 0}
    for objeto_id in range(1, max(objetos) + 1):
        offsets[objeto_id] = len(saida)
        saida.extend(f"{objeto_id} 0 obj\n".encode())
        saida.extend(objetos[objeto_id])
        saida.extend(b"\nendobj\n")
    xref = len(saida)
    saida.extend(f"xref\n0 {max(objetos) + 1}\n".encode())
    saida.extend(b"0000000000 65535 f \n")
    for objeto_id in range(1, max(objetos) + 1):
        saida.extend(f"{offsets[objeto_id]:010d} 00000 n \n".encode())
    saida.extend(
        f"trailer\n<< /Size {max(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(saida)
