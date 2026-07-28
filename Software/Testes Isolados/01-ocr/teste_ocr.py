import easyocr
import cv2

# Nome da imagem que você vai testar
IMAGEM = 'etiqueta_teste.jpg'

print("Iniciando EasyOCR...")
reader = easyocr.Reader(['pt', 'en'], gpu=False)

try:
    print(f"Lendo o arquivo: {IMAGEM}")
    img = cv2.imread(IMAGEM)
    
    # Tratamento de imagem para melhorar a leitura
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    adjusted = cv2.convertScaleAbs(gray, alpha=1.5, beta=10)
    processed_img = cv2.threshold(adjusted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    
    print("Extraindo dados...")
    resultados = reader.readtext(processed_img, detail=0)
    
    print("\n--- TEXTOS ENCONTRADOS ---")
    for texto in resultados:
        print(f"-> {texto}")
    print("--------------------------")
except Exception as e:
    print(f"Erro ao processar imagem: {e}")