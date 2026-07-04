# Heyu X10 Bridge — HA OS add-on image
# Debian base so heyu compiles with the same glibc toolchain proven on the
# existing Ubuntu x10 box. (Alpine/musl is possible but riskier for heyu.)
ARG BUILD_FROM=debian:bookworm-slim
FROM ${BUILD_FROM}

# heyu version + source URL (verify URL in Phase 2; heyu.org/download)
ARG HEYU_VERSION=2.10
# heyu.org's HTTPS cert is for *.github.com (mismatch); the 301 redirects to
# plain HTTP on www.heyu.org. Use the HTTP URL directly.
ARG HEYU_URL=http://www.heyu.org/download/heyu-${HEYU_VERSION}.tar.gz

# Build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl tar \
        python3 python3-pip python3-venv \
        jq \
    && rm -rf /var/lib/apt/lists/*

# Build heyu from source.
# NOTE: heyu's ./Configure is normally interactive. We pipe default answers so
# it runs non-interactively; the exact prompts/answers may differ between heyu
# versions and are confirmed in Phase 2 against the real archive. If Configure
# supports a defaults flag or config file, prefer that here.
RUN mkdir -p /opt/heyu-build && cd /opt/heyu-build \
    && curl -fsSL -o heyu.tar.gz "${HEYU_URL}" \
    && tar xzf heyu.tar.gz \
    && cd heyu-${HEYU_VERSION} \
    && sh Configure linux \
    && sed -i 's/^CFLAGS = /CFLAGS = -fcommon /' Makefile \
    && make \
    && printf '4\n' | make install \
    && which heyu

# Python deps for the bridge
RUN pip3 install --no-cache-dir --break-system-packages paho-mqtt PyYAML

# App
WORKDIR /app
COPY devices.yaml /app/devices.yaml
COPY bridge.py /app/bridge.py
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
