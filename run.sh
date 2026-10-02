#!/usr/bin/env bash
# =============================================================================
# PopeNails Loyalty Card - Script de Inicio
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
VENV_DIR=".venv"

echo "💅 ========================================================"
echo "💅  PopeNails Studio - Backend Servidor de Fidelización"
echo "💅 ========================================================"

# 1. Verificar instalación de Python 3
if ! command -v python3 &>/dev/null; then
    echo "❌ Error: Python 3 no está instalado en el sistema."
    exit 1
fi

# 2. Configurar entorno virtual si no existe
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creando entorno virtual en $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# 3. Activar entorno virtual
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# 4. Asegurar dependencias instaladas
if ! python3 -c "import fastapi, uvicorn, pydantic" &>/dev/null; then
    echo "⬇️  Instalando dependencias desde requirements.txt..."
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    echo "✅ Dependencias instaladas correctamente."
fi

# 5. Iniciar servidor con recarga en caliente
echo ""
echo "🚀 Servidor iniciado con éxito:"
echo "   - Local URL:         http://localhost:$PORT"
echo "   - API Tarjeta:       http://localhost:$PORT/api/card"
echo "   - API Escaneo:       http://localhost:$PORT/api/scan (POST)"
echo "   - Swagger Docs:      http://localhost:$PORT/docs"
echo "   - Assets estáticos:  http://localhost:$PORT/assets/"
echo "   - Public estáticos:  http://localhost:$PORT/public/"
echo ""
echo "Presiona Ctrl+C para detener el servidor."
echo "--------------------------------------------------------"

exec uvicorn server:app --host "$HOST" --port "$PORT" --reload
