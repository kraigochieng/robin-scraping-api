import shutil
from pathlib import Path

from robin_scraping_api.config import ENCRYPTED_PROFILES_DIR, PROFILES_DIR
from robin_scraping_api.encryption import build_fernet
from robin_scraping_api.settings import settings


def encrypt_profiles(
    *,
    profiles_dir: Path = PROFILES_DIR,
    encrypted_dir: Path = ENCRYPTED_PROFILES_DIR,
    key: str | None = None,
) -> None:
    """Write an encrypted copy of every profile file. Run locally after profile changes."""
    cipher = build_fernet(
        key=key if key is not None else settings.profiles_encryption_key.get_secret_value()
    )

    if encrypted_dir.exists():
        shutil.rmtree(encrypted_dir)
    encrypted_dir.mkdir(parents=True)

    for local_file in profiles_dir.rglob("*"):
        if not local_file.is_file():
            continue
        encrypted_file = encrypted_dir / local_file.relative_to(profiles_dir)
        encrypted_file = encrypted_file.with_name(encrypted_file.name + ".enc")
        encrypted_file.parent.mkdir(parents=True, exist_ok=True)
        encrypted_file.write_bytes(cipher.encrypt(local_file.read_bytes()))

    print("Profiles encrypted and ready to commit!")


if __name__ == "__main__":
    encrypt_profiles()
