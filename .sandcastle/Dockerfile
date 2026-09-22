FROM node:22-bookworm

# Install system dependencies
# python3-venv/-pip: this repo is Python; the agent needs to run pytest.
RUN apt-get update && apt-get install -y \
  git \
  curl \
  jq \
  python3-venv \
  python3-pip \
  && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
  && apt-get update && apt-get install -y gh \
  && rm -rf /var/lib/apt/lists/*

# Build-args for UID/GID alignment: sandcastle docker build-image
# defaults these to the host user's UID/GID so image-built files
# and bind-mounted files share an owner without runtime chown.
ARG AGENT_UID=1000
ARG AGENT_GID=1000

# Rename the base image's "node" user to "agent" and align UID/GID.
RUN groupmod -o -g $AGENT_GID node && usermod -o -u $AGENT_UID -g $AGENT_GID -d /home/agent -m -l agent node
USER ${AGENT_UID}:${AGENT_GID}

# Install Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | bash

# Add Claude to PATH
ENV PATH="/home/agent/.local/bin:$PATH"

# Python venv for the repo's light tier (environment.yml minus GDAL/pyproj).
# GDAL/pyproj are conda-only and are NOT installed here — see environment-data.yml.
# Everything outside moondata.raster works without them, which covers the test suite.
RUN python3 -m venv /home/agent/venv \
  && /home/agent/venv/bin/pip install --no-cache-dir "numpy>=1.24" pytest
ENV PATH="/home/agent/venv/bin:$PATH"
ENV VIRTUAL_ENV="/home/agent/venv"

WORKDIR /home/agent

# In worktree sandbox mode, Sandcastle bind-mounts the git worktree at /home/agent/workspace
# and overrides the working directory to /home/agent/workspace at container start.
# Structure your Dockerfile so that /home/agent/workspace can serve as the project root.
ENTRYPOINT ["sleep", "infinity"]
