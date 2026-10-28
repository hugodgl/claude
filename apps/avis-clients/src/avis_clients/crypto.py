"""Chiffrement des jetons de plateforme stockés en base (Fernet, clé dédiée `TOKENS_KEY`).

Choix : une clé **distincte** de `SESSION_SECRET`. Changer le secret de session (invalidation des cookies
après un incident) ne doit pas rendre illisibles les jetons de Pages Facebook ; et la clé de chiffrement
n'a pas à transiter par le module de signature des cookies. Génération :
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

MISSING_KEY_MESSAGE = (
    "TOKENS_KEY manquant dans .env : générez-la avec "
    "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
    "puis relancez l'application."
)
UNREADABLE_MESSAGE = ("jeton illisible : TOKENS_KEY a changé depuis l'enregistrement de la source ; "
                      "reliez de nouveau la page pour enregistrer un jeton.")


class TokenKeyError(RuntimeError):
    """Clé absente, invalide, ou jeton chiffré avec une autre clé."""


def is_valid_fernet_key(key: str | None) -> bool:
    if not key:
        return False
    try:
        Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except (ValueError, TypeError):
        return False
    return True


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")


class TokenCipher:
    """Chiffre / déchiffre les jetons. Sans clé, toute opération échoue avec un message explicite
    (jamais de stockage en clair par défaut silencieux)."""

    def __init__(self, key: str | None):
        key = (key or "").strip() or None
        if key and not is_valid_fernet_key(key):
            raise TokenKeyError("TOKENS_KEY invalide : attendu une clé Fernet (44 caractères base64 url-safe).")
        self._fernet = Fernet(key.encode("utf-8")) if key else None

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plain: str) -> str:
        if self._fernet is None:
            raise TokenKeyError(MISSING_KEY_MESSAGE)
        return self._fernet.encrypt(plain.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        if self._fernet is None:
            raise TokenKeyError(MISSING_KEY_MESSAGE)
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError) as e:
            raise TokenKeyError(UNREADABLE_MESSAGE) from e
