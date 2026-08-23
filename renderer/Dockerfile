FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PORT=8080

WORKDIR /app

# Fonts must be installed here, not in Django: this is the process that lays
# out text, and a missing family means the wrong glyphs in every export.
#
# `fonts-roboto` earns its place beyond the defaults. Templates imported from
# real artwork are set in the faces designers actually use, and a headline
# measured against a condensed face reflows into three lines when it is laid
# out in DejaVu Sans — which is wider than almost anything a flyer is set in.
# Roboto ships a Condensed cut, so the two shapes that matter (a normal body
# face and a narrow display one) are both covered. See html_builder.FONT_STACKS
# for the families a template is allowed to name.
#
# `fonts-dancingscript` covers the third shape: luxury property artwork sets
# its headline in flowing calligraphy, and laying that out in a serif is the
# single most obvious way an imported template stops looking like its source.
# The copperplate faces those flyers actually use are proprietary; this is the
# closest formal script Debian ships, and near-right reads as the same design
# where a serif does not.
# The second row of packages is the authoring palette: six more open-licensed
# families so an agent building a design from scratch has real typographic
# range (an elegant garamond, a geometric sans, a rounded face, a slab, a
# retro script, a soft display). All from Debian's own archive — this
# container stays networkless at run time and every family here is named in
# html_builder.FONT_STACKS and vendored for the editor canvas, so the three
# surfaces keep drawing the same glyphs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core fonts-liberation2 fonts-roboto fonts-dancingscript \
        fonts-ebgaramond fonts-lato fonts-quicksand fonts-roboto-slab \
        fonts-lobstertwo fonts-comfortaa \
        ca-certificates curl \
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
