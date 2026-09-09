# The WhatsApp bridge — Node + a real Chromium.
#
# open-wa automates WhatsApp Web, so this image needs an actual browser. That
# rules out a plain Node buildpack on most platforms and is why the bridge is
# deployed as a container while the API can be either.
#
# Two things about this image are load-bearing on a host:
#
#   - Chromium comes from the distro, not from Puppeteer's postinstall
#     downloader. That download is a common build failure (it fetches from
#     googlechromelabs.github.io at install time), and when it fails npm rolls
#     the whole install back and leaves node_modules empty.
#   - The session lives on a mounted disk, not in the image. The linked account
#     is a Chrome profile on disk; keep it inside the container and every deploy
#     asks someone to scan a pairing QR again. See WA_SESSION_DIR.

FROM node:22-bookworm-slim

ENV PUPPETEER_SKIP_DOWNLOAD=true \
    PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    NODE_ENV=production

# chromium: the browser open-wa drives.
# fonts-liberation + fonts-noto-color-emoji: WhatsApp Web renders text and
#   emoji; without fonts the page loads but the QR canvas and chat list are
#   blank boxes, which is a confusing way to fail.
# ca-certificates: TLS to web.whatsapp.com.
# dumb-init: PID 1 that reaps zombies and forwards signals. Chromium spawns a
#   tree of child processes, and Node as PID 1 leaves them behind on restart —
#   which eventually exhausts the container's memory.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        ca-certificates \
        fonts-liberation \
        fonts-noto-color-emoji \
        dumb-init \
    && rm -rf /var/lib/apt/lists/*

ENV WA_CHROME_PATH=/usr/bin/chromium \
    WA_SESSION_DIR=/var/data/wa-sessions

WORKDIR /app

# Dependencies as their own layer: package.json changes far less often than
# server.js, and reinstalling open-wa on every code push is a slow build.
COPY package.json package-lock.json .npmrc ./
RUN npm ci --omit=dev

COPY server.js ./

# node runs as a normal user; Chromium must never run as root even with
# --no-sandbox. The session directory is created and handed over here so a
# freshly mounted disk is writable on the first boot.
RUN mkdir -p /var/data/wa-sessions && chown -R node:node /var/data /app
USER node

EXPOSE 3001
# A container is not a session: this reports the HTTP surface being up, which is
# what a platform needs to route traffic. Whether WhatsApp is *linked* is the
# `connected` field in the body, and it is deliberately not a health failure —
# a bridge waiting for someone to scan a QR is working correctly.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD node -e "require('http').get({host:'127.0.0.1',port:process.env.PORT||3001,path:'/health'},r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

ENTRYPOINT ["dumb-init", "--"]
CMD ["node", "server.js"]
