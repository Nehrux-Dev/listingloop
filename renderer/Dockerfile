FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PORT=8080

WORKDIR /app

# Fonts must be installed here, not in Django: this is the process that lays
# out text, and a missing family means the wrong glyphs in every export.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core fonts-liberation2 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

RUN npx playwright install --with-deps chromium

COPY . .

EXPOSE 8080

# Chromium's memory is the constraint here (~700 MB peak per the Step 4
# prototype), which is why this is its own container with its own limits
# rather than sharing the Django process.
CMD ["node", "src/server.js"]
