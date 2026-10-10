#!/usr/bin/env bash
# docs/arquitectura.md -> docs/arquitectura.pdf (Mermaid rendered to SVG, printed by headless Chromium).
# Needs: docker, node/npx. The ingestion image (already built) provides Chromium.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
W=$(mktemp -d); chmod 777 "$W"; trap 'rm -rf "$W"' EXIT
cp docs/arquitectura.md "$W/in.md"

# 1. Every ```mermaid block -> SVG file + image reference
docker run --rm -u "$(id -u):$(id -g)" -v "$W:/data:z" minlag/mermaid-cli:11.17.1 \
  -i /data/in.md -o /data/out.md -e svg -b white >/dev/null

# 2. Markdown -> HTML
npx --yes marked@15.0.12 -i "$W/out.md" -o "$W/body.html" --gfm
cat > "$W/doc.html" <<HTML
<!doctype html><html lang="es"><head><meta charset="utf-8"><title>WanderSync: Documento Técnico de Arquitectura</title>
<style>
  @page { size: A4; margin: 18mm 16mm; }
  body { font: 10.5pt/1.5 "DejaVu Sans", system-ui, sans-serif; color: #10201f; }
  h1 { font-size: 20pt; color: #0b5f55; margin: 0 0 .3em; }
  h2 { font-size: 14pt; color: #0b5f55; border-bottom: 1px solid #d3dddb; padding-bottom: .2em; margin-top: 1.4em; break-after: avoid; }
  h3 { font-size: 11.5pt; margin-top: 1.1em; break-after: avoid; }
  table { border-collapse: collapse; width: 100%; font-size: 9pt; margin: .6em 0; break-inside: auto; }
  th, td { border: 1px solid #d3dddb; padding: 4px 6px; text-align: left; vertical-align: top; }
  th { background: #e8eeed; }
  tr { break-inside: avoid; }
  code { font: 8.5pt "DejaVu Sans Mono", monospace; background: #eef3f2; padding: 0 3px; border-radius: 3px; }
  pre { background: #eef3f2; padding: 8px 10px; border-radius: 6px; white-space: pre-wrap; font-size: 8.5pt; break-inside: avoid; }
  pre code { background: none; padding: 0; }
  img { display: block; max-width: 100%; max-height: 190mm; margin: .8em auto; break-inside: avoid; }
  hr { border: 0; border-top: 1px solid #d3dddb; margin: 1.2em 0; }
</style></head><body>
HTML
cat "$W/body.html" >> "$W/doc.html"
echo "</body></html>" >> "$W/doc.html"

# 3. HTML -> PDF with the Chromium baked into the ingestion image
docker run --rm -v "$W:/w:z" --entrypoint chromium wandersync-ingestion \
  --headless=new --no-sandbox --disable-gpu --no-pdf-header-footer \
  --print-to-pdf=/w/out.pdf "file:///w/doc.html" >/dev/null 2>&1
cp "$W/out.pdf" docs/arquitectura.pdf
echo "docs/arquitectura.pdf: $(du -h docs/arquitectura.pdf | cut -f1)"
