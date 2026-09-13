"""End-to-end walkthrough of the user_management API against a running server.

Exercises the whole module the way a client would — register, login, groups,
invitations, members, admin transfer — plus the main negative paths, and
finishes by showing what landed in the audit trail.

    # terminal 1
    uvicorn app.main:app --reload
    # terminal 2
    python scripts/smoke_walkthrough.py

Safe to re-run: every run uses fresh phone numbers.
"""

import asyncio
import random
import sys

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
PASSWORD = "correct-horse-battery"

# Fresh numbers each run so the script is re-runnable against the same dev db.
SUFFIX = random.randint(1000, 9999)
PHONES = {
    "mudit": f"+9190000{SUFFIX}1",
    "riya": f"+9190000{SUFFIX}2",
    "papa": f"+9190000{SUFFIX}3",
}

PASS = 0
FAIL = 0


def check(label: str, got: int, want: int, extra: str = "") -> None:
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
    mark = "PASS" if ok else "FAIL"
    line = f"  [{mark}] {label:<52} {got}"
    if not ok:
        line += f"  (expected {want})"
    if extra:
        line += f"  {extra}"
    print(line)


def section(title: str) -> None:
    print(f"\n{title}\n" + "-" * 72)


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as c:
        # ---------------------------------------------------------------
        section("1. REGISTRATION")

        users = {}
        for name, phone in PHONES.items():
            r = await c.post(
                f"{BASE}/auth/register",
                json={
                    "phone": phone,
                    "display_name": name.title(),
                    "password": PASSWORD,
                },
            )
            check(f"register {name}", r.status_code, 201)
            users[name] = {"phone": phone, "id": r.json().get("id")}

        r = await c.post(
            f"{BASE}/auth/register",
            json={
                "phone": PHONES["mudit"],
                "display_name": "Impostor",
                "password": PASSWORD,
            },
        )
        check("duplicate phone rejected", r.status_code, 409)

        r = await c.post(
            f"{BASE}/auth/register",
            json={"phone": "98765", "display_name": "Bad", "password": PASSWORD},
        )
        check("malformed phone rejected", r.status_code, 422)

        r = await c.post(
            f"{BASE}/auth/register",
            json={"phone": f"+9199999{SUFFIX}9", "display_name": "Bad", "password": "short"},
        )
        check("short password rejected", r.status_code, 422)

        # ---------------------------------------------------------------
        section("2. LOGIN")

        for name in users:
            r = await c.post(
                f"{BASE}/auth/login",
                json={"phone": users[name]["phone"], "password": PASSWORD},
            )
            check(f"login {name}", r.status_code, 200)
            users[name]["auth"] = {"Authorization": f"Bearer {r.json()['access_token']}"}

        wrong = await c.post(
            f"{BASE}/auth/login",
            json={"phone": PHONES["mudit"], "password": "wrong-password"},
        )
        unknown = await c.post(
            f"{BASE}/auth/login",
            json={"phone": "+919111111111", "password": "wrong-password"},
        )
        check("wrong password rejected", wrong.status_code, 401)
        check("unknown phone rejected", unknown.status_code, 401)
        check(
            "both failures identical (no enumeration)",
            int(wrong.json()["detail"] == unknown.json()["detail"]),
            1,
            f'-> "{wrong.json()["detail"]}"',
        )

        mudit, riya, papa = users["mudit"], users["riya"], users["papa"]

        # ---------------------------------------------------------------
        section("3. AUTHENTICATION IS ENFORCED")

        r = await c.get(f"{BASE}/groups")
        check("no token rejected", r.status_code, 401)

        r = await c.get(f"{BASE}/groups", headers={"Authorization": "Bearer not.a.jwt"})
        check("garbage token rejected", r.status_code, 401)

        r = await c.get(f"{BASE}/auth/me", headers=mudit["auth"])
        check("valid token accepted", r.status_code, 200, f'-> {r.json()["display_name"]}')

        r = await c.get(f"{BASE}/auth/me/quota", headers=mudit["auth"])
        check(
            "quota readable",
            r.status_code,
            200,
            f'-> {r.json()["files_used_today"]}/{r.json()["cap_files"]} uploads',
        )

        # ---------------------------------------------------------------
        section("4. GROUPS")

        r = await c.post(
            f"{BASE}/groups",
            json={"name": "Sharma Family", "description": "Everyday identity papers"},
            headers=mudit["auth"],
        )
        check("create group", r.status_code, 201, f'-> role={r.json()["my_role"]}')
        group = r.json()["id"]

        r = await c.get(f"{BASE}/groups/{group}", headers=riya["auth"])
        check("non-member gets 404 (not 403)", r.status_code, 404)

        # ---------------------------------------------------------------
        section("5. INVITATIONS")

        r = await c.post(
            f"{BASE}/groups/{group}/invite",
            json={"phone": riya["phone"]},
            headers=mudit["auth"],
        )
        check("admin invites Riya", r.status_code, 201)
        inv_riya = r.json()["id"]

        r = await c.post(
            f"{BASE}/groups/{group}/invite",
            json={"phone": "+919111111111"},
            headers=mudit["auth"],
        )
        check("invite unregistered phone -> 404", r.status_code, 404)

        r = await c.post(
            f"{BASE}/groups/{group}/invite",
            json={"phone": riya["phone"]},
            headers=mudit["auth"],
        )
        check("duplicate pending invite -> 409", r.status_code, 409)

        r = await c.get(f"{BASE}/invitations", headers=riya["auth"])
        check(
            "Riya sees her invitation",
            len(r.json()),
            1,
            f'-> "{r.json()[0]["group_name"]}" from {r.json()[0]["invited_by"]["display_name"]}',
        )

        r = await c.get(f"{BASE}/invitations", headers=papa["auth"])
        check("Papa sees none of it", len(r.json()), 0)

        r = await c.post(f"{BASE}/invitations/{inv_riya}/accept", headers=papa["auth"])
        check("outsider cannot accept it", r.status_code, 404)

        r = await c.post(f"{BASE}/invitations/{inv_riya}/accept", headers=riya["auth"])
        check("Riya accepts", r.status_code, 204)

        r = await c.post(f"{BASE}/invitations/{inv_riya}/decline", headers=riya["auth"])
        check("decline after accept -> 409", r.status_code, 409)

        # Papa joins too.
        r = await c.post(
            f"{BASE}/groups/{group}/invite",
            json={"phone": papa["phone"]},
            headers=mudit["auth"],
        )
        inv_papa = r.json()["id"]
        await c.post(f"{BASE}/invitations/{inv_papa}/accept", headers=papa["auth"])

        # ---------------------------------------------------------------
        section("6. MEMBERS")

        r = await c.get(f"{BASE}/groups/{group}/members", headers=riya["auth"])
        roster = ", ".join(f'{m["account"]["display_name"]}({m["role"]})' for m in r.json())
        check("member list", len(r.json()), 3, f"-> {roster}")

        r = await c.delete(
            f"{BASE}/groups/{group}/members/{papa['id']}", headers=riya["auth"]
        )
        check("member cannot remove another -> 403", r.status_code, 403)

        r = await c.delete(
            f"{BASE}/groups/{group}/members/{mudit['id']}", headers=mudit["auth"]
        )
        check("admin cannot remove self -> 409", r.status_code, 409)

        r = await c.delete(f"{BASE}/groups/{group}/members/me", headers=mudit["auth"])
        check("sole admin cannot leave -> 409", r.status_code, 409)

        r = await c.delete(
            f"{BASE}/groups/{group}/members/{papa['id']}", headers=mudit["auth"]
        )
        check("admin removes Papa", r.status_code, 204)

        # ---------------------------------------------------------------
        section("7. ADMIN TRANSFER")

        r = await c.post(
            f"{BASE}/groups/{group}/transfer-admin",
            json={"new_admin_id": riya["id"]},
            headers=mudit["auth"],
        )
        check("Mudit hands admin to Riya", r.status_code, 204)

        r = await c.get(f"{BASE}/groups/{group}", headers=riya["auth"])
        check("Riya is now admin", r.json()["my_role"], "admin")

        r = await c.get(f"{BASE}/groups/{group}", headers=mudit["auth"])
        check("Mudit demoted to member", r.json()["my_role"], "member")

        r = await c.delete(f"{BASE}/groups/{group}", headers=mudit["auth"])
        check("former admin loses powers -> 403", r.status_code, 403)

        r = await c.delete(f"{BASE}/groups/{group}/members/me", headers=mudit["auth"])
        check("Mudit can now leave", r.status_code, 204)

        # ---------------------------------------------------------------
        section("8. PASSWORD CHANGE")

        r = await c.post(
            f"{BASE}/auth/me/password",
            json={"current_password": "not-the-password", "new_password": "brand-new-secret"},
            headers=riya["auth"],
        )
        check("wrong current password -> 401", r.status_code, 401)

        r = await c.post(
            f"{BASE}/auth/me/password",
            json={"current_password": PASSWORD, "new_password": "brand-new-secret"},
            headers=riya["auth"],
        )
        check("password changed", r.status_code, 204)

        r = await c.post(
            f"{BASE}/auth/login",
            json={"phone": riya["phone"], "password": "brand-new-secret"},
        )
        check("login with new password", r.status_code, 200)

        r = await c.post(
            f"{BASE}/auth/login", json={"phone": riya["phone"], "password": PASSWORD}
        )
        check("old password no longer works", r.status_code, 401)

        # ---------------------------------------------------------------
        section("9. AUDIT TRAIL")
        print("  (read straight from the dev database)")

    import sqlite3

    conn = sqlite3.connect("docvault_dev.db")
    rows = conn.execute(
        "SELECT table_name, operation, COUNT(*) FROM audit_logs "
        "GROUP BY table_name, operation ORDER BY table_name, operation"
    ).fetchall()
    print(f"\n  {'TABLE':<18} {'OP':<8} COUNT")
    for table, op, count in rows:
        print(f"  {table:<18} {op:<8} {count}")

    leaked = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE new_values LIKE '%secret_hash%' "
        "OR old_values LIKE '%secret_hash%'"
    ).fetchone()[0]
    check("\n  no secret_hash anywhere in the trail", leaked, 0)

    attributed = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE actor_id IS NOT NULL"
    ).fetchone()[0]
    anonymous = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE actor_id IS NULL"
    ).fetchone()[0]
    print(f"  attributed rows: {attributed}   unattributed (registration): {anonymous}")
    conn.close()

    print("\n" + "=" * 72)
    print(f"  {PASS} passed, {FAIL} failed")
    print("=" * 72)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
