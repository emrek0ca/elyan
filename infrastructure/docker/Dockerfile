FROM python:3.11-slim AS base

LABEL maintainer="ELYAN Team <support@elyan.ai>"
LABEL version="1.0.0"
LABEL description="ELYAN - Autonomous AI Assistant"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ELYAN_HOME=/opt/elyan \
    ELYAN_DATA=/data/elyan

WORKDIR ${ELYAN_HOME}

RUN groupadd -r elyan && useradd -r -g elyan -d ${ELYAN_HOME} -s /sbin/nologin elyan

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p ${ELYAN_DATA}/learning ${ELYAN_DATA}/knowledge ${ELYAN_DATA}/cache ${ELYAN_DATA}/logs && \
    chown -R elyan:elyan ${ELYAN_HOME} ${ELYAN_DATA}

EXPOSE 8080 9090

USER elyan

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "from core.production_monitor import HealthMonitor; h=HealthMonitor(); print(h.get_status())" || exit 1

ENTRYPOINT ["python", "-m"]
CMD ["core.agent"]
