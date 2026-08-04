# Standalone image for the rendering prototype.
#
# Deliberately separate from the application stack: this is a throwaway
# comparison, and Chromium's system dependencies have no business in the
# Django image.
#
# Linux is the point — these numbers should reflect what a deployment would
# actually see, not what a Windows host does.
FROM node:22-bookworm-slim

ENV NODE_ENV=development \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# fonts-dejavu-core gives both engines the *same* font family to work with,
# which is what makes the visual comparison meaningful. Without it Satori has
# no font at all (it has no system-font fallback) and Chromium would silently
# substitute something else.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY package.json ./
RUN npm install --no-audit --no-fund

# Chromium + its system libraries. This single line is most of the size
# difference between the two approaches, and is itself a finding.
RUN npx playwright install --with-deps chromium

COPY . .

CMD ["node", "src/index.js"]
