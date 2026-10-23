FROM python:3.12.14-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/tmp \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 demandiq \
    && useradd --uid 10001 --gid 10001 --no-create-home demandiq

WORKDIR /app
COPY requirements-runtime.lock pyproject.toml README.md ./
RUN python -m pip install --no-cache-dir -r requirements-runtime.lock
COPY backend ./backend
COPY ml ./ml
COPY scripts ./scripts
COPY configs ./configs
RUN python -m pip install --no-deps --no-build-isolation . \
    && python -m pip check \
    && mkdir -p /runtime/data /runtime/artifacts \
    && chown -R 10001:10001 /runtime

USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
