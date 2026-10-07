import cv2
import easyocr

# Imagem utilizada no teste.
# Coloque um arquivo chamado "teste.jpg" na mesma pasta ou altere este valor para o nome desejado.
IMAGEM = "teste.jpg"

print("Iniciando EasyOCR...")

# Inicializa o leitor OCR com suporte a português e inglês.
# gpu=False permite executar o teste utilizando apenas a CPU.
reader = easyocr.Reader(["pt", "en"], gpu=False)

try:
    print(f"Lendo o arquivo: {IMAGEM}")

    # Carrega a imagem utilizando o OpenCV.
    img = cv2.imread(IMAGEM)

    # Verifica se a imagem foi encontrada corretamente.
    if img is None:
        raise FileNotFoundError(
            f"Não foi possível abrir a imagem '{IMAGEM}'."
        )

    # Converte a imagem para escala de cinza.
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Aumenta o contraste da imagem para facilitar a diferenciação entre texto e fundo.
    adjusted = cv2.convertScaleAbs(
        gray,
        alpha=1.5,
        beta=10
    )

    # Aplica limiarização automática utilizando o método de Otsu.
    processed_img = cv2.threshold(
        adjusted,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]

    print("Extraindo dados...")

    # detail=0 faz o EasyOCR retornar apenas os textos reconhecidos, sem coordenadas ou níveis de confiança.
    resultados = reader.readtext(
        processed_img,
        detail=0
    )

    print("\n--- TEXTOS ENCONTRADOS ---")

    if resultados:
        for texto in resultados:
            print(f"-> {texto}")
    else:
        print("Nenhum texto identificado.")

    print("--------------------------")

except Exception as erro:
    print(f"Erro ao processar imagem: {erro}")
