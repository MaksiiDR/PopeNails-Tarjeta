#!/usr/bin/env python3
"""
=============================================================================
PopeNails Loyalty Card - Backend Server (FastAPI + Supabase)
=============================================================================
Servidor de fidelización y tarjeta de puntos para PopeNails Studio.
Compatible tanto en desarrollo local como en Vercel Serverless.

Endpoints principales:
  - GET  /api/clients             -> Lista todas las clientas (Supabase loyalty_cards o appointments)
  - GET  /api/card?client_name=.. -> Retorna la tarjeta de una clienta específica o la clienta activa
  - POST /api/scan                -> Escaneo en mostrador para sellar/canjear en Supabase
  - POST /api/client              -> Registra una nueva clienta con 0 sellos
  - POST /api/reset               -> Reinicia la tarjeta al estado inicial de pruebas
  - GET  /health                  -> Health check y estado de conexión a Supabase
  - GET  /docs                    -> Swagger UI interactiva
=============================================================================
"""

import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Cargar variables de entorno desde .env
current_dir = Path(__file__).resolve().parent
from dotenv import load_dotenv
env_path = current_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# Si el usuario ejecuta con python del sistema pero existe .venv local,
# re-ejecutar automáticamente usando el entorno virtual.
venv_python = current_dir / ".venv" / "bin" / "python"
if sys.executable != str(venv_python) and venv_python.exists():
    try:
        import fastapi
        import httpx
    except ImportError:
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

# ---------------------------------------------------------------------------
# Configuración de Supabase
# ---------------------------------------------------------------------------
SUPABASE_URL = (
    os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    or os.getenv("SUPABASE_URL")
    or "https://ktmwjuamovupzwqifmct.supabase.co"
).rstrip("/")

SUPABASE_ANON_KEY = (
    os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or ""
)

def get_supabase_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def slugify(text: str) -> str:
    """Convierte texto en un identificador limpio para el QR"""
    if not text:
        return "CLIENT"
    clean = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^\w\s-]", "", clean).strip().upper()
    clean = re.sub(r"[-\s]+", "-", clean)
    return clean or "CLIENT"

# ---------------------------------------------------------------------------
# Estado en Memoria (Fallback & Caché Local)
# ---------------------------------------------------------------------------
INITIAL_DEFAULT_CARD = {
    "cliente": "Nueva Clienta",
    "client_name": "Nueva Clienta",
    "puntos": 0,
    "points": 0,
    "sellos_actuales": 0,
    "stamps": 0,
    "total_sellos": 10,
    "qr_code": "POPENAILS-NUEVA-CLIENTA",
    "nivel": "Bienvenida",
    "premio_disponible": False,
    "ultimo_escaneo": None
}

card_state = dict(INITIAL_DEFAULT_CARD)

# Memoria de clientas para actualizaciones en tiempo real cuando loyalty_cards aún no existe en Supabase
CLIENTS_OVERRIDE_CACHE: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Modelos Pydantic
# ---------------------------------------------------------------------------
class CardResponse(BaseModel):
    cliente: str = Field(..., examples=["Nueva Clienta"])
    client_name: Optional[str] = Field(None, examples=["Nueva Clienta"])
    puntos: int = Field(0, examples=[0])
    points: Optional[int] = Field(0, examples=[0])
    sellos_actuales: int = Field(0, examples=[0])
    stamps: Optional[int] = Field(0, examples=[0])
    total_sellos: int = Field(10, examples=[10])
    qr_code: str = Field("POPENAILS-VIP-7892", examples=["POPENAILS-VIP-7892"])
    nivel: Optional[str] = Field("Bienvenida", examples=["Bienvenida"])
    premio_disponible: Optional[bool] = Field(False, examples=[False])
    ultimo_escaneo: Optional[str] = Field(None, examples=["2026-10-02T18:30:00"])
    visitas: Optional[int] = Field(None, examples=[3])


class ClientItem(BaseModel):
    client_name: str
    cliente: str
    phone: Optional[str] = None
    sellos_actuales: int = 0
    stamps: int = 0
    puntos: int = 0
    points: int = 0
    total_sellos: int = 10
    nivel: str = "Bienvenida"
    visitas: int = 0
    ultima_visita: Optional[str] = None
    qr_code: str


class ScanRequest(BaseModel):
    client_name: Optional[str] = Field(None, description="Nombre de la clienta a escanear")
    cliente: Optional[str] = Field(None, description="Alias para client_name")
    action: Optional[str] = Field("add_stamp", description="Acción: 'add_stamp', 'redeem', 'reset'")
    sellos: Optional[int] = Field(1, ge=1, le=10, description="Cantidad de sellos a sumar")
    qr_code: Optional[str] = Field(None, description="Código QR opcional para validación")


class ScanResponse(BaseModel):
    status: str
    message: str
    card: CardResponse
    sellos_agregados: int
    premio_desbloqueado: bool
    timestamp: str


class CreateClientRequest(BaseModel):
    client_name: str = Field(..., description="Nombre completo de la nueva clienta", examples=["Valentina Silva"])
    phone: Optional[str] = Field(None, description="Teléfono de contacto opcional", examples=["+56912345678"])


class CreateClientResponse(BaseModel):
    status: str
    message: str
    client: ClientItem

# ---------------------------------------------------------------------------
# Lógica de Comunicación con Supabase
# ---------------------------------------------------------------------------
async def query_supabase_loyalty_cards() -> Optional[List[Dict[str, Any]]]:
    """Consulta la tabla loyalty_cards en Supabase. Si da 404/PGRST205 retorna None."""
    if not SUPABASE_ANON_KEY:
        return None
    try:
        url = f"{SUPABASE_URL}/rest/v1/loyalty_cards?select=*&order=client_name.asc"
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=get_supabase_headers())
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404 or "PGRST205" in resp.text:
                return None
            return None
    except Exception as e:
        print(f"⚠️ Error consultando loyalty_cards en Supabase: {e}")
        return None


async def query_supabase_appointments_grouped() -> List[ClientItem]:
    """
    Consulta la tabla appointments y agrupa por client_name.
    Retorna la lista de las 96 clientas existentes en la base de datos de PopeNails.
    """
    clients_dict: Dict[str, Dict[str, Any]] = {}

    if SUPABASE_ANON_KEY:
        try:
            url = f"{SUPABASE_URL}/rest/v1/appointments?select=client_name,created_at,service,price&order=created_at.desc&limit=1000"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=get_supabase_headers())
                if resp.status_code == 200:
                    records = resp.json()
                    for item in records:
                        name = (item.get("client_name") or "").strip()
                        if not name:
                            continue
                        if name not in clients_dict:
                            slug = slugify(name)
                            clients_dict[name] = {
                                "client_name": name,
                                "cliente": name,
                                "phone": None,
                                "sellos_actuales": 0,
                                "stamps": 0,
                                "puntos": 0,
                                "points": 0,
                                "total_sellos": 10,
                                "nivel": "Bienvenida",
                                "visitas": 0,
                                "ultima_visita": item.get("created_at"),
                                "qr_code": f"POPENAILS-{slug}"
                            }
                        clients_dict[name]["visitas"] += 1
        except Exception as e:
            print(f"⚠️ Error consultando appointments en Supabase: {e}")

    # Si por algún motivo falló la red o no hubo clientas, asegurar clienta por defecto
    if not clients_dict:
        clients_dict["Nueva Clienta"] = {
            "client_name": "Nueva Clienta",
            "cliente": "Nueva Clienta",
            "phone": None,
            "sellos_actuales": 0,
            "stamps": 0,
            "puntos": 0,
            "points": 0,
            "total_sellos": 10,
            "nivel": "Bienvenida",
            "visitas": 0,
            "ultima_visita": None,
            "qr_code": "POPENAILS-NUEVA-CLIENTA"
        }

    # Aplicar overrides y clientas creadas en memoria
    for name, override in CLIENTS_OVERRIDE_CACHE.items():
        if name in clients_dict:
            clients_dict[name].update(override)
        else:
            slug = slugify(name)
            clients_dict[name] = {
                "client_name": name,
                "cliente": name,
                "phone": override.get("phone"),
                "sellos_actuales": override.get("sellos_actuales", 0),
                "stamps": override.get("stamps", override.get("sellos_actuales", 0)),
                "puntos": override.get("puntos", 0),
                "points": override.get("points", override.get("puntos", 0)),
                "total_sellos": 10,
                "nivel": override.get("nivel", "Bienvenida"),
                "visitas": override.get("visitas", 1),
                "ultima_visita": override.get("ultimo_escaneo") or datetime.now().isoformat(),
                "qr_code": f"POPENAILS-{slug}"
            }

    # Ordenar alfabéticamente
    sorted_clients = sorted(clients_dict.values(), key=lambda x: x["client_name"].lower())
    return [ClientItem(**item) for item in sorted_clients]


async def find_client_card(client_name: str) -> Dict[str, Any]:
    """Busca los datos de una clienta en loyalty_cards, caché de memoria o appointments."""
    clean_name = client_name.strip()
    slug = slugify(clean_name)

    # 1. Buscar en Supabase loyalty_cards
    if SUPABASE_ANON_KEY:
        try:
            url = f"{SUPABASE_URL}/rest/v1/loyalty_cards?client_name=ilike.{clean_name}&select=*&limit=1"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=get_supabase_headers())
                if resp.status_code == 200:
                    rows = resp.json()
                    if rows:
                        row = rows[0]
                        stamps = row.get("stamps", 0)
                        pts = row.get("points", 0)
                        nivel = "Gold VIP" if pts >= 1000 else ("Clienta Frecuente" if stamps > 0 else "Bienvenida")
                        return {
                            "cliente": row.get("client_name", clean_name),
                            "client_name": row.get("client_name", clean_name),
                            "puntos": pts,
                            "points": pts,
                            "sellos_actuales": stamps,
                            "stamps": stamps,
                            "total_sellos": 10,
                            "qr_code": f"POPENAILS-{slug}",
                            "nivel": nivel,
                            "premio_disponible": stamps >= 10,
                            "ultimo_escaneo": row.get("last_visit")
                        }
        except Exception as e:
            print(f"⚠️ Error buscando en loyalty_cards: {e}")

    # 2. Buscar en caché de memoria
    if clean_name in CLIENTS_OVERRIDE_CACHE:
        ov = CLIENTS_OVERRIDE_CACHE[clean_name]
        stamps = ov.get("sellos_actuales", 0)
        pts = ov.get("puntos", 0)
        nivel = "Gold VIP" if pts >= 1000 else ("Clienta Frecuente" if stamps > 0 else "Bienvenida")
        return {
            "cliente": clean_name,
            "client_name": clean_name,
            "puntos": pts,
            "points": pts,
            "sellos_actuales": stamps,
            "stamps": stamps,
            "total_sellos": 10,
            "qr_code": f"POPENAILS-{slug}",
            "nivel": nivel,
            "premio_disponible": stamps >= 10,
            "ultimo_escaneo": ov.get("ultimo_escaneo")
        }

    # 3. Buscar en appointments para ver si existe y cuántas visitas tiene
    visitas = 0
    ultima_visita = None
    if SUPABASE_ANON_KEY:
        try:
            url = f"{SUPABASE_URL}/rest/v1/appointments?client_name=ilike.{clean_name}&select=client_name,created_at&limit=50"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=get_supabase_headers())
                if resp.status_code == 200:
                    appts = resp.json()
                    visitas = len(appts)
                    if appts:
                        clean_name = appts[0].get("client_name") or clean_name
                        ultima_visita = appts[0].get("created_at")
        except Exception as e:
            print(f"⚠️ Error buscando clienta en appointments: {e}")

    return {
        "cliente": clean_name,
        "client_name": clean_name,
        "puntos": 0,
        "points": 0,
        "sellos_actuales": 0,
        "stamps": 0,
        "total_sellos": 10,
        "qr_code": f"POPENAILS-{slug}",
        "nivel": "Bienvenida",
        "premio_disponible": False,
        "visitas": visitas,
        "ultimo_escaneo": ultima_visita
    }


async def save_client_card_supabase(client_name: str, stamps: int, points: int, phone: Optional[str] = None):
    """Guarda o actualiza la tarjeta en Supabase y en la caché de memoria."""
    now_iso = datetime.now().isoformat()
    clean_name = client_name.strip()
    nivel = "Gold VIP" if points >= 1000 else ("Clienta Frecuente" if stamps > 0 else "Bienvenida")

    # Guardar en memoria
    if clean_name not in CLIENTS_OVERRIDE_CACHE:
        CLIENTS_OVERRIDE_CACHE[clean_name] = {}

    CLIENTS_OVERRIDE_CACHE[clean_name].update({
        "client_name": clean_name,
        "cliente": clean_name,
        "sellos_actuales": stamps,
        "stamps": stamps,
        "puntos": points,
        "points": points,
        "nivel": nivel,
        "ultimo_escaneo": now_iso
    })
    if phone:
        CLIENTS_OVERRIDE_CACHE[clean_name]["phone"] = phone

    # Actualizar o insertar en Supabase si la tabla loyalty_cards está creada
    if SUPABASE_ANON_KEY:
        try:
            headers = get_supabase_headers()
            async with httpx.AsyncClient(timeout=8.0) as client:
                # Intentar PATCH
                patch_url = f"{SUPABASE_URL}/rest/v1/loyalty_cards?client_name=eq.{clean_name}"
                patch_body = {
                    "stamps": stamps,
                    "points": points,
                    "last_visit": now_iso
                }
                if phone:
                    patch_body["phone"] = phone
                patch_resp = await client.patch(patch_url, json=patch_body, headers=headers)
                if patch_resp.status_code == 200 and patch_resp.json():
                    return  # Actualizado exitosamente

                # Si no existía la fila, intentar POST (insert)
                if patch_resp.status_code in (200, 204) and not patch_resp.json():
                    post_url = f"{SUPABASE_URL}/rest/v1/loyalty_cards"
                    post_body = {
                        "client_name": clean_name,
                        "stamps": stamps,
                        "points": points,
                        "phone": phone,
                        "last_visit": now_iso
                    }
                    await client.post(post_url, json=post_body, headers=headers)
        except Exception as e:
            print(f"ℹ️ Persistencia en memoria OK. Supabase sync loyalty_cards: {e}")

# ---------------------------------------------------------------------------
# Aplicación FastAPI y Rutas
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PopeNails Loyalty Card API",
    description="Backend de fidelización, clientas y puntos para PopeNails Studio conectado a Supabase",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Definir un APIRouter para compartir rutas con y sin prefijo /api
api_router = APIRouter()


@api_router.get("/clients", response_model=List[ClientItem], summary="Listar todas las clientas")
async def get_clients():
    """
    Lista todas las clientas:
    1. Consulta 'loyalty_cards' en Supabase.
    2. Si da 404 o no existe, consulta la tabla 'appointments' agrupando por client_name
       para traer las 96 clientas existentes en el salón.
    """
    loyalty_rows = await query_supabase_loyalty_cards()
    if loyalty_rows is not None and len(loyalty_rows) > 0:
        clients_list = []
        for r in loyalty_rows:
            name = r.get("client_name") or "Sin nombre"
            slug = slugify(name)
            stamps = r.get("stamps", 0)
            pts = r.get("points", 0)
            nivel = "Gold VIP" if pts >= 1000 else ("Clienta Frecuente" if stamps > 0 else "Bienvenida")
            clients_list.append(ClientItem(
                client_name=name,
                cliente=name,
                phone=r.get("phone"),
                sellos_actuales=stamps,
                stamps=stamps,
                puntos=pts,
                points=pts,
                total_sellos=10,
                nivel=nivel,
                visitas=r.get("total_cycles_completed", 0) + (1 if stamps > 0 else 0),
                ultima_visita=r.get("last_visit"),
                qr_code=f"POPENAILS-{slug}"
            ))
        return clients_list

    # Fallback automático a appointments (96 clientas reales)
    return await query_supabase_appointments_grouped()


@api_router.get("/card", response_model=CardResponse, summary="Obtener estado de la tarjeta")
async def get_card(client_name: Optional[str] = Query(None, description="Nombre de la clienta")):
    """
    Retorna los datos de fidelización:
    - Si se especifica client_name, busca su tarjeta particular en Supabase/appointments.
    - Si no se especifica, retorna el estado de la clienta activa actual.
    """
    if client_name and client_name.strip():
        data = await find_client_card(client_name.strip())
        return CardResponse(**data)

    return CardResponse(
        cliente=card_state["cliente"],
        client_name=card_state.get("client_name", card_state["cliente"]),
        puntos=card_state["puntos"],
        points=card_state.get("points", card_state["puntos"]),
        sellos_actuales=card_state["sellos_actuales"],
        stamps=card_state.get("stamps", card_state["sellos_actuales"]),
        total_sellos=card_state["total_sellos"],
        qr_code=card_state["qr_code"],
        nivel=card_state.get("nivel", "Bienvenida"),
        premio_disponible=card_state.get("premio_disponible", False),
        ultimo_escaneo=card_state.get("ultimo_escaneo")
    )


@api_router.post("/scan", response_model=ScanResponse, summary="Escanear tarjeta en mostrador")
async def scan_card(payload: Optional[ScanRequest] = None):
    """
    Simula el escaneo en el mostrador de PopeNails:
    - Recibe { client_name, action: 'add_stamp' | 'redeem' }
    - Actualiza sellos y puntos en Supabase y memoria
    - Sella (+50 pts) o canjea premio (reinicio de sellos)
    """
    if payload is None:
        payload = ScanRequest()

    target_client = (payload.client_name or payload.cliente or card_state["cliente"]).strip()
    action = payload.action or "add_stamp"
    now_iso = datetime.now().isoformat()

    current_data = await find_client_card(target_client)
    stamps = current_data.get("sellos_actuales", 0)
    points = current_data.get("puntos", 0)
    total_sellos = current_data.get("total_sellos", 10)

    sellos_agregados = 0
    premio_desbloqueado = False

    if action == "reset":
        stamps = 0
        points = 0
        message = f"Tarjeta de '{target_client}' reiniciada a 0 sellos y 0 puntos."
    elif action == "redeem":
        if stamps < total_sellos and not current_data.get("premio_disponible", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La clienta {target_client} aún no tiene 10 sellos para canjear premio."
            )
        stamps = 0
        message = f"🎉 ¡Premio canjeado con éxito para {target_client}! Se ha iniciado un nuevo ciclo de sellos."
    else:  # add_stamp
        sellos_a_sumar = payload.sellos if payload.sellos is not None else 1
        sellos_agregados = sellos_a_sumar

        if stamps >= total_sellos:
            stamps = 0

        nuevo_total = stamps + sellos_a_sumar
        puntos_ganados = 50 * sellos_a_sumar
        points += puntos_ganados

        if nuevo_total >= total_sellos:
            stamps = total_sellos
            premio_desbloqueado = True
            points += 200  # Bono por completar
            message = (
                f"🎉 ¡Felicidades {target_client}! Completaste los {total_sellos} sellos. "
                "¡Tienes 1 servicio gratis o descuento VIP disponible! (+200 pts bonus)"
            )
        else:
            stamps = nuevo_total
            message = (
                f"💅 ¡Sello agregado para {target_client}! Lleva {stamps} "
                f"de {total_sellos} sellos. (+{puntos_ganados} pts acumulados)"
            )

    # Persistir en Supabase y caché
    await save_client_card_supabase(target_client, stamps, points)

    # Actualizar también tarjeta default si es la misma
    if target_client.lower() == card_state["cliente"].lower():
        card_state["sellos_actuales"] = stamps
        card_state["stamps"] = stamps
        card_state["puntos"] = points
        card_state["points"] = points
        card_state["ultimo_escaneo"] = now_iso
        card_state["premio_disponible"] = premio_desbloqueado

    card_obj = CardResponse(
        cliente=target_client,
        client_name=target_client,
        puntos=points,
        points=points,
        sellos_actuales=stamps,
        stamps=stamps,
        total_sellos=total_sellos,
        qr_code=f"POPENAILS-{slugify(target_client)}",
        nivel="Gold VIP" if points >= 1000 else ("Clienta Frecuente" if stamps > 0 else "Bienvenida"),
        premio_disponible=(stamps >= total_sellos),
        ultimo_escaneo=now_iso
    )

    return ScanResponse(
        status="success",
        message=message,
        card=card_obj,
        sellos_agregados=sellos_agregados,
        premio_desbloqueado=premio_desbloqueado,
        timestamp=now_iso
    )


@api_router.post("/client", response_model=CreateClientResponse, summary="Registrar nueva clienta")
async def create_client(payload: CreateClientRequest):
    """
    Registra una nueva clienta en PopeNails con 0 sellos y 0 puntos.
    Guarda en Supabase (loyalty_cards) y actualiza la lista disponible.
    """
    name = payload.client_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre de la clienta no puede estar vacío.")

    slug = slugify(name)
    now_iso = datetime.now().isoformat()

    # Guardar en Supabase y memoria
    await save_client_card_supabase(client_name=name, stamps=0, points=0, phone=payload.phone)

    client_item = ClientItem(
        client_name=name,
        cliente=name,
        phone=payload.phone,
        sellos_actuales=0,
        stamps=0,
        puntos=0,
        points=0,
        total_sellos=10,
        nivel="Bienvenida",
        visitas=0,
        ultima_visita=now_iso,
        qr_code=f"POPENAILS-{slug}"
    )

    return CreateClientResponse(
        status="success",
        message=f"Clienta '{name}' registrada exitosamente con 0 sellos.",
        client=client_item
    )


@api_router.post("/reset", summary="Reiniciar tarjeta a valores iniciales de prueba")
def reset_card():
    """Reinicia la tarjeta activa a 0 sellos y 0 puntos (Nueva Clienta)."""
    card_state.clear()
    card_state.update(INITIAL_DEFAULT_CARD)
    CLIENTS_OVERRIDE_CACHE.clear()
    return {
        "status": "success",
        "message": "Tarjeta y cachés reiniciados a 0 sellos y 0 puntos.",
        "card": card_state
    }


# Registrar endpoints tanto bajo /api como en la raíz (para máxima compatibilidad con Vercel rewrites)
app.include_router(api_router, prefix="/api")
app.include_router(api_router, include_in_schema=False)


@app.get("/health", summary="Health check")
async def health_check():
    supabase_configured = bool(SUPABASE_URL and SUPABASE_ANON_KEY)
    return {
        "status": "ok",
        "service": "PopeNails Backend Server",
        "supabase_configured": supabase_configured,
        "supabase_url": SUPABASE_URL,
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


@app.get("/", response_class=HTMLResponse, summary="Página principal")
def serve_index():
    """Sirve el index.html principal de la aplicación."""
    root_index = current_dir / "index.html"
    public_index = public_path / "index.html"

    if root_index.exists():
        return FileResponse(str(root_index))
    if public_index.exists():
        return FileResponse(str(public_index))

    return HTMLResponse("<h1>PopeNails Backend Activo</h1><p>Visita <a href='/docs'>/docs</a> para la API.</p>")


# ---------------------------------------------------------------------------
# Punto de Entrada para desarrollo local
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🚀 Iniciando servidor PopeNails en http://{host}:{port}")
    uvicorn.run("server:app", host=host, port=port, reload=True)
