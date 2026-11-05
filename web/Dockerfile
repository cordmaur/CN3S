FROM python:3.12-slim-bookworm

# The token-authenticated SQL connection uses Microsoft ODBC Driver 18.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
        -o /tmp/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/* /tmp/packages-microsoft-prod.deb

WORKDIR /app

# Install the existing web extra; no notebook kernel or editor is needed.
COPY pyproject.toml ./
COPY src/cn3s/ ./src/cn3s/
RUN pip install --no-cache-dir ".[web]"

COPY web/*.py ./web/
COPY web/templates/ ./web/templates/
COPY web/static/ ./web/static/
COPY src/hydro/ ./src/hydro/
COPY src/utils/ ./src/utils/

ENV PYTHONPATH=/app/src
ENV MPLBACKEND=Agg

EXPOSE 8000
CMD ["python", "-m", "gunicorn", "--workers", "1", "--bind", "0.0.0.0:8000", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "web.app:app"]
