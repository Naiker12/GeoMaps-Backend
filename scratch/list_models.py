import os
import json
from google import genai
from dotenv import load_dotenv

load_dotenv()

def list_models():
    api_key = os.getenv("GOOGLE_API")
    if not api_key:
        print("Error: GOOGLE_API not found in .env")
        return

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})
    
    try:
        print("Listing available models...")
        for model in client.models.list():
            # Intentar ver qué atributos tiene el objeto model
            # print(dir(model))
            print(f"- {model.name}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    list_models()
