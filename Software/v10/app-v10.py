"""Ponto único de inicialização da v10, para navegador e aplicativos móveis."""

from backend.app import app, iniciar_servidor

if __name__ == "__main__":
    iniciar_servidor()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
