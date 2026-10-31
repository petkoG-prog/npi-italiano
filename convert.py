#!/usr/bin/env python3
"""Convert NPI exercise PDFs to interactive HTML exercise pages.

Supports:
  • Text-layer PDFs (levels 1 & 3): blank detection via trailing/leading spaces
  • Scanned PDFs    (levels 2 & 4): EasyOCR + horizontal-gap detection
"""
import pymupdf, os, re, json, sys
from html import escape as esc

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = (
    "D:/Games/Marin T., Ruggieri L., Magnelli S., Cernigliaro M.A., Spinosa E."
    " - Nuovissimo Progetto Italiano - 2019-2022"
)
OUT = "D:/Games/NPI"

PDFS = {
    1: f"{BASE}/1/Ruggieri L., Magnelli S., Marin T."
       f" - Nuovissimo Progetto italiano 1. A1-A2. Quaderno degli esercizi - 2019.pdf",
    2: f"{BASE}/2/Ruggieri L., Magnelli S., Marin T."
       f" - Nuovissimo Progetto Italiano 2. B1-B2. Quaderno degli Esercizi - 2020.pdf",
    3: f"{BASE}/3/Cernigliaro M.A."
       f" - Nuovissimo Progetto italiano 3. C1. Quaderno degli esercizi - 2020.pdf",
    4: f"{BASE}/4/Spinosa E."
       f" - Nuovissimo Progetto italiano 4. C2. Quaderno degli esercizi - 2022.pdf",
}

LEVEL_META = {
    1: {'cefr': 'A1–A2', 'color': 'green',  'title': 'Elementare'},
    2: {'cefr': 'B1–B2', 'color': 'blue',   'title': 'Intermedio'},
    3: {'cefr': 'C1',    'color': 'orange',  'title': 'Avanzato'},
    4: {'cefr': 'C2',    'color': 'red',     'title': 'Padronanza'},
}

# ── Blank detection ──────────────────────────────────────────────────────────

def text_to_html(text: str) -> str:
    """
    Convert a PDF text block to HTML, replacing blank markers with <input>.
    A blank is signalled by: line[i] ends with trailing space AND line[i+1]
    starts with a leading space. If the following line begins with (N) or
    (N. Verb), that text becomes the input's placeholder.
    """
    from html import escape as esc

    lines = text.split('\n')
    out = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        has_leading  = line.startswith(' ') or line.startswith('\t')
        has_trailing = line != line.rstrip()

        nxt = lines[i + 1] if i + 1 < len(lines) else ''
        next_has_leading = nxt.startswith(' ') or nxt.startswith('\t')

        # ── Pure blank line with leading space = isolated blank field ──
        if not stripped and has_leading:
            out.append('<input type="text" class="ex-input" spellcheck="true" autocomplete="off"> ')
            continue
        if not stripped:
            continue

        # ── Line that follows a blank ──
        if has_leading:
            hint_m = re.match(r'^\(([^)]+)\)\s*(.*)', stripped, re.DOTALL)
            if hint_m:
                hint = '(' + hint_m.group(1).strip() + ')'
                rest = hint_m.group(2).strip()
                out.append(
                    f'<input type="text" class="ex-input" placeholder="{esc(hint)}"'
                    f' title="{esc(hint)}" spellcheck="true" autocomplete="off">'
                )
                if rest:
                    out.append(f' <span>{esc(rest)}</span>')
            else:
                out.append('<input type="text" class="ex-input" spellcheck="true" autocomplete="off"> ')
                out.append(f'<span>{esc(stripped)}</span>')
        else:
            out.append(f'<span>{esc(stripped)}</span>')

        # ── Trailing blank at end of line if next line doesn't signal it ──
        if has_trailing and not next_has_leading:
            out.append(' <input type="text" class="ex-input" spellcheck="true" autocomplete="off">')

        out.append(' ')

    return ''.join(out).strip()


# ── Image extraction (text-layer PDFs) ───────────────────────────────────────

def extract_page_images(page, doc, page_num: int, level: int,
                        pw: float, ph: float) -> list:
    """
    Return list of (y0, x0, html_snippet) for each meaningful image on the page.
    Images are saved to exercises/<level>/img/.
    """
    img_dir = os.path.join(OUT, 'exercises', str(level), 'img')
    os.makedirs(img_dir, exist_ok=True)

    seen = set()
    results = []

    for img_info in page.get_images(full=True):
        xref   = img_info[0]
        w_px   = img_info[2]
        h_px   = img_info[3]

        # Skip tiny decorative glyphs
        if w_px < 60 or h_px < 60:
            continue

        for rect in page.get_image_rects(xref):
            x0, y0, x1, y1 = rect
            w_pg = x1 - x0
            h_pg = y1 - y0

            # Skip images in the header strip or footer strip
            if y0 < 72 or y1 > ph - 18:
                continue
            # Skip images too small on the page
            if w_pg < 28 or h_pg < 28:
                continue

            key = (xref, round(y0, 1))
            if key in seen:
                continue
            seen.add(key)

            try:
                base   = doc.extract_image(xref)
                ext    = base.get('ext', 'png')
                idx    = len(results)
                fname  = f'p{page_num:03d}_{idx:02d}.{ext}'
                fpath  = os.path.join(img_dir, fname)
                with open(fpath, 'wb') as f:
                    f.write(base['image'])

                width_pct = min(int(w_pg / pw * 100), 100)
                html = (
                    f'<div class="ex-image">'
                    f'<img src="img/{fname}" alt="" loading="lazy" '
                    f'style="max-width:{width_pct}%;max-height:320px;object-fit:contain">'
                    f'</div>'
                )
                results.append((y0, x0, html))
            except Exception:
                pass

    return results


# ── Overlay layout (text-layer PDFs rendered as image) ───────────────────────

def get_blank_positions(page, pw: float, ph: float) -> list[dict]:
    """Extract blank underlines from horizontal drawing strokes, as 0-1 fractions."""
    blanks = []
    for d in page.get_drawings():
        if d.get('type') != 's':
            continue
        rect = d['rect']
        if abs(rect.y1 - rect.y0) >= 3:    # must be nearly horizontal
            continue
        w = rect.x1 - rect.x0
        if w < 15:                           # too short to be a blank field
            continue
        y_mid = (rect.y0 + rect.y1) / 2
        if y_mid < 70 or y_mid > ph - 18:   # skip header/footer area
            continue
        blanks.append({
            'left':  rect.x0 / pw,
            'top':   y_mid  / ph,
            'width': w      / pw,
        })
    return blanks


def render_page_to_jpeg(page, page_num: int, level: int,
                        scale: float = 2.0) -> str | None:
    """Render PDF page to JPEG at given scale; save to img/. Returns relative src."""
    img_dir = os.path.join(OUT, 'exercises', str(level), 'img')
    os.makedirs(img_dir, exist_ok=True)
    fname = f'p{page_num:03d}_render.jpg'
    fpath = os.path.join(img_dir, fname)
    if os.path.exists(fpath):
        return f'img/{fname}'
    try:
        mat = pymupdf.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(fpath)
        return f'img/{fname}'
    except Exception:
        return None


def overlay_page_to_html(page, pw: float, ph: float,
                          page_num: int, level: int,
                          doc=None) -> tuple[str, str | None]:
    """
    Render the PDF page as an image and overlay <input> elements on each blank
    underline detected from drawing strokes.
    Returns (html_string, unit_or_None).
    """
    blocks = page.get_text('blocks')
    meaningful = sum(
        1 for b in blocks
        if b[6] == 0
        and not should_skip(b[4], b[0], b[1], pw, ph)
        and len(b[4].strip()) > 10
    )
    if meaningful < 1:
        return '', None

    img_src = render_page_to_jpeg(page, page_num, level)
    if not img_src:
        return '', None

    blanks = get_blank_positions(page, pw, ph)
    unit   = detect_unit(page)

    inputs_html = ''
    for b in blanks:
        l = b['left']  * 100
        t = b['top']   * 100
        w = b['width'] * 100
        inputs_html += (
            f'<input type="text" class="overlay-input" '
            f'spellcheck="true" autocomplete="off" '
            f'style="left:{l:.2f}%;top:{t:.2f}%;width:{w:.2f}%">\n'
        )

    content_html = (
        f'<div class="page-overlay-wrap">\n'
        f'<img src="{img_src}" alt="Pagina {page_num}" loading="lazy">\n'
        f'{inputs_html}'
        f'</div>'
    )
    return content_html, unit


# ── Block classification ──────────────────────────────────────────────────────

SKIP_TEXTS = {
    'nuovissimo', 'progetto\n', 'italiano\n', 'italiano',
    'progetto italiano', 'quaderno degli esercizi',
}

def should_skip(text: str, x0: float, y0: float, pw: float, ph: float) -> bool:
    t = text.strip().lower()
    if not t:
        return True
    # Page number at bottom
    if y0 > ph * 0.88 and re.match(r'^\d{1,3}$', text.strip()):
        return True
    # Top-of-page header area
    if y0 < 72:
        for kw in SKIP_TEXTS:
            if kw in t:
                return True
        # "Unità" label top right
        if x0 > pw * 0.65 and 'unit' in t:
            return True
    return False


def is_exercise_header(text: str):
    """Return (num, instruction) if block is an exercise header like '9  Completa...'."""
    stripped = text.strip()
    m = re.match(r'^(\d+)\s{2,}(.+)', stripped, re.DOTALL)
    if m:
        return m.group(1), m.group(2).strip()
    return None, None


def detect_unit(page) -> str | None:
    """Try to find unit number from top-right area."""
    pw = page.rect.width
    for b in page.get_text('blocks'):
        x0, y0, x1, y1, text, *_ = b
        if y0 < 60 and x0 > pw * 0.6:
            m = re.search(r'\d+', text)
            if m:
                return m.group()
    return None


# ── HTML building ─────────────────────────────────────────────────────────────

def block_to_html(text: str) -> str:
    """Render one PDF text block as styled HTML."""
    from html import escape as esc
    stripped = text.strip()

    # Exercise header: "9  Completa con l'articolo..."
    ex_num, instruction = is_exercise_header(stripped)
    if ex_num and instruction:
        instr_html = text_to_html(instruction)
        return (
            f'<div class="ex-header">'
            f'<span class="ex-num">{esc(ex_num)}</span>'
            f'<span class="ex-instr">{instr_html}</span>'
            f'</div>'
        )

    # Standalone exercise instruction that starts with space (e.g. "\nCompleta...")
    if text.startswith('\n') or (text.startswith(' ') and not re.match(r'^\s+\d+\.', text)):
        first_line = stripped.split('\n')[0]
        # Looks like an instruction line
        if re.match(r'^[A-Z]', first_line) and len(first_line) > 15 and 'input' not in first_line.lower():
            return f'<p class="ex-instr standalone">{text_to_html(stripped)}</p>'

    body = text_to_html(stripped)
    return f'<div class="ex-block">{body}</div>'


# ── Page HTML template ────────────────────────────────────────────────────────

def page_html(level: int, page_num: int, content_html: str,
              unit: str | None, prev_p: int | None, next_p: int | None,
              pdf_pw: float = 0) -> str:
    meta = LEVEL_META[level]
    color = meta['color']
    cefr  = meta['cefr']

    prev_btn = (
        f'<a href="page_{prev_p:03d}.html" class="nav-btn">&#8592; {prev_p}</a>'
        if prev_p else '<span class="nav-btn disabled">&#8592;</span>'
    )
    next_btn = (
        f'<a href="page_{next_p:03d}.html" class="nav-btn">{next_p} &#8594;</a>'
        if next_p else '<span class="nav-btn disabled">&#8594;</span>'
    )

    unit_badge = (
        f'<span class="unit-badge bg-{color}-900 text-{color}-300 border-{color}-700">'
        f'Unità {unit}</span>'
    ) if unit else ''

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Livello {level} · p.{page_num}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="../../style.css">
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen flex flex-col">

  <!-- Top nav -->
  <nav class="sticky top-0 z-20 bg-slate-800 border-b border-slate-700 px-4 py-2.5
              flex items-center justify-between gap-4 text-sm">
    <div class="flex items-center gap-2 min-w-0">
      <a href="../../index.html" class="text-slate-400 hover:text-white shrink-0" title="Home">
        <svg viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
          <path d="M10.707 2.293a1 1 0 0 0-1.414 0l-7 7A1 1 0 0 0 3 11h1v6a1 1 0 0 0 1 1h4v-4h2v4h4a1 1 0 0 0 1-1v-6h1a1 1 0 0 0 .707-1.707l-7-7z"/>
        </svg>
      </a>
      <span class="text-slate-600">/</span>
      <a href="../level{level}.html" class="text-slate-400 hover:text-white truncate">
        Livello {level} <span class="text-slate-600">({cefr})</span>
      </a>
      <span class="text-slate-600">/</span>
      <span class="text-white font-medium">p.{page_num}</span>
      {unit_badge}
    </div>
    <div class="flex items-center gap-1 shrink-0">
      {prev_btn}
      {next_btn}
    </div>
  </nav>

  <!-- Exercise content -->
  <main class="flex-1 max-w-3xl w-full mx-auto px-5 py-7">
    <div class="exercise-page space-y-3">
      {content_html}
    </div>
  </main>

  <!-- Bottom toolbar -->
  <div class="sticky bottom-0 bg-slate-800/95 backdrop-blur border-t border-slate-700
              px-5 py-2.5 flex items-center justify-between gap-4 text-xs">
    <div class="flex items-center gap-3">
      <button onclick="checkProgress()"
              class="bg-{color}-700 hover:bg-{color}-600 text-white px-3 py-1.5 rounded-lg transition-colors">
        Controlla
      </button>
      <button onclick="clearPage()"
              class="bg-slate-700 hover:bg-slate-600 text-slate-300 px-3 py-1.5 rounded-lg transition-colors">
        Cancella
      </button>
    </div>
    <span id="progress" class="text-slate-400"></span>
    <div class="flex items-center gap-1">
      {prev_btn}
      {next_btn}
    </div>
  </div>

  <script>
    const KEY = 'npi_l{level}_p{page_num:03d}';
    const SEL = '.ex-input, .overlay-input';

    function saveProgress() {{
      const vals = [...document.querySelectorAll(SEL)].map(i => i.value);
      try {{ localStorage.setItem(KEY, JSON.stringify(vals)); }} catch(e) {{}}
    }}

    function loadProgress() {{
      try {{
        const saved = JSON.parse(localStorage.getItem(KEY) || '[]');
        document.querySelectorAll(SEL).forEach((inp, i) => {{
          if (saved[i]) inp.value = saved[i];
        }});
      }} catch(e) {{}}
    }}

    function checkProgress() {{
      const inputs = document.querySelectorAll(SEL);
      const filled = [...inputs].filter(i => i.value.trim()).length;
      const pct = inputs.length ? Math.round(filled / inputs.length * 100) : 0;
      document.getElementById('progress').textContent =
        `${{filled}}/${{inputs.length}} (${{pct}}%)`;
    }}

    function clearPage() {{
      document.querySelectorAll(SEL).forEach(i => {{ i.value = ''; }});
      try {{ localStorage.removeItem(KEY); }} catch(e) {{}}
      document.getElementById('progress').textContent = 'Cancellato';
    }}

    document.querySelectorAll(SEL).forEach(i => i.addEventListener('input', saveProgress));
    loadProgress();
    checkProgress();

    // Keyboard: Enter advances to next input
    document.querySelectorAll(SEL).forEach((inp, idx, all) => {{
      inp.addEventListener('keydown', e => {{
        if (e.key === 'Enter') {{ e.preventDefault(); all[idx + 1]?.focus(); }}
      }});
    }});

    // Overlay input font scaling (only active when page was rendered from PDF)
    (function() {{
      const PDF_PW = {pdf_pw};
      if (!PDF_PW) return;
      const BASE_FS = 11;
      function scaleOverlays() {{
        document.querySelectorAll('.page-overlay-wrap').forEach(wrap => {{
          const s = wrap.clientWidth / PDF_PW;
          wrap.querySelectorAll('.overlay-input').forEach(inp => {{
            inp.style.fontSize = (BASE_FS * s).toFixed(1) + 'px';
            inp.style.height   = (BASE_FS * s * 1.6).toFixed(1) + 'px';
          }});
        }});
      }}
      if (window.ResizeObserver) {{
        const ro = new ResizeObserver(scaleOverlays);
        document.querySelectorAll('.page-overlay-wrap').forEach(w => ro.observe(w));
      }}
      window.addEventListener('resize', scaleOverlays);
      scaleOverlays();
    }})();
  </script>
</body>
</html>
"""


# ── Level index HTML ──────────────────────────────────────────────────────────

def level_index_html(level: int, pages: list[dict]) -> str:
    meta  = LEVEL_META[level]
    color = meta['color']
    cefr  = meta['cefr']
    title = meta['title']
    total = len(pages)

    cards = []
    for p in pages:
        unit_txt = f"Unità {p['unit']}" if p.get('unit') else ''
        cards.append(
            f'<a href="{level}/page_{p["num"]:03d}.html" '
            f'   class="page-card block bg-slate-800 border border-slate-700 '
            f'          hover:border-{color}-500 rounded-xl p-4 transition-colors">'
            f'  <div class="flex justify-between items-start">'
            f'    <span class="text-{color}-400 font-bold text-lg">p.{p["num"]}</span>'
            f'    <span class="text-xs text-slate-500">{unit_txt}</span>'
            f'  </div>'
            f'  <div class="text-xs text-slate-500 mt-1">{p.get("inputs", 0)} campi</div>'
            f'</a>'
        )

    grid = '\n'.join(cards)

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Livello {level} Esercizi — {cefr}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="../style.css">
  <style>
    .flag-stripe {{ background: linear-gradient(to right, #009246 33.3%, #fff 33.3%, #fff 66.6%, #ce2b37 66.6%); }}
  </style>
</head>
<body class="bg-slate-900 text-white min-h-screen">
  <div class="h-1.5 flag-stripe"></div>
  <nav class="bg-slate-800 border-b border-slate-700 px-5 py-3 flex items-center gap-3 sticky top-0 z-20">
    <a href="../index.html" class="flex items-center gap-2 text-slate-400 hover:text-white text-sm">
      <svg viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
        <path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/>
      </svg>
      Home
    </a>
    <span class="text-slate-600">/</span>
    <span class="text-white font-semibold">Livello {level}</span>
    <span class="bg-{color}-900/60 text-{color}-300 text-xs font-bold px-2.5 py-0.5 rounded-full border border-{color}-700">{cefr}</span>
  </nav>

  <header class="max-w-4xl mx-auto px-6 py-8">
    <h1 class="text-3xl font-bold text-white">Quaderno degli Esercizi</h1>
    <p class="text-slate-400 mt-1">Livello {level} — {title} ({cefr}) · {total} pagine</p>
    <p class="text-slate-500 text-sm mt-2">
      Clicca una pagina per aprire gli esercizi interattivi. I tuoi progressi vengono salvati automaticamente.
    </p>
  </header>

  <main class="max-w-4xl mx-auto px-6 pb-12">
    <div class="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-7 gap-3">
      {grid}
    </div>
  </main>
  <div class="h-1.5 flag-stripe"></div>
</body>
</html>
"""


# ── Scanned page OCR → HTML (EasyOCR + gap detection) ────────────────────────

def save_scanned_page_img(page, doc, page_num: int, level: int) -> str | None:
    """
    For a scanned PDF page: extract the embedded full-page image and save it.
    Returns the relative HTML src path, or None on failure.
    """
    img_dir = os.path.join(OUT, 'exercises', str(level), 'img')
    os.makedirs(img_dir, exist_ok=True)

    for img_info in page.get_images(full=True):
        xref, _, w, h = img_info[0], img_info[1], img_info[2], img_info[3]
        if w < 400 or h < 400:   # skip small embedded icons
            continue
        try:
            base  = doc.extract_image(xref)
            ext   = base.get('ext', 'jpg')
            fname = f'p{page_num:03d}_scan.{ext}'
            fpath = os.path.join(img_dir, fname)
            with open(fpath, 'wb') as f:
                f.write(base['image'])
            return f'img/{fname}'
        except Exception:
            pass
    return None


def ocr_page_to_html(page, reader, doc, page_num: int, level: int,
                     scale: float = 1.5) -> str:
    """
    Render a scanned PDF page at `scale`, run EasyOCR to detect gaps (blanks),
    then return overlay HTML: scan image as background + positioned <input> elements.
    """
    mat     = pymupdf.Matrix(scale, scale)
    pix     = page.get_pixmap(matrix=mat)
    pw_px   = pix.width
    ph_px   = pix.height
    img_bytes = pix.tobytes('png')

    results = reader.readtext(img_bytes, paragraph=False)

    # Normalise to (y_center, y_bottom, x_start, x_end, text)
    items = []
    for bbox, text, conf in results:
        if conf < 0.3 or not text.strip():
            continue
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        xmin, xmax = min(xs), max(xs)
        yc     = sum(ys) / len(ys)
        ybot   = max(ys)
        items.append((yc, ybot, xmin, xmax, text.strip()))

    # Drop header (top 7%) and footer (bottom 5%)
    items = [it for it in items if ph_px * 0.07 < it[0] < ph_px * 0.95]

    # Group into rows: items within 15px y of each other
    items.sort(key=lambda it: it[0])
    rows: list[list] = []
    cur_row: list    = []
    prev_y = None
    for it in items:
        y = it[0]
        if prev_y is None or abs(y - prev_y) < 15 * scale:
            cur_row.append(it)
            prev_y = (prev_y + y) / 2 if prev_y is not None else y
        else:
            if cur_row:
                rows.append(sorted(cur_row, key=lambda i: i[2]))
            cur_row = [it]
            prev_y = y
    if cur_row:
        rows.append(sorted(cur_row, key=lambda i: i[2]))

    gap_thr = pw_px * 0.06

    inputs_html = ''
    for row in rows:
        if not row:
            continue
        # Use the maximum y_bottom of items in the row as the anchor (≈ baseline)
        row_ybot = max(it[1] for it in row)
        for j, (yc, ybot, x0, x1, text) in enumerate(row):
            if j > 0:
                prev_x1 = row[j - 1][3]
                gap = x0 - prev_x1
                if gap > gap_thr:
                    l = prev_x1 / pw_px * 100
                    t = row_ybot  / ph_px * 100
                    w = gap       / pw_px * 100
                    inputs_html += (
                        f'<input type="text" class="overlay-input" '
                        f'spellcheck="true" autocomplete="off" '
                        f'style="left:{l:.2f}%;top:{t:.2f}%;width:{w:.2f}%">\n'
                    )

    scan_src = save_scanned_page_img(page, doc, page_num, level)
    if not scan_src:
        return ''

    return (
        f'<div class="page-overlay-wrap">\n'
        f'<img src="{scan_src}" alt="Pagina {page_num}" loading="lazy">\n'
        f'{inputs_html}'
        f'</div>'
    )


# ── Text-layer page → HTML ────────────────────────────────────────────────────

def textpdf_page_to_html(page, pw: float, ph: float,
                         page_num: int = 0, level: int = 0,
                         doc=None) -> tuple[str, str | None]:
    """Extract text+image blocks from a text-layer PDF page and convert to HTML."""
    blocks = page.get_text('blocks')

    # ── Build combined item list: (y, x, kind, payload) ──
    combined = []

    for b in blocks:
        if b[6] == 0:   # text block
            combined.append((b[1], b[0], 'text', b))

    if doc is not None and page_num > 0:
        for y0, x0, html in extract_page_images(page, doc, page_num, level, pw, ph):
            combined.append((y0, x0, 'img', html))

    combined.sort(key=lambda c: (round(c[0] / 15) * 15, c[1]))

    block_htmls = []
    meaningful  = 0

    for y0, x0, kind, payload in combined:
        if kind == 'text':
            text = payload[4]
            if should_skip(text, x0, y0, pw, ph):
                continue
            if text.strip():
                if len(text.strip()) > 10:
                    meaningful += 1
                block_htmls.append(block_to_html(text))
        else:           # 'img'
            block_htmls.append(payload)

    if meaningful < 2:
        return '', None

    unit = detect_unit(page)
    return '\n'.join(block_htmls), unit


# ── Main conversion loop ──────────────────────────────────────────────────────

def _write_pages(level, page_metas, content_map):
    out_dir = os.path.join(OUT, 'exercises', str(level))
    for i, meta in enumerate(page_metas):
        prev_p = page_metas[i - 1]['num'] if i > 0 else None
        next_p = page_metas[i + 1]['num'] if i + 1 < len(page_metas) else None
        html = page_html(
            level, meta['num'], content_map[meta['num']],
            meta.get('unit'), prev_p, next_p,
            meta.get('pdf_pw', 0),
        )
        out_path = os.path.join(out_dir, f'page_{meta["num"]:03d}.html')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(html)


def convert_pdf(level: int):
    pdf_path = PDFS[level]
    out_dir  = os.path.join(OUT, 'exercises', str(level))
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n=== Level {level}: {os.path.basename(pdf_path)} ===")
    doc   = pymupdf.open(pdf_path)
    total = len(doc)

    # Detect if scanned by checking first few pages for text
    sample_text = ''.join(doc[min(i, total-1)].get_text() for i in range(3, 7))
    is_scanned  = len(sample_text.strip()) < 50

    reader = None
    if is_scanned:
        print("  Detected scanned PDF — loading EasyOCR (first time downloads models)...")
        import easyocr
        reader = easyocr.Reader(['it', 'en'], gpu=False, verbose=False)
        print("  EasyOCR ready.")

    page_metas: list[dict] = []
    content_map: dict[int, str] = {}

    for pn in range(total):
        page   = doc[pn]
        pw, ph = page.rect.width, page.rect.height

        if is_scanned:
            content_html = ocr_page_to_html(page, reader, doc, pn + 1, level, scale=1.5)
            if len(content_html.strip()) < 40:
                continue
            unit = None
        else:
            content_html, unit = overlay_page_to_html(page, pw, ph, pn + 1, level, doc)
            if not content_html.strip():
                continue

        input_count = content_html.count('<input ')
        pnum = pn + 1
        page_metas.append({
            'num': pnum, 'unit': unit, 'inputs': input_count,
            'pdf_pw': pw,
        })
        content_map[pnum] = content_html

        if pn % 10 == 0:
            print(f"  ...page {pn+1}/{total}")

    _write_pages(level, page_metas, content_map)

    # Write level index
    with open(os.path.join(OUT, 'exercises', f'level{level}.html'), 'w', encoding='utf-8') as f:
        f.write(level_index_html(level, page_metas))

    # Write manifest
    with open(os.path.join(out_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(page_metas, f, ensure_ascii=False, indent=2)

    print(f"  → {len(page_metas)} pages converted")
    doc.close()


if __name__ == '__main__':
    levels = [int(x) for x in sys.argv[1:]] if sys.argv[1:] else [1, 2, 3, 4]
    for lv in levels:
        convert_pdf(lv)
    print('\nDone. Open D:/Games/NPI-Exercises/index.html')
