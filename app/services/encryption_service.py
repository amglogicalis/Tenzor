import base64
import os
import hashlib
import logging
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app import config

logger = logging.getLogger(__name__)

class EncryptionService:
    def __init__(self):
        # Derivar una clave de 32 bytes (256 bits) de ARZOR_ENCRYPTION_KEY usando SHA-256
        enc_key = config.ARZOR_ENCRYPTION_KEY or "fallback-arzor-encryption-key-please-change-in-prod"
        self.key_bytes = hashlib.sha256(enc_key.encode("utf-8")).digest()
        self.aesgcm = AESGCM(self.key_bytes)

    def encrypt(self, plain_text: str) -> str:
        """
        Cifra un texto plano y devuelve el resultado en formato base64 que incluye el nonce.
        Formato devuelto: nonce_b64.ciphertext_b64
        """
        if not plain_text:
            return ""
        try:
            nonce = os.urandom(12)  # Nonce de 12 bytes recomendado para AES-GCM
            ciphertext = self.aesgcm.encrypt(nonce, plain_text.encode("utf-8"), None)
            
            nonce_b64 = base64.b64encode(nonce).decode("utf-8")
            ciphertext_b64 = base64.b64encode(ciphertext).decode("utf-8")
            return f"{nonce_b64}.{ciphertext_b64}"
        except Exception as e:
            logger.error(f"Error cifrando datos: {e}")
            raise ValueError("No se pudo cifrar la clave de API.")

    def decrypt(self, encrypted_text: str) -> str:
        """
        Descifra un texto cifrado en formato nonce_b64.ciphertext_b64 y devuelve el texto plano.
        """
        if not encrypted_text:
            return ""
        try:
            parts = encrypted_text.split(".")
            if len(parts) != 2:
                raise ValueError("Formato de texto cifrado inválido.")
            
            nonce = base64.b64decode(parts[0])
            ciphertext = base64.b64decode(parts[1])
            
            decrypted = self.aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted.decode("utf-8")
        except Exception as e:
            logger.error(f"Error descifrando datos: {e}")
            raise ValueError("No se pudo descifrar la clave de API. Verifica la clave de cifrado.")

# Singleton global
encryption_service = EncryptionService()
