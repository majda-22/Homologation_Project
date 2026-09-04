"""Services applicatifs d'authentification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database.database import SessionLocal
from app.infrastructure.database.models import Utilisateur


@dataclass(frozen=True)
class AuthenticatedUserDTO:
    id: int
    username: str
    role: str


def hash_password(password: str) -> str:
    return PasswordHasher().hash(password)


def verifier_password(password: str, hash: str) -> bool:
    try:
        return PasswordHasher().verify(hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


class AuthService:
    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self.session_factory = session_factory

    def authentifier(self, username: str, password: str) -> AuthenticatedUserDTO | None:
        with self.session_factory() as session:
            utilisateur = session.scalar(
                select(Utilisateur).where(Utilisateur.username == username.strip())
            )
            if utilisateur is None:
                return None
            if not utilisateur.is_active:
                return None
            if not verifier_password(password, utilisateur.password_hash):
                return None
            return AuthenticatedUserDTO(
                id=utilisateur.id,
                username=utilisateur.username,
                role=utilisateur.role.value,
            )
