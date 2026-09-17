# Production image for the FastAPI backend. Not used for local dev — local
# dev runs `uvicorn` directly against SQLite (see README.md); this image
# targets the docker-compose prod stack (Postgres + Caddy alongside it).

FROM python:3.12-slim

# Uses a non-root user throughout: a compromised process inside the
# container should not be root on the box.
RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

# setuptools' package discovery (pyproject.toml's [tool.setuptools.packages.find])
# needs the `app/` package present at install time, so this can't be split
# into a deps-only layer + a code layer the usual way — copy everything first.
COPY . .
RUN pip install --no-cache-dir . && chown -R app:app /app

USER app

EXPOSE 8000

# Alembic runs on every container start, not as a separate deploy step — a
# fresh box or a box mid-upgrade always ends up at the same schema before
# uvicorn accepts traffic. Single worker: see docker-compose.yml's comment
# on why (the e2-micro host has 1 GB RAM total, shared with Postgres).
ENTRYPOINT ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
