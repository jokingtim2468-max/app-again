"""Turn dist-demo/ into one self-contained HTML page (all JS + CSS inlined) for sharing as a single file."""
import re
import sys
from pathlib import Path

dist = Path(sys.argv[1] if len(sys.argv) > 1 else "dist-demo")
out = Path(sys.argv[2] if len(sys.argv) > 2 else dist / "apollo-demo.html")
html = (dist / "index.html").read_text()
css = "".join((dist / p).read_text() for p in re.findall(r'href="\./(assets/[^"]+\.css)"', html))
js_files = re.findall(r'src="\./(assets/[^"]+\.js)"', html)
assert len(js_files) == 1, f"expected one bundle, got {js_files}"
js = (dist / js_files[0]).read_text().replace("</script", "<\\/script")
page = f"""<title>Apollo Trading</title>
<style>
:root {{ color-scheme: dark; --bg: #090A0F; }}
html, body {{ background: var(--bg); height: 100%; }}
#root {{ height: 100%; }}
{css}
</style>
<div id="root"></div>
<script type="module">
{js}
</script>
"""
out.write_text(page)
print(out, f"{len(page) / 1e6:.2f} MB")
