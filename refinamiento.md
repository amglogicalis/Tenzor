New Steps:


Ahora tocara separar Arzor AIs CLI de Arzors AIs Plattform, ya que tenemos la base

Arzor AIs CLI sera una plataforma compartida pero separada usa las mismas base de datos, cuenta etc. 

Permite registrar una cuenta con su cli

La unica diferencia es que Arzor AIs CLI estara enfocado en la programacion desarrolo e informatica como codex y atigravity.

1. El primero paso sera revisar los modelos de cada provider, y seleccionar nosotros mismos los mas rentables/utiles/altamente disponibles y capaces para programacion, desarrollo e informatica.
Una vez los tengamos el usuario al mostrar sus modelos disponibles hara un filtrado mostrando solo los que sirven (esto solo en cli no en web)

2. El crear agentes se mantiene igual pudiendo craer agentes correctamente, y ademas intuyo aunque no lo he probado que estos agentes se pueden ver en web para tener una interfaz grafica para ser usada de forma correcta. A partir de lo siguiente no se debe harcodear para evitar errores.

3. Ahora deberemos hacer que en vez de por ejemplo .\venv\Scripts\python.exe cli/arzor.py list-agents, el comando se ejecute arzor list-agents. Aplicando lo mismo a los otros comandos.

4. Crear un manual de comandos para entenderlo

5. Crear un set-up comando para linux y windows que instale todas las dependencias y prepare el entorno una vez los usuarios se traigan a su pc el repo, y puedan uasr ya el cli sin problemas. Podemos usarlo tambien como onboarding de que debe configurar el user (en su .env) para usar el cli correctamente

6. Por ultimo añadiremos al funcion round table para que los agentes puedan discutir que hacer con tu consulta desde el pc. Y añadir la funcion exclusiva team para el cli, que permitira lanzar tareas de forma simultanea con distintos agentes sin conflictos (incluso permitiendo la comunicacion entre agentes) para ir haciendo cada uno una tarea como si fuera un equipo real en el pc

Con esto creamos buscamos crear un cli usable desde cualquie rlugar del ordenador, enfocado en crear agentes especialziados en el campo que quiera el user para lo que el quiera




- Paso final de todo: limpieza del entorno, y del repositorio de archivos no necesarios o redundantes,