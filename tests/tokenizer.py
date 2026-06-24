from google.cloud import storage
import json

CREDS  = r"C:\mis-proyectos\Tenzor\service_account.json"
BUCKET = "tenzorai-tuning"
SRC    = "output/tenz-1-nova/postprocess/node-0/checkpoints/final/tokenizer_config.json"
DST    = "output/tenz-1-nova/tokenizer_config.json"

client = storage.Client.from_service_account_json(CREDS)
bucket = client.bucket(BUCKET)

# Leer el tokenizer_config.json de final/
content = bucket.blob(SRC).download_as_text()
cfg = json.loads(content)

# Verificar y limpiar si tiene referencia al tenant bucket
name_or_path = cfg.get("name_or_path", "")
print(f"name_or_path actual: {name_or_path}")

if "caip-tenant" in name_or_path or "caip-" in name_or_path:
    print("⚠️  Tiene referencia al tenant bucket — limpiando...")
    cfg["name_or_path"] = "Qwen/Qwen3-14B"
    content = json.dumps(cfg, indent=2)
    print("✅  Referencia corregida a: Qwen/Qwen3-14B")
else:
    print("✅  Sin referencias problemáticas — copiando tal cual")

# Subir a la raíz
bucket.blob(DST).upload_from_string(content, content_type="application/json")
print(f"✅  tokenizer_config.json actualizado en raíz ({len(content)/1024:.1f} KB)")