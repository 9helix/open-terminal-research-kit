# Open Terminal + research toolkit.
# Build from the folder that contains this file:
#   docker build -t open-terminal-research --build-arg RUN_USER=<user> .
#
# RUN_USER must be the user the base image runs as. Find it with:
#   docker inspect --format '{{.Config.User}}' ghcr.io/open-webui/open-terminal:latest
# (empty output = the image runs as root: use RUN_USER=root)
FROM ghcr.io/open-webui/open-terminal:latest

ARG RUN_USER=user
ARG OCR_LANGS="eng hrv"
ARG READER=auto
ARG INSTALL_FLAGS=""

USER root
COPY . /opt/research-kit
RUN chmod +x /opt/research-kit/install.sh \
 && /opt/research-kit/install.sh --langs "${OCR_LANGS}" --reader "${READER}" ${INSTALL_FLAGS} \
 && rm -rf /var/lib/apt/lists/* /root/.cache/pip
USER ${RUN_USER}
