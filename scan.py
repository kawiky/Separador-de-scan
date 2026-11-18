import pytesseract
from pdf2image import convert_from_path
from separar_devolucoes import processar, salvar, separar_pdf
import sys
import os


#converte o pdf e, uma lista de imagens


if len(sys.argv) < 2:
    print("Uso correto: python meu_script.py caminho/do/arquivo.pdf")
    sys.exit(1)

# Captura o primeiro parâmetro informado depois do nome do script
caminho_pdf = sys.argv[1]

if os.path.exists(caminho_pdf):
    print(f"Processando o arquivo: {caminho_pdf}")
    # Segue para a extração do texto...
else:
    print(f"Erro: O arquivo '{caminho_pdf}' não existe.")

paginas = convert_from_path(caminho_pdf, dpi=300)

#processa cada pagina
"""para criar uma variavel sozinha para armezenar as paginas  """
paginas_uteis = ""

for numero, pagina_imagem in enumerate(paginas):
    #extari o texto da imagem
    config_customizada = r'--psm 6'
    texto_extraido = pytesseract.image_to_string(pagina_imagem, lang='por', config=config_customizada) 

    paginas_uteis += texto_extraido + "\n--- FIM DA PÁGINA ---\n"


from separar_devolucoes import processar, salvar, separar_pdf

registros, grupos = processar(paginas_uteis)      # texto = string com as páginas separadas por "--- FIM DA PÁGINA ---"

for r in registros:                       # informações de cada página
    print(r["pagina"], r["tipo"], r["empresa_nome"], r["cliente_id"], r["mes_ano"])

for g in grupos:                          # páginas de cada grupo
    print(g["empresa"], g["mes_ano"], g["cliente_nome"], g["paginas"])

salvar(registros, grupos, "saida")        # json + csv
separar_pdf("scan.pdf", grupos, "saida")  # um PDF por grupo







  

    