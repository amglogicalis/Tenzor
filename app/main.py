import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import chat, admin, endpoints
from app.routers import platform_auth, platform_agents, platform_knowledge, platform_chat, round_table, platform_keys
from app.routers import platform_compiler, crew
from app import config


app = FastAPI(
    title="Tenzor API",
    description="API privada y especializada en programación, cloud e infraestructura para el equipo de Tenzor.",
    version="1.0.0"
)

# Configurar CORS para permitir peticiones desde cualquier origen (integraciones web)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Error interno en el servidor de Tenzor: {str(exc)}"}
    )

# Registrar Routers — Tenzor AI (chat técnico privado, API compatible OpenAI)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(endpoints.router)

# Registrar Routers — Arzor AIs Platform (stubs, se implementan fase a fase)
app.include_router(platform_auth.router)
app.include_router(platform_agents.router)
app.include_router(platform_knowledge.router)
app.include_router(platform_chat.router)
app.include_router(platform_keys.router)
app.include_router(round_table.router)
app.include_router(platform_compiler.router)
app.include_router(crew.router)


from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Montar carpeta de archivos estáticos (CSS, JS, imágenes)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
async def root():
    """
    Sirve el frontend interactivo de Tenzor.
    """
    return FileResponse("app/static/index.html")

@app.get("/platform")
@app.get("/platform/{full_path:path}")
async def platform_spa(full_path: str = ""):
    """
    Sirve la SPA de Arzor AIs Platform.
    Todas las sub-rutas del frontend se resuelven aquí (client-side routing).
    """
    return FileResponse("app/static/platform/index.html")

import asyncio
import logging
from app.routers.chat import ai_service

async def auto_shutdown_loop():
    logger = logging.getLogger("auto_shutdown")
    logger.info("Bucle de auto-apagado por inactividad iniciado.")
    while True:
        try:
            # Comprobar inactividad cada 60 segundos
            await asyncio.sleep(60)
            ai_service.check_idle_shutdown()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error en bucle de auto-apagado: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(auto_shutdown_loop())

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=True)

