"""
Limpia dataset.jsonl antes de lanzar el full fine-tuning:
  1. Elimina duplicados EXACTOS de respuesta (se queda con la primera ocurrencia)
  2. Elimina respuestas que parecen truncadas (bloques de código sin cerrar,
     o que terminan abruptamente en ':' sin continuación)
  3. Marca (no borra automáticamente) respuestas con la plantilla genérica
     repetitiva tipo "Puedes utilizar X para crear Y más rápido y eficiente..."
     -- estas se imprimen para que decidas si las quieres fuera o no.

Uso:
    python clean_dataset.py
"""

import json

SRC = r"C:\mis-proyectos\Tenzor\dataset.jsonl"
DST = r"C:\mis-proyectos\Tenzor\dataset_clean.jsonl"

PATRON_GENERICO = "más rápido y eficiente utilizando características como"

with open(SRC, encoding="utf-8") as f:
    lineas = [json.loads(l) for l in f if l.strip()]

print(f"Total original: {len(lineas)} ejemplos\n")

vistos = set()
limpio = []
eliminados_dup = 0
eliminados_truncados = 0
genericos_detectados = []

for d in lineas:
    pregunta = d["contents"][0]["parts"][0]["text"]
    respuesta = d["contents"][1]["parts"][0]["text"]

    # 1. Duplicados exactos de respuesta
    if respuesta.strip() in vistos:
        eliminados_dup += 1
        continue
    vistos.add(respuesta.strip())

    # 2. Respuestas truncadas: bloque de código SIN CERRAR (número impar de ```)
    #    o que terminan en ":" suelto sin continuación (ej. "es:" y nada más).
    #    OJO: terminar en ``` (cierre normal de bloque) NO cuenta como truncado.
    backticks_impares = respuesta.count("```") % 2 != 0
    termina_en_dos_puntos_solo = (
        respuesta.strip().endswith(":")
        and not respuesta.strip().endswith("```")
    )

    if backticks_impares or termina_en_dos_puntos_solo:
        eliminados_truncados += 1
        print(f"  ✂️  ELIMINADA (truncada): {pregunta[-80:]}")
        continue

    # 3. Detectar plantilla genérica (solo se informa, no se borra)
    if PATRON_GENERICO in respuesta:
        genericos_detectados.append(pregunta[-80:])

    limpio.append(d)

print(f"\nDuplicados exactos eliminados : {eliminados_dup}")
print(f"Respuestas truncadas eliminadas: {eliminados_truncados}")
print(f"Respuestas con plantilla genérica detectadas (NO eliminadas): {len(genericos_detectados)}")
for g in genericos_detectados:
    print(f"  ⚠️  {g}")

with open(DST, "w", encoding="utf-8") as f:
    for d in limpio:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")

print(f"\n✅ Dataset limpio guardado en: {DST}")
print(f"   Total final: {len(limpio)} ejemplos (de {len(lineas)} originales)")
print("\nSi quieres eliminar también las respuestas con plantilla genérica,")
print("ábrelas en el archivo limpio y bórralas a mano, o dime y te genero")
print("una versión que las filtre automáticamente también.")
