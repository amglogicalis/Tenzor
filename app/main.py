import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import chat, admin
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

# Registrar Routers
app.include_router(chat.router)
app.include_router(admin.router)

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

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=True)
