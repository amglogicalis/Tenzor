import os
import re
from google.cloud import aiplatform
import vertexai

# --- CONFIGURACIÓN ---
CREDENTIALS_PATH = r"C:\mis-proyectos\Tenzor\service_account.json"
PROJECT_ID       = "753320073574"
REGION           = "us-central1"

# Tu Endpoint ID exacto
ENDPOINT_ID = "mg-endpoint-1eae4fb8-4883-4bfc-8355-08cdb1ee1bb9" 

# --- DEFINICIÓN DE PERSONAS (SYSTEM PROMPTS) ---
PERSONAS = {
    "1": {
        "nombre": "Tenzor Meteor (Normal)",
        "temp": 0.2,
        "prompt": "Eres Tenzor Meteor, un experto en DevOps y Cloud. Responde de forma técnica y concisa. Si te preguntan algo fuera de IT, responde: 'Lo siento, soy una IA especializada exclusivamente en desarrollo de software e infraestructuras Cloud. No puedo ayudarte con ese tema.'"
    },
    "2": {
        "nombre": "Modo Código Estricto (Sin explicaciones)",
        "temp": 0.0, # Temperatura 0 = Cero alucinaciones, respuestas deterministas
        "prompt": "Eres un generador de código puro. Tu única función es devolver código funcional, optimizado y sin bugs. NO saludes. NO des explicaciones previas ni posteriores. NO uses formato markdown a menos que sea estrictamente necesario. Devuelve ÚNICAMENTE el código."
    },
    "3": {
        "nombre": "Arquitecto Crítico (Evaluador de soluciones)",
        "temp": 0.3,
        "prompt": "Eres un Arquitecto Cloud Senior muy estricto. Cuando el usuario proponga una idea o arquitectura, tu trabajo es buscarle las vulnerabilidades, cuellos de botella de rendimiento y problemas de escalabilidad. Lista siempre los 'Pros', los 'Contras críticos' y propón una 'Solución Enterprise' mejor."
    }
}

def main():
    print("🔄 Inicializando cliente de Vertex AI...")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_PATH
    vertexai.init(project=PROJECT_ID, location=REGION)

    print(f"🔌 Conectando al Endpoint: {ENDPOINT_ID} ...")
    try:
        endpoint = aiplatform.Endpoint(ENDPOINT_ID)
    except Exception as e:
        print(f"❌ Error al conectar con el Endpoint: {e}")
        return

    print("\n=======================================================")
    print("🎭 SELECCIONA EL MODO DE LA IA")
    print("=======================================================")
    for key, data in PERSONAS.items():
        print(f"[{key}] - {data['nombre']}")
    
    seleccion = input("\nElige un número (1, 2 o 3) [Por defecto: 1]: ").strip()
    if seleccion not in PERSONAS:
        seleccion = "1"
        
    modo_activo = PERSONAS[seleccion]

    print("\n=======================================================")
    print(f"🚀 INICIANDO: {modo_activo['nombre']}")
    print("Escribe 'salir' para terminar")
    print("=======================================================\n")

    while True:
        prompt = input("Tú: ")
        
        if prompt.lower() in ['salir', 'exit', 'quit']:
            print("Desconectando... ¡Hasta luego!")
            break
        
        if not prompt.strip():
            continue

        try:
            # Formato ChatML usando el System Prompt de la Persona seleccionada
            prompt_chatml = f"<|im_start|>system\n{modo_activo['prompt']}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"

            # Enviamos la petición. Bajamos a 1024 tokens para respetar el límite de 2048 del contenedor
            response = endpoint.predict(
                instances=[{
                    "prompt": prompt_chatml,
                    "max_tokens": 1024, 
                    "temperature": modo_activo['temp'], 
                }]
            )
            
            if response.predictions:
                prediction = response.predictions[0]
                
                if isinstance(prediction, str):
                    reply = prediction
                elif isinstance(prediction, dict):
                    reply = prediction.get("content", prediction.get("text", prediction.get("outputs", str(prediction))))
                else:
                    reply = str(prediction)
                
                # --- LIMPIEZA ---
                if "Output:" in reply:
                    reply = reply.split("Output:", 1)[-1]
                if "<|im_start|>assistant" in reply:
                    reply = reply.split("<|im_start|>assistant")[-1]
                
                # Borramos los pensamientos internos (<think>...</think>)
                reply = re.sub(r'<think>.*?</think>', '', reply, flags=re.DOTALL)
                reply = reply.replace("<|im_end|>", "").strip()
                    
                print(f"\n🤖 {modo_activo['nombre']}:\n{reply}\n")
                print("-" * 60)
            else:
                print("\n⚠️ El modelo no devolvió ninguna predicción.\n")

        except Exception as e:
            print(f"\n❌ Error al consultar la IA: {e}\n")

if __name__ == "__main__":
    main()