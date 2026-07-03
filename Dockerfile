FROM ubuntu:24.04

# Non-interactive apt, sane locale
ENV DEBIAN_FRONTEND=noninteractive \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

# Toolchain the APR tool shells out to (gcc/g++/gcov) plus Python.
# libasan is required for the --enable-asan code path.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
      g++ \
      libasan8 \
      python3 \
      python3-venv \
      python3-pip \
      ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps into an isolated venv (Ubuntu 24.04 is PEP 668
# "externally managed" and blocks pip into the system interpreter).
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Install the tool itself
WORKDIR /opt/apr
COPY apr_tool/ /opt/apr/apr_tool/

# Mount points for the user's buggy code/tests (input) and the patch (output)
VOLUME ["/input", "/output"]

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
