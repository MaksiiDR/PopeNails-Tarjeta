import os
import sys
from pathlib import Path

# Agregar la raíz del proyecto al sys.path para importar server.py
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Cargar variables de entorno locales si existen
try:
    from dotenv import load_dotenv
    env_file = root_dir / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
except ImportError:
    pass

# Exportar la app FastAPI para Vercel Serverless Function
from server import app
