"""
verify_rag.py — Verificacion rapida del RAG de plataforma Arzor.

Uso:
    .\venv\Scripts\python.exe tests\verify_rag.py [AGENT_ID] [--clean]

    AGENT_ID  UUID de un agente existente (opcional; si se omite usa el primero de la DB).
    --clean   Elimina los archivos subidos al finalizar.

El script:
  1. Ingesta los dos PDFs de tests/ directamente en Supabase (sin servidor HTTP).
  2. Realiza busquedas que DEBEN encontrar chunks.
  3. Realiza una busqueda negativa que NO debe devolver nada.
  4. Imprime un resumen con checkmarks.

Requisitos: SUPABASE_URL y SUPABASE_SERVICE_KEY en .env (o en el entorno).
"""

import sys, os, time, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from app.services.platform_rag_service import PlatformRAGService

TESTS_DIR = ROOT / "tests"
PDF_FILES = [
    ("rag_verification_document.pdf", "application/pdf"),
    ("mlops_knowledge_pack.pdf",      "application/pdf"),
]
POSITIVE_QUERIES = ["machine learning", "pipeline", "model"]
NEGATIVE_QUERY   = "xyzzy quux frobnicator nonexistent token 9834jsdf"
FAKE_USER_ID     = "00000000-0000-0000-0000-000000000001"


def main():
    agent_id = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    svc = PlatformRAGService()

    if not svc.supabase:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_KEY no configurados.")
        sys.exit(1)

    if not agent_id:
        try:
            resp = svc.supabase.table("custom_agents").select("id").limit(1).execute()
            if resp.data:
                agent_id = resp.data[0]["id"]
                print(f"Usando primer agente: {agent_id}")
            else:
                print("No hay agentes en la DB. Crea uno primero.")
                sys.exit(1)
        except Exception as e:
            print(f"Error consultando agentes: {e}")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Verificacion RAG — agente: {agent_id}")
    print(f"{'='*60}\n")

    # Fase 1: Ingesta
    uploaded = []
    for fname, ctype in PDF_FILES:
        fpath = TESTS_DIR / fname
        if not fpath.exists():
            print(f"[SKIP] {fpath} no encontrado")
            continue
        raw = fpath.read_bytes()
        print(f"[UPLOAD] {fname} ({len(raw)//1024} KB)...")
        t0 = time.monotonic()
        try:
            r = svc.ingest_file(agent_id=agent_id, user_id=FAKE_USER_ID,
                                filename=fname, content_type=ctype, raw_bytes=raw)
            print(f"  OK  {r.get('chunks_created','?')} chunks en {time.monotonic()-t0:.1f}s  (file_id={r.get('file_id','?')})")
            uploaded.append((fname, r.get("file_id")))
        except Exception as e:
            print(f"  ERROR: {e}")
    
    if not uploaded:
        print("\nNinguna ingesta exitosa. Abortando.")
        sys.exit(1)

    print()

    # Fase 2: Busquedas positivas
    all_ok = True
    print("Busquedas positivas (esperan >= 1 chunk):\n")
    for q in POSITIVE_QUERIES:
        try:
            chunks = svc.search(agent_id=agent_id, query=q, top_k=3)
            if chunks:
                preview = chunks[0].content[:80].replace("\n"," ")
                print(f"  OK  '{q}' -> {len(chunks)} chunk(s) | rank={chunks[0].rank:.4f}")
                print(f"      \"{preview}...\"")
            else:
                print(f"  FAIL '{q}' -> 0 resultados")
                all_ok = False
        except Exception as e:
            print(f"  ERROR '{q}': {e}")
            all_ok = False
        print()

    # Fase 3: Busqueda negativa
    print(f"Busqueda negativa (espera 0 chunks):\n")
    try:
        neg = svc.search(agent_id=agent_id, query=NEGATIVE_QUERY, top_k=3)
        if not neg:
            print(f"  OK  Ninguna coincidencia espuria (correcto)\n")
        else:
            print(f"  WARN {len(neg)} falsos positivos\n")
    except Exception as e:
        print(f"  ERROR: {e}\n")

    # Resumen
    print("-"*60)
    print("RESULTADO: OK" if all_ok else "RESULTADO: FALLO (revisa logs Supabase)")
    print("-"*60)

    # Limpieza
    if "--clean" in sys.argv:
        print("\nLimpiando archivos subidos...")
        for fname, fid in uploaded:
            if fid:
                try:
                    svc.delete_file(file_id=fid, user_id=FAKE_USER_ID)
                    print(f"  Eliminado: {fname}")
                except Exception as e:
                    print(f"  No se pudo eliminar {fname}: {e}")

if __name__ == "__main__":
    main()
