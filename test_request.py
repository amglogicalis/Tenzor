import httpx

url = "http://127.0.0.1:8000/v1/chat/completions"
headers = {
    "Authorization": "Bearer tenzor-c41a63ce7244e22de59a73fd79abccf1",
    "Content-Type": "application/json"
}

# 1. Prueba de pregunta de programación (Debería responder bien)
payload_programming = {
    "messages": [
        {"role": "user", "content": "¿Cómo creo un recurso S3 simple en Terraform?"}
    ],
    "temperature": 0.7
}

print("--- Probando pregunta válida (Terraform) ---")
try:
    response = httpx.post(url, json=payload_programming, headers=headers, timeout=30.0)
    print(f"Status Code: {response.status_code}")
    print("Respuesta:")
    print(response.json()["choices"][0]["message"]["content"])
except Exception as e:
    print(f"Error: {e}")

print("\n-------------------------------------------")

# 2. Prueba de pregunta fuera de tema (Debería ser rechazada por el System Prompt)
payload_offtopic = {
    "messages": [
        {"role": "user", "content": "Dame una receta para hacer pizza napolitana"}
    ],
    "temperature": 0.7
}

print("--- Probando pregunta fuera de tema (Pizza) ---")
try:
    response = httpx.post(url, json=payload_offtopic, headers=headers, timeout=30.0)
    print(f"Status Code: {response.status_code}")
    print("Respuesta:")
    print(response.json()["choices"][0]["message"]["content"])
except Exception as e:
    print(f"Error: {e}")
