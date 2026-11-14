# MISTER PLIS in a container (docs/DEPLOY_LINUX.md, docs/DEPLOY_WINDOWS.md; docs/PREP_PLAN.md R4).
# The code is in /app (replaced by a new image); the instance — config.toml, data/, secrets/ — is the volume
# /srv/mister-plis, and the lab's storage and backup folders are volumes too (/storage, /backup).
#
#   docker build --build-arg COMMIT=$(git rev-parse HEAD) -t mister-plis .
#   docker compose -f deploy/docker-compose.yml up -d
FROM python:3.12-slim

# git: tool sources and the modules' repositories (the inventory, the notebook) are git repositories
# openssh-client: ssh-keygen checks the release feed's signature (mister_plis/updates.py)
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates openssh-client \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 misterplis \
 && mkdir -p /srv/mister-plis /storage /backup \
 && chown misterplis:misterplis /srv/mister-plis /storage /backup

WORKDIR /app
# exactly the pinned versions, each checked against its checksum (scripts/lock.sh; docs/SECURITY_AUDIT.md M5)
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
# docs/ is read by the guide page; labs/ holds the lab files that come with the code; requirements.txt guards the
# base's packages when a tool source installs its own
COPY pyproject.toml ./
COPY mister_plis ./mister_plis
COPY modules ./modules
COPY labs ./labs
COPY docs ./docs
# the tool sources this release brings with it (bundled-tools.toml; put there by scripts/release.sh)
COPY bundled-tools ./bundled-tools

# which commit this image was built from (shown on Settings → Server & updates; there is no .git in the image)
ARG COMMIT=""
ARG COMMIT_DATE=""
ENV HOME=/home/misterplis \
    MISTER_PLIS_HOME=/srv/mister-plis \
    MISTER_PLIS_INSTALL=docker \
    MISTER_PLIS_SUPERVISED=1 \
    MISTER_PLIS_HOST=0.0.0.0 \
    MISTER_PLIS_PORT=8000 \
    MISTER_PLIS_COMMIT=${COMMIT} \
    MISTER_PLIS_COMMIT_DATE=${COMMIT_DATE} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

VOLUME ["/srv/mister-plis", "/storage", "/backup"]
EXPOSE 8000 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/version', timeout=3)"

# starts as root only to give the volumes Docker made to misterplis, then runs as misterplis (deploy/docker-entrypoint.sh)
COPY deploy/docker-entrypoint.sh /usr/local/bin/mister-plis-entrypoint
ENTRYPOINT ["mister-plis-entrypoint"]
CMD ["python", "-m", "mister_plis"]
