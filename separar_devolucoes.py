# -*- coding: utf-8 -*-
"""
Separa as páginas do texto extraído (OCR) por:
    EMPRESA que recebe a devolução  x  CLIENTE  x  MÊS/ANO

- O cliente NÃO precisa ser informado: ele é descoberto pelo CNPJ (8 primeiros dígitos)
  que aparece na nota e que NÃO é de uma das suas empresas.
- Cada informação encontrada fica salva junto com o número da página.

Uso:
    python separar_devolucoes.py texto.txt                  -> gera resultado.json e paginas.csv
    python separar_devolucoes.py texto.txt scan.pdf saida/  -> também gera um PDF por grupo (precisa do pypdf)
"""
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

# ════════════════════════════════════════════════════════════════
# 1. CONFIGURAÇÃO  (só isto precisa ser ajustado)
# ════════════════════════════════════════════════════════════════
SEPARADOR_PAGINA = "--- FIM DA PÁGINA ---"

# Raiz do CNPJ (8 primeiros dígitos) das SUAS empresas.
# Tudo que NÃO estiver aqui é tratado como cliente/fornecedor.
EMPRESAS_PROPRIAS = {"51281824"}

# Só para dar nome às pastas e ao relatório (opcional). Raiz do CNPJ -> nome.
NOMES_CNPJ = {
    "51281824": "TAINNA DECORACOES LTDA",
    "11766919": "KAN TAI IMPORTACAO E EXPORTACAO LTDA",
    
}

# ════════════════════════════════════════════════════════════════
# 2. VARIÁVEIS DE BUSCA (regex)
# ════════════════════════════════════════════════════════════════
# --- tipo da página -----------------------------------------------------
RE_AUTORIZACAO = re.compile(r"Autoriza[çc][ãa]o\s+de\s+Devolu", re.I)
RE_FICHA = re.compile(r"FICHA\s+DE\s+RECLAMA", re.I)
RE_DANFE = re.compile(
    r"DANFE|DOCUMENTO\s+AUXILIAR|[DP]ESTINAT[ÁA]RIO\s*/\s*REMETENTE"
    r"|C[ÁA]LCULO\s+DO\s+IMPOSTO|CHAVE\s+DE\s+ACESSO", re.I)

# --- CNPJ (com pontuação ou 14 dígitos corridos; tolera "," no lugar de ".") ---
RE_CNPJ = re.compile(
    r"(?<![\d.,])(\d{2})[.,]?(\d{3})[.,]?(\d{3})\s?/\s?\d{4}"   # 51.281.824/0001-18
    r"|(?<!\d)(\d{8})\d{6}(?!\d)")                              # 51281824000118
RE_TITULO_DESTINATARIO = re.compile(r"[DP]ESTINAT[ÁA]RIO\s*/\s*REMETENTE", re.I)

# --- número da NF -------------------------------------------------------
RE_NF_AUTORIZACAO = re.compile(r"Nota\s+Fiscal:\s*0*(\d+)", re.I)   # Nota Fiscal: 000012764
RE_NF_FICHA = re.compile(r"\bNOTA:\s*0*(\d+)", re.I)                # NOTA: 11517
RE_NF_DANFE = re.compile(r"\bN[.º°]\s*0*(\d{3,9})\b")               # N. 000012764
RE_COMPLEMENTO = re.compile(r"INFORMA[ÇC][ÕO]ES\s+COMPLEMENTARES|DADOS\s+ADICIONAIS", re.I)
RE_NUM_REFERENCIA = re.compile(r"(?<![\d.,/-])0*(\d{4,9})(?![\d/-]|[.,]\d)")  # nºs citados no complemento

# --- nome (só para batizar pastas; o agrupamento usa o CNPJ) -------------
RE_NOME_FICHA = re.compile(r"RECLAMANTE:\s*(.+)", re.I)
RE_NOME_AUTORIZACAO = re.compile(r"C[li]{2}ente:\s*\d+(?:\s+\d+)?\s*-\s*(.+)", re.I)  # "Cliente"/"Cilente"

# --- natureza / CFOP (para saber se é devolução e quem recebe) ----------
RE_NATUREZA = re.compile(r"NATUREZA\s+DA\s+OPERA[ÇC][ÃA]O(.{0,160})", re.I | re.S)
RE_DEVOLUCAO = re.compile(r"DEVOL|RETORNO\s+DE\s+MERCADORIA|EMISS[ÃA]O\s+ORIGINAL", re.I)
RE_CFOP = re.compile(r"(?<!\d)([1-7])[.,/ ]?(\d{3})(?!\d)\s*[|\[\]\sJ]*UN\b")  # CFOP fica antes da coluna "UN"
CFOPS_DEVOLUCAO = {
    "1201", "1202", "1203", "1204", "1208", "1209", "1410", "1411", "1412", "1413", "1660", "1661", "1662",
    "2201", "2202", "2203", "2204", "2208", "2209", "2410", "2411", "2412", "2413", "2660", "2661", "2662",
    "5201", "5202", "5208", "5209", "5210", "5410", "5411", "5412", "5413", "5660", "5661", "5662",
    "6201", "6202", "6208", "6209", "6210", "6410", "6411", "6412", "6413", "6660", "6661", "6662",
}

# --- datas (tolera barras perdidas pela OCR: 10092026) --------------------
RE_DATA = re.compile(r"(?<!\d)(\d{2})\D?(\d{2})\D?(20\d{2})(?!\d)")
RE_DATA_EMISSAO = re.compile(r"DATA\s*(?:D[EA]\s*)?EMISS[ÃA]O(.{0,350})", re.I | re.S)
RE_DATA_HORA_RODAPE = re.compile(r"(\d{2})/(\d{2})/(20\d{2})\s+\d{2}:\d{2}")   # autorização: 18/09/2026 09:18
RE_DATA_ABERTURA = re.compile(r"ABERTURA:\s*(\d{2})/(\d{2})/(20\d{2})", re.I)   # ficha de reclamação


# ════════════════════════════════════════════════════════════════
# 3. FUNÇÕES AUXILIARES
# ════════════════════════════════════════════════════════════════
CONHECIDOS = set(EMPRESAS_PROPRIAS) | set(NOMES_CNPJ)


def ajusta_raiz(r):
    """Corrige 1 dígito errado da OCR quando a raiz é quase igual a uma conhecida."""
    for k in CONHECIDOS:
        if len(k) == len(r) and sum(a != b for a, b in zip(r, k)) <= 1:
            return k
    return r


def raizes(txt):
    """Lista de raízes de CNPJ na ordem em que aparecem."""
    out = []
    for m in RE_CNPJ.finditer(txt):
        r = m.group(1) + m.group(2) + m.group(3) if m.group(1) else m.group(4)
        out.append(ajusta_raiz(r))
    return out


def mes_ano(dd, mm, aaaa):
    """Devolve 'AAAA-MM' se a data for válida."""
    try:
        if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
            return f"{aaaa}-{int(mm):02d}"
    except ValueError:
        pass
    return None


def primeira_data(txt):
    for m in RE_DATA.finditer(txt):
        r = mes_ano(*m.groups())
        if r:
            return r
    return None


def limpa_nome(s):
    return re.sub(r"[\s\d|]+$", "", s).strip()


def nome_seguro(s):
    return re.sub(r"[^\w\- ]", "", s).strip()[:60]


# ════════════════════════════════════════════════════════════════
# 4. ANÁLISE DE UMA PÁGINA
# ════════════════════════════════════════════════════════════════
def analisar_pagina(n, t):
    p = dict(pagina=n, tipo="outro", nf=None, refs=set(), cliente_cnpj=None,
             cliente_nome=None, empresa=None, data=None, devolucao=False)

    if RE_AUTORIZACAO.search(t):
        p["tipo"] = "autorizacao"
        m = RE_NF_AUTORIZACAO.search(t)
        p["nf"] = int(m.group(1)) if m else None
        m = RE_NOME_AUTORIZACAO.search(t)
        p["cliente_nome"] = limpa_nome(m.group(1)) if m else None
        datas = RE_DATA_HORA_RODAPE.findall(t)
        p["data"] = mes_ano(*datas[-1]) if datas else None

    elif RE_FICHA.search(t):
        p["tipo"] = "ficha"
        m = RE_NF_FICHA.search(t)
        p["nf"] = int(m.group(1)) if m else None
        m = RE_NOME_FICHA.search(t)
        p["cliente_nome"] = limpa_nome(m.group(1)) if m else None
        m = RE_DATA_ABERTURA.search(t)
        p["data"] = mes_ano(*m.groups()) if m else None

    elif RE_DANFE.search(t):
        p["tipo"] = "danfe"
        # emitente = CNPJs ANTES do título "DESTINATÁRIO/REMETENTE"; destinatário = DEPOIS
        titulo = RE_TITULO_DESTINATARIO.search(t)
        if titulo:
            antes, depois = raizes(t[:titulo.start()]), raizes(t[titulo.end():])
            emit = antes[0] if antes else None
            dest = depois[0] if depois else None
        else:
            todos = list(dict.fromkeys(raizes(t)))
            emit = todos[0] if todos else None
            dest = todos[1] if len(todos) > 1 else None

        m = RE_NATUREZA.search(t)
        natureza = m.group(1) if m else ""
        m = RE_CFOP.search(t)
        cfop = m.group(1) + m.group(2) if m else None
        m = RE_COMPLEMENTO.search(t)
        complemento = t[m.end():] if m else ""

        p["devolucao"] = bool(RE_DEVOLUCAO.search(natureza)) or cfop in CFOPS_DEVOLUCAO \
            or bool(RE_DEVOLUCAO.search(complemento))

        # nº da NF só vale quando a nota é emitida por uma empresa sua
        if emit is None or emit in EMPRESAS_PROPRIAS:
            m = RE_NF_DANFE.search(t)
            p["nf"] = int(m.group(1)) if m else None

        # data de emissão
        m = RE_DATA_EMISSAO.search(t)
        p["data"] = (primeira_data(m.group(1)) if m else None) or primeira_data(t)

        if p["devolucao"]:
            # CFOP 1/2/3 = entrada própria (quem recebe é o emitente); 5/6/7 = saída (recebe o destinatário)
            if cfop:
                entrada = cfop[0] in "123"
            else:
                entrada = bool(re.search("DEVOL", natureza, re.I) and re.search("VEND", natureza, re.I))
            recebe, outro = (emit, dest) if entrada else (dest, emit)
            if recebe is None and entrada:
                recebe = sorted(EMPRESAS_PROPRIAS)[0]
            p["empresa"] = recebe
            p["cliente_cnpj"] = next((c for c in (outro, recebe) if c and c not in EMPRESAS_PROPRIAS), None)
            p["refs"] = {int(x) for x in RE_NUM_REFERENCIA.findall(complemento)}
        else:
            p["cliente_cnpj"] = next((c for c in (dest, emit) if c and c not in EMPRESAS_PROPRIAS), None)
    return p


# ════════════════════════════════════════════════════════════════
# 5. LIGAÇÃO ENTRE PÁGINAS (quem pertence ao mesmo cliente)
# ════════════════════════════════════════════════════════════════
class Uniao:
    def __init__(self, n):
        self.pai = list(range(n))
        self.cnpjs = [set() for _ in range(n)]

    def raiz(self, x):
        while self.pai[x] != x:
            self.pai[x] = self.pai[self.pai[x]]
            x = self.pai[x]
        return x

    def une(self, a, b, guardar=False):
        ra, rb = self.raiz(a), self.raiz(b)
        if ra == rb:
            return True
        if guardar and self.cnpjs[ra] and self.cnpjs[rb] and self.cnpjs[ra].isdisjoint(self.cnpjs[rb]):
            return False   # clientes diferentes: não junta
        self.pai[rb] = ra
        self.cnpjs[ra] |= self.cnpjs[rb]
        return True


def processar(texto):
    paginas = texto.split(SEPARADOR_PAGINA)
    if paginas and not paginas[-1].strip():
        paginas.pop()
    info = [analisar_pagina(i + 1, t) for i, t in enumerate(paginas)]

    uf = Uniao(len(info))
    for i, p in enumerate(info):
        if p["cliente_cnpj"]:
            uf.cnpjs[i].add(p["cliente_cnpj"])

    # (a) mesmo número de NF (autorização/ficha <-> DANFE; folha 1/2 <-> folha 2/2)
    por_nf = defaultdict(list)
    for i, p in enumerate(info):
        if p["nf"]:
            por_nf[p["nf"]].append(i)
    for idx in por_nf.values():
        for j in idx[1:]:
            uf.une(idx[0], j)

    # (b) a NF de devolução cita a NF de venda no campo de informações complementares
    for i, p in enumerate(info):
        for r in p["refs"]:
            if r in por_nf:
                uf.une(i, por_nf[r][0])

    # (c) ordem do scan: autorização/ficha abre o grupo; as páginas seguintes entram nele
    #     desde que o CNPJ do cliente não seja diferente
    ancora = None
    for i, p in enumerate(info):
        if p["tipo"] in ("autorizacao", "ficha"):
            ancora = i
        elif p["tipo"] == "outro" and i > 0:
            uf.une(i - 1, i)             # página sem nada reconhecível: fica com a anterior
        elif ancora is not None:
            uf.une(ancora, i, guardar=True)

    # ── resolve cada grupo ──
    comps = defaultdict(list)
    for i in range(len(info)):
        comps[uf.raiz(i)].append(i)

    ordem_tipo = {"ficha": 0, "autorizacao": 1, "danfe": 2, "outro": 3}
    registros = []
    for gid, idxs in enumerate(sorted(comps.values(), key=min), start=1):
        pg = sorted((info[i] for i in idxs), key=lambda x: ordem_tipo[x["tipo"]])

        c = Counter(p["cliente_cnpj"] for p in pg if p["cliente_cnpj"])
        cliente_cnpj = c.most_common(1)[0][0] if c else None
        nome = next((p["cliente_nome"] for p in pg if p["cliente_nome"]), None)
        cliente_id = cliente_cnpj or (("NOME_" + nome_seguro(nome).upper().replace(" ", "_")) if nome else "SEM_CLIENTE")
        cliente_nome = nome or NOMES_CNPJ.get(cliente_cnpj) or (f"CNPJ_{cliente_cnpj}" if cliente_cnpj else "SEM_CLIENTE")

        e = Counter(p["empresa"] for p in pg if p["empresa"])
        empresa = e.most_common(1)[0][0] if e else None

        data = (next((p["data"] for p in pg if p["tipo"] == "danfe" and p["devolucao"] and p["data"]), None)
                or next((p["data"] for p in pg if p["tipo"] == "autorizacao" and p["data"]), None)
                or next((p["data"] for p in pg if p["tipo"] == "ficha" and p["data"]), None)
                or next((p["data"] for p in pg if p["data"]), None))

        for i in sorted(idxs):
            p = info[i]
            registros.append({
                "pagina": p["pagina"],
                "tipo": p["tipo"],
                "nf": p["nf"],
                "cliente_id": cliente_id,
                "cliente_nome": cliente_nome,
                "empresa_cnpj": empresa,
                "empresa_nome": NOMES_CNPJ.get(empresa, empresa) if empresa else "EMPRESA_NAO_IDENTIFICADA",
                "mes_ano": data or "SEM_DATA",
                "dossie": gid,
                # o que foi encontrado DIRETAMENTE nesta página (o resto foi herdado do dossiê)
                "achado_na_pagina": [k for k in ("nf", "cliente_cnpj", "cliente_nome", "empresa", "data") if p[k]],
            })
    registros.sort(key=lambda r: r["pagina"])

    # ── agrupa por EMPRESA x CLIENTE x MÊS/ANO ──
    grupos = defaultdict(lambda: {"paginas": [], "cliente_nome": None})
    for r in registros:
        g = grupos[(r["empresa_nome"], r["cliente_id"], r["mes_ano"])]
        g["paginas"].append(r["pagina"])
        g["cliente_nome"] = g["cliente_nome"] or r["cliente_nome"]
    lista = []
    for (emp, cid, mes), g in sorted(grupos.items()):
        lista.append({
            "empresa": emp, "cliente_id": cid, "cliente_nome": g["cliente_nome"], "mes_ano": mes,
            "paginas": sorted(g["paginas"]),
            "pasta": os.path.join(nome_seguro(emp), mes, nome_seguro(g["cliente_nome"]) + "_" + cid),
        })
    return registros, lista


# ════════════════════════════════════════════════════════════════
# 6. SAÍDAS
# ════════════════════════════════════════════════════════════════
def salvar(registros, grupos, pasta="."):
    # Defina aqui a pasta onde quer guardar só o JSON e o CSV
    pasta_relatorios = r"C:\Meu Drive\SEPARAÇÃO DE PDF\relatorios"
    os.makedirs(pasta_relatorios, exist_ok=True)
    
    with open(os.path.join(pasta_relatorios, "resultado.json"), "w", encoding="utf-8") as f:
        json.dump({"paginas": registros, "grupos": grupos}, f, ensure_ascii=False, indent=2)
        
    with open(os.path.join(pasta_relatorios, "paginas.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["pagina", "tipo", "nf", "empresa", "cliente_id", "cliente_nome", "mes_ano", "achado_na_pagina"])
        for r in registros:
            w.writerow([r["pagina"], r["tipo"], r["nf"] or "", r["empresa_nome"], r["cliente_id"],
                        r["cliente_nome"], r["mes_ano"], ",".join(r["achado_na_pagina"])])


def separar_pdf(pdf, grupos, pasta):
    from pypdf import PdfReader, PdfWriter      # pip install pypdf
    leitor = PdfReader(pdf)
    for g in grupos:
        destino = os.path.join(pasta, g["pasta"])
        os.makedirs(destino, exist_ok=True)
        w = PdfWriter()
        for n in g["paginas"]:
            w.add_page(leitor.pages[n - 1])
        with open(os.path.join(destino, "devolucao.pdf"), "wb") as f:
            w.write(f)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as f:
        texto = f.read()
    regs, grps = processar(texto)
    saida = sys.argv[3] if len(sys.argv) > 3 else "."
    salvar(regs, grps, saida)
    for g in grps:
        aviso = "  <-- CONFERIR" if "SEM_" in (g["cliente_id"] + g["mes_ano"]) or "NAO_IDENT" in g["empresa"] else ""
        print(f'{g["empresa"]} | {g["mes_ano"]} | {g["cliente_nome"]} ({g["cliente_id"]}) -> páginas {g["paginas"]}{aviso}')
    if len(sys.argv) > 2 and sys.argv[2]:
        separar_pdf(sys.argv[2], grps, saida)
