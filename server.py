#!/usr/bin/env python3
"""
=============================================================================
PopeNails Loyalty Card - Backend Server
=============================================================================
Servidor de desarrollo y producción ligero para PopeNails.
Proporciona:
  - Servido de archivos estáticos (public/ y assets/)
  - GET  /api/card  -> Estado actual de la tarjeta de fidelización
  - POST /api/scan  -> Simula escaneo en mostrador para sellar/validar tarjeta
  - POST /api/reset -> Reinicia la tarjeta al estado inicial de pruebas
  - GET  /health    -> Verificación de salud del servicio
  - Swagger UI interactiva en /docs
=============================================================================
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Si el usuario ejecuta directamente con python del sistema pero existe .venv local,
# re-ejecutar automáticamente usando el entorno virtual.
current_dir = Path(__file__).resolve().parent
venv_python = current_dir / ".venv" / "bin" / "python"
if sys.executable != str(venv_python) and venv_python.exists():
    try:
        import fastapi
    except ImportError:
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

# Inicialización de la aplicación FastAPI
app = FastAPI(
    title="PopeNails Loyalty Card API",
    description="Backend de fidelización y tarjeta de puntos para PopeNails Studio",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configuración de CORS para permitir consumo desde cualquier origen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Estado de la Tarjeta en Memoria (Simulación de Base de Datos)
# ---------------------------------------------------------------------------
INITIAL_CARD_STATE = {
    "cliente": "Nueva Clienta",
    "puntos": 0,
    "sellos_actuales": 0,
    "total_sellos": 10,
    "qr_code": "POPENAILS-VIP-7892",
    "nivel": "Bienvenida",
    "premio_disponible": False,
    "ultimo_escaneo": None
}

card_state = dict(INITIAL_CARD_STATE)

# ---------------------------------------------------------------------------
# Modelos Pydantic para Validación de Datos
# ---------------------------------------------------------------------------
class CardResponse(BaseModel):
    cliente: str = Field(..., examples=["Nueva Clienta"])
    puntos: int = Field(..., examples=[0])
    sellos_actuales: int = Field(..., examples=[0])
    total_sellos: int = Field(..., examples=[10])
    qr_code: str = Field(..., examples=["POPENAILS-VIP-7892"])
    nivel: Optional[str] = Field("Bienvenida", examples=["Bienvenida"])
    premio_disponible: Optional[bool] = Field(False, examples=[False])
    ultimo_escaneo: Optional[str] = Field(None, examples=["2026-10-02T18:30:00"])


class ScanRequest(BaseModel):
    qr_code: Optional[str] = Field(None, description="Código QR escaneado en el mostrador")
    action: Optional[str] = Field("add_stamp", description="Acción a realizar: 'add_stamp', 'redeem', 'reset'")
    sellos: Optional[int] = Field(1, ge=1, le=10, description="Cantidad de sellos a agregar")


class ScanResponse(BaseModel):
    status: str
    message: str
    card: CardResponse
    sellos_agregados: int
    premio_desbloqueado: bool
    timestamp: str

# ---------------------------------------------------------------------------
# Endpoints de la API
# ---------------------------------------------------------------------------

@app.get("/api/card", response_model=CardResponse, summary="Obtener estado de la tarjeta")
def get_card():
    """
    Retorna los datos de fidelización del cliente actual:
    - Nombre del cliente
    - Puntos acumulados
    - Sellos actuales y total de sellos
    - Código QR único para validación
    """
    return CardResponse(
        cliente=card_state["cliente"],
        puntos=card_state["puntos"],
        sellos_actuales=card_state["sellos_actuales"],
        total_sellos=card_state["total_sellos"],
        qr_code=card_state["qr_code"],
        nivel=card_state.get("nivel", "Gold VIP"),
        premio_disponible=card_state.get("premio_disponible", False),
        ultimo_escaneo=card_state.get("ultimo_escaneo")
    )


@app.post("/api/scan", response_model=ScanResponse, summary="Escanear tarjeta en mostrador")
def scan_card(payload: Optional[ScanRequest] = None):
    """
    Simula el escaneo en el mostrador de PopeNails:
    - Valida el código QR si se especifica
    - Agrega sello(s) a la tarjeta
    - Incrementa puntos (+50 pts por sello)
    - Desbloquea premio al alcanzar 10 sellos (+200 pts bonus)
    - Si ya se completó y se vuelve a sellar, reinicia ciclo conservando puntos
    """
    if payload is None:
        payload = ScanRequest()

    # Validación de QR si se envía
    if payload.qr_code and payload.qr_code.strip() != card_state["qr_code"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"QR inválido '{payload.qr_code}'. Código esperado: {card_state['qr_code']}"
        )

    now_iso = datetime.now().isoformat()
    action = payload.action or "add_stamp"
    sellos_agregados = 0
    premio_desbloqueado = False

    if action == "reset":
        card_state.clear()
        card_state.update(INITIAL_CARD_STATE)
        card_state["ultimo_escaneo"] = now_iso
        message = "Tarjeta reiniciada al estado predeterminado de pruebas."
    elif action == "redeem":
        if not card_state["premio_disponible"] and card_state["sellos_actuales"] < card_state["total_sellos"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No tienes un premio pendiente por canjear."
            )
        card_state["sellos_actuales"] = 0
        card_state["premio_disponible"] = False
        card_state["ultimo_escaneo"] = now_iso
        message = "¡Premio canjeado con éxito! Se ha renovado tu tarjeta para una nueva ronda."
    else:  # add_stamp
        sellos_a_sumar = payload.sellos if payload.sellos is not None else 1
        sellos_actuales = card_state["sellos_actuales"]
        total_sellos = card_state["total_sellos"]

        # Si ya estaba llena y se escanea de nuevo, cicla a una nueva tarjeta
        if sellos_actuales >= total_sellos:
            sellos_actuales = 0
            card_state["premio_disponible"] = False

        nuevo_total = sellos_actuales + sellos_a_sumar
        sellos_agregados = sellos_a_sumar

        # Puntos por visita
        puntos_ganados = 50 * sellos_a_sumar
        card_state["puntos"] += puntos_ganados

        if nuevo_total >= total_sellos:
            card_state["sellos_actuales"] = total_sellos
            card_state["premio_disponible"] = True
            premio_desbloqueado = True
            card_state["puntos"] += 200  # Bono por completar
            message = (
                f"🎉 ¡Felicidades! Completaste los {total_sellos} sellos. "
                "¡Tienes 1 servicio gratis o descuento VIP disponible! (+200 pts bonus)"
            )
        else:
            card_state["sellos_actuales"] = nuevo_total
            message = (
                f"💅 ¡Sello agregado con éxito! Llevas {card_state['sellos_actuales']} "
                f"de {total_sellos} sellos. (+{puntos_ganados} pts acumulados)"
            )

        card_state["ultimo_escaneo"] = now_iso

    card_obj = CardResponse(
        cliente=card_state["cliente"],
        puntos=card_state["puntos"],
        sellos_actuales=card_state["sellos_actuales"],
        total_sellos=card_state["total_sellos"],
        qr_code=card_state["qr_code"],
        nivel=card_state.get("nivel", "Gold VIP"),
        premio_disponible=card_state.get("premio_disponible", False),
        ultimo_escaneo=card_state.get("ultimo_escaneo")
    )

    return ScanResponse(
        status="success",
        message=message,
        card=card_obj,
        sellos_agregados=sellos_agregados,
        premio_desbloqueado=premio_desbloqueado,
        timestamp=now_iso
    )


@app.post("/api/reset", summary="Reiniciar tarjeta a valores iniciales de prueba")
def reset_card():
    """Reinicia la tarjeta a los valores iniciales para facilitar pruebas del frontend."""
    card_state.clear()
    card_state.update(INITIAL_CARD_STATE)
    return {
        "status": "success",
        "message": "Tarjeta reiniciada exitosamente",
        "card": card_state
    }


@app.get("/health", summary="Health check")
def health_check():
    return {
        "status": "ok",
        "service": "PopeNails Backend Server",
        "timestamp": datetime.now().isoformat()
    }


# ---------------------------------------------------------------------------
# Manejo y Servido de Archivos Estáticos
# ---------------------------------------------------------------------------
public_path = current_dir / "public"
assets_path = current_dir / "assets"

if assets_path.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

if public_path.exists():
    app.mount("/public", StaticFiles(directory=str(public_path)), name="public")


@app.get("/", response_class=HTMLResponse, summary="Página principal o Dashboard de pruebas")
def serve_index():
    """
    Sirve el index.html de public/ o de la raíz si existe.
    Si no existe aún, muestra una interfaz de prueba para desarrolladores.
    """
    public_index = public_path / "index.html"
    root_index = current_dir / "index.html"

    if public_index.exists():
        return FileResponse(str(public_index))
    if root_index.exists():
        return FileResponse(str(root_index))

    # Plantilla de bienvenida y test interactivo mientras el frontend se integra
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PopeNails - Backend API</title>
        <style>
            :root {{
                --bg: #0f172a;
                --card-bg: #1e293b;
                --primary: #f43f5e;
                --primary-hover: #e11d48;
                --accent: #fb7185;
                --text: #f8fafc;
                --muted: #94a3b8;
                --border: #334155;
            }}
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background: var(--bg);
                color: var(--text);
                display: flex;
                flex-direction: column;
                align-items: center;
                min-height: 100vh;
                padding: 2rem 1rem;
            }}
            .container {{
                max-width: 650px;
                width: 100%;
                background: var(--card-bg);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 2rem;
                box-shadow: 0 10px 30px rgba(0,0,0,0.4);
            }}
            .brand {{
                text-align: center;
                margin-bottom: 1.5rem;
            }}
            .brand h1 {{
                font-size: 1.8rem;
                background: linear-gradient(135deg, #fb7185, #f43f5e);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 0.25rem;
            }}
            .badge {{
                display: inline-block;
                background: rgba(244, 63, 94, 0.15);
                color: var(--accent);
                padding: 0.2rem 0.6rem;
                border-radius: 20px;
                font-size: 0.8rem;
                font-weight: 600;
                margin-top: 0.5rem;
            }}
            .card-preview {{
                background: #0b1120;
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 1.25rem;
                margin: 1.5rem 0;
            }}
            .stamps-bar {{
                display: flex;
                gap: 6px;
                margin: 1rem 0;
                flex-wrap: wrap;
                justify-content: center;
            }}
            .stamp {{
                width: 38px;
                height: 38px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1rem;
                background: #334155;
                color: #64748b;
                border: 2px dashed #475569;
                transition: all 0.3s ease;
            }}
            .stamp.active {{
                background: linear-gradient(135deg, #f43f5e, #e11d48);
                color: #fff;
                border: 2px solid #fda4af;
                box-shadow: 0 0 12px rgba(244, 63, 94, 0.5);
            }}
            .actions {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 0.75rem;
                margin-top: 1rem;
            }}
            button {{
                cursor: pointer;
                border: none;
                padding: 0.8rem 1.2rem;
                border-radius: 8px;
                font-weight: 600;
                font-size: 0.9rem;
                transition: background 0.2s, transform 0.1s;
            }}
            button:active {{ transform: scale(0.98); }}
            .btn-primary {{
                background: var(--primary);
                color: white;
            }}
            .btn-primary:hover {{ background: var(--primary-hover); }}
            .btn-secondary {{
                background: #334155;
                color: var(--text);
            }}
            .btn-secondary:hover {{ background: #475569; }}
            .links {{
                margin-top: 1.5rem;
                display: flex;
                justify-content: center;
                gap: 1.5rem;
                font-size: 0.85rem;
            }}
            .links a {{
                color: var(--accent);
                text-decoration: none;
            }}
            .links a:hover {{ text-decoration: underline; }}
            pre {{
                background: #020617;
                border-radius: 8px;
                padding: 1rem;
                font-size: 0.8rem;
                overflow-x: auto;
                color: #38bdf8;
                margin-top: 1rem;
                max-height: 160px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="brand">
                <h1>PopeNails Studio</h1>
                <p style="color: var(--muted); font-size: 0.9rem;">Backend de Fidelización y Tarjeta Digital Activo</p>
                <span class="badge">API v1.0 • FastAPI</span>
            </div>

            <div class="card-preview">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong id="client-name" style="font-size: 1.1rem;">Nueva Clienta</strong>
                    <span id="points-badge" style="color: #38bdf8; font-weight: bold;">0 pts</span>
                </div>
                <div style="font-size: 0.8rem; color: var(--muted); margin-top: 4px;">
                    QR: <code id="qr-val">POPENAILS-VIP-7892</code>
                </div>

                <div class="stamps-bar" id="stamps-container"></div>
                
                <p id="status-msg" style="text-align:center; font-size: 0.85rem; color: #a7f3d0; min-height: 1.2rem;"></p>
            </div>

            <div class="actions">
                <button class="btn-primary" onclick="simulateScan()">💅 Simular Escaneo (+1 Sello)</button>
                <button class="btn-secondary" onclick="resetCard()">🔄 Reiniciar Tarjeta</button>
            </div>

            <pre id="json-output">// Respuesta JSON de /api/card cargando...</pre>

            <div class="links">
                <a href="/docs" target="_blank">📖 Documentación Swagger (/docs)</a>
                <a href="/api/card" target="_blank">🔍 GET /api/card</a>
                <a href="/health" target="_blank">🩺 /health</a>
            </div>
        </div>

        <script>
            async function loadCard() {
                try {
                    const res = await fetch('/api/card');
                    const data = await res.json();
                    document.getElementById('client-name').innerText = data.cliente;
                    document.getElementById('points-badge').innerText = data.puntos + ' pts';
                    document.getElementById('qr-val').innerText = data.qr_code;
                    document.getElementById('json-output').innerText = JSON.stringify(data, null, 2);

                    const stampsContainer = document.getElementById('stamps-container');
                    stampsContainer.innerHTML = '';
                    for (let i = 1; i <= data.total_sellos; i++) {
                        const s = document.createElement('div');
                        s.className = 'stamp' + (i <= data.sellos_actuales ? ' active' : '');
                        s.innerHTML = i <= data.sellos_actuales ? '💅' : i;
                        stampsContainer.appendChild(s);
                    }
                } catch(e) {
                    console.error(e);
                }
            }

            async function simulateScan() {
                try {
                    const res = await fetch('/api/scan', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ action: 'add_stamp', qr_code: 'POPENAILS-VIP-7892' })
                    });
                    const data = await res.json();
                    document.getElementById('status-msg').innerText = data.message;
                    loadCard();
                } catch (e) {
                    console.error(e);
                }
            }

            async function resetCard() {
                try {
                    const res = await fetch('/api/reset', { method: 'POST' });
                    const data = await res.json();
                    document.getElementById('status-msg').innerText = data.message;
                    loadCard();
                } catch (e) {
                    console.error(e);
                }
            }

            loadCard();
        </script>
    </body>
    </html>
    """)


# ---------------------------------------------------------------------------
# Punto de Entrada
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🚀 Iniciando servidor PopeNails en http://{host}:{port}")
    uvicorn.run("server:app", host=host, port=port, reload=True)
