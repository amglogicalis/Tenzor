Hecho -- 1.AL crear un agente no se muestran todos los modelos reales que ofrecen los providers. Averigua los modelos disponibles mediante pruebas a la api.

Hecho -- 2.AL elegir configurar una api key de un provider, al elegir entre providers, se ve blanco y no se ve el nombre del provider pues sus letras son blancas tambien. Hacer mas estetico y acorde a la pagina la seleccion del provider al configurar la api key en el perfil

Hecho -- 3.Añadir poco a poco todos los providers de la opcion/capa B

Hecho -- 4.Explicamiento y revision del fallback, y si es posible mejorarlo

Hecho -- 5.Revisar que no deja borrar documentos de los conocimientos de un agente 

Hecho -- 6.Hacer que pueda haber rondas ilimitadas en las round tables

Hecho -- 7.Ver si se puede añadir provider un modelo corriendo via ollama en el pc local del user o en un server configurado por el user

En proceso -- 8.Funcion de limitar palabras por pompt/consulta con el objetivo de ahorro y optimizacion, tambien a decidir limite de archivos. Antes de hcaer cambios con este paso preguntame como lo implementaremos.

Extra 1: al iniciar sesion y escribir mal la contraseña, o que falta confirmacion, y ese tipo de errores, mostrar: "Has introducido mal la contraseña" u otra frase acorde al error en vez de read null o un error raro tipo sql 

Extra 2: mejorar la apariencia de los desplegables para que se vean mas en formato y estetica de la interfaz general al igual de algunas notificaciones de informacion, como por ejemplo la que informa sobre los agentes de una round table al hacerle click o los desplegables a la hora de crear una api key con un provider el desplegable de providers.

Extra 3: si es posible hacer mas vistoso, personalizado, estetico acorde a Arzor y asi verse mas fiable el correo que se manda para confirmar que es un correo real.

9. Hacer un onboarding que explique que es Arzor, como conseguir las api key gratis y como funcionan estas, como configurarlas y como usar arzor. Esto se ejcuta siempre que se detecta que el usuario se acab de craer y que es nuevo.

- PASO FINAL Y NUEVO COMIENZO/ ETAPA FINAL DE Arzor: Empezar la optimizacion, mejora y desarrollo completo y verdadero de Arzros AIs Cli, el antigravity/codex nuestro.
Este no va a tratar de ser un "especializador de modelos para cualquier cosa" si no que este sera la herramienta para ayudar a desarrolladores e informaticos. Mi plan es el siguiente:
Usaremos la misma base de Arzor, especiliazcion y round tables. Pero ahora sabiendo los modelos que tiene cada provider por las pruebas anteriores mantenemos el BYOK pero haciendo un filtrado de los mejores modelos en terminos de calidad/logica/disponibilidad/tokens, etc.
Tambien haremos un filtrado de providers, ya que puede que algun provider no de la calidad y las otras caracterisitcas necesarias con sus modelos y su plan free tier. 
El plan sera igual, una vez tengamos los mejores modelos, se les especialzia en programacion de un lenguaje, arquitectura cloud, DevOps, etc... Para luego poder usarlos individualmente mandandoles prompts y ellos actuando de forma autonoma en el ordenador crando archivos modificandolos y ejecutando comandos y scripts.
O usarlos todos juntos para tener tu equipo de informatica para tus proyectos. Integraremos fallback y demas y aprovecharemos la buena base que ya tenemos de Arzor.

- Paso final de todo: limpieza del entorno, y del repositorio de archivos no necesarios o redundantes,