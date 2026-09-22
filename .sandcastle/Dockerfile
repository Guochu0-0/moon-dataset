FROM node:22-bookworm

# Install system dependencies
# bzip2: needed to unpack the micromamba tarball below.
RUN apt-get update && apt-get install -y \
  git \
  curl \
  jq \
  bzip2 \
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

# Python 环境：直接用仓库自己的数据处理档，不另抄一份依赖清单（会漂）。
#
# 用的是数据处理档而非文档档：数据根整份只读挂进了沙箱（见 main.mts），agent 要真
# 跑得动镶嵌/重投影/裁切，就必须有 GDAL 与 pyproj。quarto 也在这份 yml 里，文档类
# 任务一并解决。
#
# micromamba 而不是 conda：单个静态二进制、自带 libmamba 求解器。environment-data.yml
# 的注释里写了经典 SAT 求解器在这一锅上解不动（实测 40 分钟无果）。
#
# COPY 的源是仓库根，所以构建必须带 --dockerfile 让 context 落在仓库根：
#   npm run sandcastle:build
RUN curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
  | tar -xvj -C /home/agent bin/micromamba

# --chown + 落在 agent 自己的家目录：COPY 进来的文件默认属 root，而 /tmp 带 sticky
# bit，非 root 用户删不掉别人的文件，收尾的 rm 会以 EPERM 失败。
COPY --chown=${AGENT_UID}:${AGENT_GID} environment-data.yml /home/agent/environment-data.yml

# 先剥掉 yml 末尾的 `pip: - -e .`：它要求仓库已在镜像里，而仓库是运行时 bind-mount
# 进来的，构建期装不了。这一步改由 hooks.onSandboxReady 的
# `pip install -e . --no-deps` 完成（见 main.mts）。
#
# 第一个 -e 先去掉 CR：仓库里的文件是 CRLF 行尾，否则 `/^  - pip:$/` 匹配的是
# `  - pip:\r`，剥不掉，micromamba 会照旧去装 `-e .` 然后失败。
# create 与 clean 必须同层：分层的话那 2 GB 包缓存会留在前一层里，镜像照样变大。
RUN cd /home/agent \
  && sed -e 's/\r$//' -e '/^  - pip:$/,$d' environment-data.yml > env-sandbox.yml \
  && grep -q 'gdal' env-sandbox.yml \
  && ! grep -q '\-e \.' env-sandbox.yml \
  && /home/agent/bin/micromamba create -y -p /home/agent/env -f env-sandbox.yml \
  && /home/agent/bin/micromamba clean -y --all \
  && rm environment-data.yml env-sandbox.yml

ENV PATH="/home/agent/env/bin:$PATH"
ENV CONDA_PREFIX="/home/agent/env"

# 这个环境的 etc/conda/activate.d/ 下有 9 个脚本（gdal、proj、quarto、deno、typst…），
# 靠 `conda activate` 才会执行。但 sandcastle 是 `docker exec` 进容器跑命令，只继承
# 镜像的 ENV、不会走 activate，所以必须在这儿把关键变量显式钉住。
#
# 不钉的后果都是静默的：GDAL 找不到 share/gdal 会退化成无投影；quarto 找不到
# QUARTO_SHARE_PATH 直接起不来。
ENV GDAL_DATA="/home/agent/env/share/gdal"
ENV CPL_ZIP_ENCODING="UTF-8"
ENV PROJ_DATA="/home/agent/env/share/proj"
# OFF 而不是 ON：ON 时 pyproj 会按需从网上取基准面网格。沙箱里那意味着要么卡住，
# 要么同一份输入在不同时间算出不同结果——这个项目要的是逐字节可复现。
ENV PROJ_NETWORK="OFF"

ENV QUARTO_SHARE_PATH="/home/agent/env/share/quarto"
ENV QUARTO_DENO="/home/agent/env/bin/deno"
ENV QUARTO_PANDOC="/home/agent/env/bin/pandoc"
ENV QUARTO_ESBUILD="/home/agent/env/bin/esbuild"
ENV QUARTO_TYPST="/home/agent/env/bin/typst"
ENV QUARTO_DART_SASS="/home/agent/env/bin/sass"

WORKDIR /home/agent

# In worktree sandbox mode, Sandcastle bind-mounts the git worktree at /home/agent/workspace
# and overrides the working directory to /home/agent/workspace at container start.
# Structure your Dockerfile so that /home/agent/workspace can serve as the project root.
ENTRYPOINT ["sleep", "infinity"]
