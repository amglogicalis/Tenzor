#!/usr/bin/env python3
"""
buscar_modelo.py
Busca el modelo mg-custom-1782292431 en todas las regiones posibles
de Vertex AI y también lista todos los modelos y endpoints disponibles.
"""

import sys
import json
import urllib.request
import urllib.error
import os

try:
    from google.oauth2 import service_account
    import google.auth.transport.requests as google_requests
except ImportError:
    print("Instala: pip install google-auth")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
PROJECT_ID           = "tenzorai"
SERVICE_ACCOUNT_JSON = r"C:\mis-proyectos\Tenzor\service_account.json"
MODEL_ID_BUSCADO     = "mg-custom-1782292431"

# Regiones donde buscar (todas las relevantes para EU y US)
REGIONES = [
    "us-central1",
    "europe-west4",
    "europe-west1",
    "europe-west2",
    "europe-west3",
    "us-east1",
    "us-west1",
    "us-west4",
    "northamerica-northeast1",
    "asia-east1",
    "asia-northeast1",
]
# ══════════════════════════════════════════════════════════════════════════════

USE_COLOR = sys.stdout.isatty()

def c(code, text):
    if not USE_COLOR:
        return text
    codes = {"reset":"\033[0m","bold":"\033[1m","green":"\033[92m",
             "yellow":"\033[93m","red":"\033[91m","cyan":"\033[96m","gray":"\033[90m","dim":"\033[2m"}
    return f"{codes.get(code,'')}{text}{codes['reset']}"

def get_token():
    if not os.path.isfile(SERVICE_ACCOUNT_JSON):
        print(c("red", f"[ERROR] No se encuentra: {SERVICE_ACCOUNT_JSON}"))
        sys.exit(1)
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(google_requests.Request())
    return creds.token

def api_get(token, url):
    """Hace GET y devuelve (dict|None, error_str|None)."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "404"
        body = e.read().decode(errors="replace")[:200]
        return None, f"HTTP {e.code}: {body}"
    except Exception as ex:
        return None, str(ex)

def listar_modelos(token, region):
    url = (f"https://{region}-aiplatform.googleapis.com/v1/"
           f"projects/{PROJECT_ID}/locations/{region}/models?pageSize=100")
    data, err = api_get(token, url)
    if err == "404" or data is None:
        return [], err
    return data.get("models", []), None

def listar_endpoints(token, region):
    url = (f"https://{region}-aiplatform.googleapis.com/v1/"
           f"projects/{PROJECT_ID}/locations/{region}/endpoints?pageSize=100")
    data, err = api_get(token, url)
    if err == "404" or data is None:
        return [], err
    return data.get("endpoints", []), None

def listar_operaciones(token, region):
    """Lista operaciones recientes (puede mostrar deploys/undeloys en curso o fallidos)."""
    url = (f"https://{region}-aiplatform.googleapis.com/v1/"
           f"projects/{PROJECT_ID}/locations/{region}/operations?pageSize=20")
    data, err = api_get(token, url)
    if err or data is None:
        return [], err
    return data.get("operations", []), None

# ──────────────────────────────────────────────────────────────────────────────

def main():
    print()
    print(c("cyan", "═" * 68))
    print(c("bold", f"  BÚSQUEDA DE MODELO: {MODEL_ID_BUSCADO}"))
    print(c("cyan", "═" * 68))
    print(f"  Proyecto: {PROJECT_ID}")
    print(f"  Buscando en {len(REGIONES)} regiones…\n")

    token = get_token()

    encontrado_en = []   # [(region, modelo_dict)]
    endpoints_encontrados = []

    for region in REGIONES:
        modelos, err = listar_modelos(token, region)
        endpoints, eerr = listar_endpoints(token, region)

        tiene_modelos    = len(modelos) > 0
        tiene_endpoints  = len(endpoints) > 0

        if not tiene_modelos and not tiene_endpoints:
            print(c("dim", f"  {region:<30} — sin recursos"))
            continue

        # ── Mostrar modelos ───────────────────────────────────────────────
        for m in modelos:
            name        = m.get("name", "")
            display     = m.get("displayName", "—")
            version_id  = m.get("versionId", "—")
            create_time = m.get("createTime", "—")[:19]
            # Extraer el ID corto del modelo del resource name
            # format: projects/.../models/MODEL_ID
            short_id = name.split("/models/")[-1].split("@")[0] if "/models/" in name else name

            match = MODEL_ID_BUSCADO.lower() in name.lower() or MODEL_ID_BUSCADO.lower() in display.lower()

            if match:
                encontrado_en.append((region, m))
                tag = c("green", "  ★ ENCONTRADO")
            else:
                tag = ""

            marker = c("green", "●") if match else c("gray", "·")
            print(f"  {marker} [{region}] MODELO{tag}")
            print(f"      ID:      {c('cyan', short_id)}")
            print(f"      Nombre:  {display}")
            print(f"      Versión: {version_id}   Creado: {create_time}")
            print(f"      Resource: {name}")
            print()

        # ── Mostrar endpoints ─────────────────────────────────────────────
        for ep in endpoints:
            ep_name    = ep.get("name", "")
            ep_display = ep.get("displayName", "—")
            ep_short   = ep_name.split("/endpoints/")[-1] if "/endpoints/" in ep_name else ep_name
            deployed   = ep.get("deployedModels", [])
            traffic    = ep.get("trafficSplit", {})
            update_t   = ep.get("updateTime", "—")[:19]

            endpoints_encontrados.append((region, ep))

            print(f"  {c('yellow','◆')} [{region}] ENDPOINT")
            print(f"      ID:      {c('yellow', ep_short)}")
            print(f"      Nombre:  {ep_display}")
            print(f"      Modelos desplegados: {len(deployed)}")
            print(f"      Tráfico: {dict(traffic) or '(vacío)'}")
            print(f"      Actualizado: {update_t}")

            for dm in deployed:
                dm_model   = dm.get("model", "—")
                dm_id      = dm.get("id", "—")
                dm_display = dm.get("displayName", "—")
                dm_version = dm.get("modelVersionId", "—")
                model_match = MODEL_ID_BUSCADO.lower() in dm_model.lower()
                tag2 = c("green", "  ← modelo buscado") if model_match else ""
                print(f"        {c('gray','└─')} Deployed model ID: {dm_id}{tag2}")
                print(f"           model resource: {dm_model}")
                print(f"           displayName: {dm_display}   versión: {dm_version}")
            print()

    # ── Operaciones recientes en us-central1 y europe-west4 ───────────────
    print(c("cyan", "─" * 68))
    print(c("bold", "\n  OPERACIONES RECIENTES (us-central1 + europe-west4)\n"))
    for region in ["us-central1", "europe-west4"]:
        ops, err = listar_operaciones(token, region)
        if not ops:
            print(c("dim", f"  {region}: sin operaciones recientes o sin permiso\n"))
            continue
        print(f"  {c('bold', region)} ({len(ops)} operaciones):")
        for op in ops[:8]:   # máx 8 por región
            op_name  = op.get("name", "—").split("/operations/")[-1]
            done     = op.get("done", False)
            error    = op.get("error", None)
            meta     = op.get("metadata", {})
            op_type  = meta.get("@type", "—").split(".")[-1]
            create_t = meta.get("createTime", "—")[:19]

            if error:
                status = c("red", f"ERROR {error.get('code','?')}: {error.get('message','')[:60]}")
            elif done:
                status = c("green", "COMPLETADA")
            else:
                status = c("yellow", "EN CURSO")

            print(f"    · {op_type:<35} {status}")
            print(f"      ID: {op_name[:50]}   {c('gray', create_t)}")
        print()

    # ── Resumen final ──────────────────────────────────────────────────────
    print(c("cyan", "═" * 68))
    print(c("bold", "\n  RESUMEN\n"))

    if encontrado_en:
        print(c("green", f"  ✔ Modelo '{MODEL_ID_BUSCADO}' encontrado en:"))
        for reg, m in encontrado_en:
            print(f"    → {reg}  /  {m.get('name','')}")
    else:
        print(c("red",    f"  ✖ Modelo '{MODEL_ID_BUSCADO}' NO encontrado en ninguna región."))
        print(c("yellow", "    Posibles causas:"))
        print(       "      · El wake/sleep lo eliminó con undeploy + delete del modelo")
        print(       "      · Fue movido a otro proyecto")
        print(       "      · El ID ha cambiado (busca arriba por nombre/display)")

    print(f"\n  Total endpoints encontrados: {len(endpoints_encontrados)}")
    for reg, ep in endpoints_encontrados:
        short = ep.get('name','').split('/endpoints/')[-1]
        print(f"    · {reg}  /  {short}  ({ep.get('displayName','—')})")

    print(c("cyan", "\n" + "═" * 68 + "\n"))

if __name__ == "__main__":
    main()
