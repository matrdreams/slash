# Build NetrisTV/ws-scrcpy at the commit in PIN. Dependencies are installed
# inside this image and are not committed. Keep WS_SCRCPY_REF equal to PIN.
FROM node:20-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        android-tools-adb \
        ca-certificates \
        git \
        python3 \
        make \
        g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ws-scrcpy

ARG WS_SCRCPY_REPO=https://github.com/NetrisTV/ws-scrcpy.git
ARG WS_SCRCPY_REF=cd6cea6ebde17af6685c2b325183fc24bef9d52b

RUN git init \
    && git remote add origin "${WS_SCRCPY_REPO}" \
    && git fetch --depth 1 origin "${WS_SCRCPY_REF}" \
    && git checkout --detach FETCH_HEAD

COPY build.config.override.json config.yaml /opt/ws-scrcpy/

RUN npm install --no-audit --no-fund \
    && npm run dist \
    && npm install --omit=dev --prefix dist

ENV WS_SCRCPY_CONFIG=/opt/ws-scrcpy/config.yaml \
    ADB_HOST=host.docker.internal \
    ADB_PORT=5037

EXPOSE 8000
WORKDIR /opt/ws-scrcpy/dist
CMD ["node", "index.js"]
