ARG BACKEND_BASE_IMAGE=192.168.50.50:16060/markz/fund-nav-estimator-backend-base:py3.14-deps-20260524-193621
FROM ${BACKEND_BASE_IMAGE}

WORKDIR /app

COPY app ./app
COPY config ./config
COPY scripts ./scripts

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
