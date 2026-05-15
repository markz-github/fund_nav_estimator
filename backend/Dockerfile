FROM 192.168.50.50:13000/markz/python-runtime:py3.14-slim

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.mirrors.ustc.edu.cn/simple/
ARG PIP_TRUSTED_HOST=pypi.mirrors.ustc.edu.cn

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
        -i "${PIP_INDEX_URL}" \
        --trusted-host "${PIP_TRUSTED_HOST}" \
        --timeout 120 \
    && python -m pip install --no-cache-dir -r requirements.txt \
        -i "${PIP_INDEX_URL}" \
        --trusted-host "${PIP_TRUSTED_HOST}" \
        --timeout 120

COPY app ./app
COPY config ./config
COPY scripts ./scripts

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
