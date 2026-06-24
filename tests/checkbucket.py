from google.cloud import storage

CREDS  = r"C:\mis-proyectos\Tenzor\service_account.json"
BUCKET = "tenzorai-tuning"
PREFIX = "output/tenz-1-nova/"

client = storage.Client.from_service_account_json(CREDS)
blobs  = sorted(client.list_blobs(BUCKET, prefix=PREFIX), key=lambda b: b.name)

print(f"\n{len(blobs)} archivos en gs://{BUCKET}/{PREFIX}\n")
print(f"{'ARCHIVO':<50} {'TAMAÑO':>12}")
print("-" * 65)
for b in blobs:
    name = b.name.replace(PREFIX, "")
    if b.size >= 1024 * 1024:
        print(f"{name:<50} {b.size/1024/1024:>9.1f} MB")
    else:
        print(f"{name:<50} {b.size/1024:>9.1f} KB")