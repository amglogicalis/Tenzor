from google.cloud import aiplatform

# Tus credenciales extraídas de los logs
PROJECT_ID = "753320073574"
REGION = "us-central1"
ENDPOINT_ID = "21770879985778688"

def check_vertex_endpoint():
    print(f"Conectando a Google Cloud Vertex AI en la región {REGION}...\n")
    
    # Inicializar el cliente
    aiplatform.init(project=PROJECT_ID, location=REGION)

    try:
        # Recuperar el objeto del endpoint
        endpoint = aiplatform.Endpoint(endpoint_name=ENDPOINT_ID)
        
        print("-" * 40)
        print(f"Endpoint encontrado: {endpoint.display_name}")
        print("-" * 40)
        
        # Extraer la lista de modelos desplegados
        deployed_models = endpoint.deployed_models
        
        if not deployed_models:
            print("⏳ ESTADO: El clúster se está creando o el modelo se está descargando.")
            print("Vuelve a intentar en unos minutos. (Puede tardar hasta 25 min).")
        else:
            print("✅ ESTADO: ¡Modelo desplegado con éxito!")
            print("\nDetalles de los modelos en este endpoint:")
            for model in deployed_models:
                print(f" - ID de despliegue: {model.id}")
                print(f" - Recurso del modelo: {model.model}")
                print(f" - Tipo de máquina: {model.dedicated_resources.machine_spec.machine_type}")
                print(f" - Acelerador (GPU): {model.dedicated_resources.machine_spec.accelerator_type.name}")
                print(f" - Cantidad de GPUs: {model.dedicated_resources.machine_spec.accelerator_count}")
                
    except Exception as e:
        print(f"❌ Error al consultar el endpoint: {e}")
        print("Asegúrate de estar autenticado ejecutando: gcloud auth application-default login")

if __name__ == "__main__":
    check_vertex_endpoint()