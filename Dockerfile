FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/ledgerline
RUN useradd --system --uid 10001 --create-home ledgerline && chown ledgerline:ledgerline /srv/ledgerline
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=ledgerline:ledgerline app ./app
COPY --chown=ledgerline:ledgerline tests ./tests
USER ledgerline
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
