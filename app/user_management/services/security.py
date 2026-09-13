"""Password hashing.

Uses the `bcrypt` library directly rather than passlib. passlib 1.7.4 (its
last release, 2020) reads `bcrypt.__about__.__version__`, which bcrypt 4.1
removed — the combination raises on every hash. Calling bcrypt directly is a
three-line API and removes an unmaintained dependency.

bcrypt rejects input beyond 72 BYTES rather than truncating it. The request
schemas cap password length to match, so this surfaces as a 422 at the edge
instead of a 500 from here.
"""

import bcrypt

# bcrypt's hard limit. Enforced at the schema layer; defined here so the
# constant has one home.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8

_ROUNDS = 12


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=_ROUNDS)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed stored hash, or input over 72 bytes. Either way the
        # credential does not verify — never propagate as a 500.
        return False
