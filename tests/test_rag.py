import os
import pytest
from app.services.rag_service import RAGService, RAGChunk

def test_rag_service_initialization():
    # Inicializa el servicio en el directorio real de entrenamiento
    rag = RAGService(docs_dir="docs_traning")
    assert len(rag.chunks) > 0
    
    # Comprobar que se han cargado fragmentos de los archivos clave
    source_files = [os.path.basename(c.source_file) for c in rag.chunks]
    assert "poseidon.md" in source_files or any("poseidon" in f.lower() for f in source_files)
    assert "cap_herramienta.md" in source_files or any("cap" in f.lower() for f in source_files)

def test_rag_search_matching_cap():
    rag = RAGService(docs_dir="docs_traning")
    
    # Búsqueda específica sobre CAP
    results = rag.search("Describe la estructura de carpetas y archivos JSON básicos requerida por un proyecto que utiliza CAP")
    assert results is not None
    assert len(results) > 0
    
    # El mejor resultado debe ser de cap_herramienta.md
    best_chunk = results[0]
    assert "cap" in os.path.basename(best_chunk.source_file).lower() or "cap" in best_chunk.heading.lower()
    
    # En el total de resultados (top 3) debe recuperarse la información de los archivos de configuración
    all_content = " ".join([c.content for c in results])
    assert "config.json" in all_content or "vars.json" in all_content or "vars" in all_content or "config" in all_content

def test_rag_search_matching_poseidon_dr():
    rag = RAGService(docs_dir="docs_traning")
    
    # Búsqueda sobre Poseidon y Disaster Recovery
    results = rag.search("¿Cómo se realiza el disaster recovery en poseidon y qué workflow de github se usa?")
    assert results is not None
    assert len(results) > 0
    
    # Debería contener referencias a Poseidon y workflows/cloudfront
    content_text = " ".join([c.content.lower() for c in results])
    headings_text = " ".join([c.heading.lower() for c in results])
    assert "poseidon" in content_text or "poseidon" in headings_text
    assert "workflow" in content_text or "github" in content_text

def test_rag_search_general_query_no_injection():
    rag = RAGService(docs_dir="docs_traning")
    
    # Búsqueda de un tema completamente general que no debería disparar la inyección de CAP/Poseidon
    results = rag.search("¿Cómo se escribe una función lambda recursiva en Python?")
    assert results is None
    
    # Otra consulta genérica
    results2 = rag.search("Hola, buenos días, ¿me puedes ayudar?")
    assert results2 is None
