import base64
import os
import shutil

from cryptography.fernet import Fernet

from robin_scraping_api.config import ENCRYPTED_PROFILES_DIR, PROFILES_DIR
from robin_scraping_api.settings import settings


def encrypt_profiles():
    """Run locally after creating/updating profiles"""
    f = Fernet(settings.profiles_encryption_key.encode())

    if os.path.exists(ENCRYPTED_PROFILES_DIR):
        shutil.rmtree(ENCRYPTED_PROFILES_DIR)
    os.makedirs(ENCRYPTED_PROFILES_DIR)

    for root, dirs, files in os.walk(PROFILES_DIR):
        for file in files:
            local_file = os.path.join(root, file)
            relative_path = os.path.relpath(local_file, PROFILES_DIR)
            encrypted_file = os.path.join(
                ENCRYPTED_PROFILES_DIR, relative_path + ".enc"
            )

            os.makedirs(os.path.dirname(encrypted_file), exist_ok=True)

            with open(local_file, "rb") as fp:
                encrypted = f.encrypt(fp.read())

            with open(encrypted_file, "wb") as fp:
                fp.write(encrypted)

    print("Profiles encrypted and ready to commit!")


if __name__ == "__main__":
    encrypt_profiles()
