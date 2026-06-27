### Fase 10: Arzor DevCrew CLI Solo accedder a esta fase tras completar el correcto funcionamiento de las anteriores

Objetivo:
CLI local para planificar y escribir proyectos usando agentes del servidor.

Componentes:

- `cli/tenzor_crew.py`
- `/platform/crew/plan`
- `/platform/crew/write`
- Backoff local.
- Debouncer cliente-servidor.
- Contexto por stubs.

Verificacion:

- Generar microservicio FastAPI completo.
- Crear estructura de archivos.
- No saturar proveedores.

---

## Instruccion de Arranque Rapido

Cuando el usuario diga:

**"pon el plan implementation_plan.md de la raiz sobre tenzor platform en marcha"**

El agente debe:

1. Crear `task.md` con checklist por fases.
2. Empezar por Fase 0.
3. Generar migraciones SQL, pero no ejecutarlas automaticamente en Supabase.
4. Pedir confirmacion antes de cualquier cambio manual en Supabase o accion irreversible.
5. Implementar fase por fase con tests.
6. Mantener Tenzor AI actual funcionando.
