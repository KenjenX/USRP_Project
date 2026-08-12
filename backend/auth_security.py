from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher


_password_hash = PasswordHash((Argon2Hasher(),))


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except Exception:
        # A malformed or unsupported stored hash must fail authentication.
        return False
