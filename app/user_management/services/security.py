"""Password hashing.

Uses the `bcrypt` library directly rather than passlib. passlib 1.7.4 (its
last release, 2020) reads `bcrypt.__about__.__version__`, which bcrypt 4.1
removed — the combination raises on every hash. Calling bcrypt directly is a
three-line API and removes an unmaintained dependency.

bcrypt rejects input beyond 72 BYTES rather than truncating it. The request
schemas cap password length to match, so this surfaces as a 422 at the edge
instead of a 500 from here.
"""

import re

import bcrypt

# bcrypt's hard limit. Enforced at the schema layer; defined here so the
# constant has one home.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8

_ROUNDS = 12

_HAS_UPPER = re.compile(r"[A-Z]")
_HAS_LOWER = re.compile(r"[a-z]")
_HAS_DIGIT = re.compile(r"\d")
# Anything not a letter/digit/whitespace counts as a special character —
# deliberately broad rather than a fixed punctuation set, so it doesn't
# reject a symbol the list-writer didn't think of.
_HAS_SPECIAL = re.compile(r"[^A-Za-z0-9\s]")


def password_strength_errors(password: str) -> list[str]:
    """What's missing for `password` to meet the complexity policy — empty if none.

    Checked at registration and password change, deliberately NOT at login
    (see docs/auth_flow.md — applying strength rules there would reject a
    valid pre-policy password, or leak the policy shape to an attacker).
    """
    errors = []
    if not _HAS_UPPER.search(password):
        errors.append("at least one uppercase letter")
    if not _HAS_LOWER.search(password):
        errors.append("at least one lowercase letter")
    if not _HAS_DIGIT.search(password):
        errors.append("at least one number")
    if not _HAS_SPECIAL.search(password):
        errors.append("at least one special character")
    return errors


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=_ROUNDS)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed stored hash, or input over 72 bytes. Either way the
        # credential does not verify — never propagate as a 500.
        return False
