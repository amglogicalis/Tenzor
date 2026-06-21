FROM python:3.12-slim

# Evitar que Python escriba archivos .pyc en disco
ENV PYTHONDONTWRITEBYTECODE 1
# Evitar que Python almacene en búfer stdout/stderr (importante para ver logs en Render)
ENV PYTHONUNBUFFERED 1

WORKDIR /code

# Instalar dependencias
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copiar el código del proyecto
COPY ./app /code/app

# Exponer el puerto por defecto (opcional, informativo)
EXPOSE 8000

# Arrancar el servidor leyendo la variable de entorno PORT (suministrada por Render)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
