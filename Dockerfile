# API service (CPU) - the orchestration half. Deploys to Render (native runtime via
# render.yaml) or any container host. The GPU work lives in worker/ on RunPod.
FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py solution_app.py pipeline.py ./

EXPOSE 8000
ENV PORT=8000
ENV APP_MODULE=solution_app
CMD ["sh", "-c", "uvicorn ${APP_MODULE}:app --host 0.0.0.0 --port ${PORT}"]
