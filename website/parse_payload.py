import re
import os

files = {
    'destek': '/tmp/destek.html',
    'yapay-zeka-bildirimi': '/tmp/ai.html',
    'veri-silme': '/tmp/veri-silme.html'
}

layout_template = """---
import AppLayout from '../layouts/AppLayout.astro';
---

<AppLayout title="{title} - Elyan">
  <main class="min-h-screen bg-[var(--color-elyan-bg)] py-20 px-6 md:px-12">
    <div class="max-w-3xl mx-auto space-y-12">
      
      <header class="space-y-4">
        <span class="text-[var(--color-elyan-primary)] font-semibold tracking-wider text-sm uppercase">{eyebrow}</span>
        <h1 class="text-4xl font-sans font-bold text-[var(--color-elyan-text)] tracking-tight">{title}</h1>
        <p class="text-[17px] text-[var(--color-elyan-text-muted)] leading-relaxed font-medium">
          {lede}
        </p>
      </header>

      <div class="space-y-10">
{content}
      </div>
      
    </div>
  </main>
</AppLayout>
"""

for slug, path in files.items():
    with open(path, 'r', encoding='utf-8') as f:
        html = f.read()

    # Extract eyebrow
    eyebrow_match = re.search(r'\\"eyebrow\\",\\"children\\":\\"(.*?)\\"', html) or re.search(r'"eyebrow","children":"(.*?)"', html)
    eyebrow = eyebrow_match.group(1) if eyebrow_match else ''

    # Extract h1
    h1_match = re.search(r'\\"h1\\",null,\{\\"children\\":\\"(.*?)\\"\}', html) or re.search(r'"h1",null,{"children":"(.*?)"}', html)
    title = h1_match.group(1) if h1_match else ''

    # Extract lede
    lede_match = re.search(r'\\"lede\\",\\"children\\":\\"(.*?)\\"\}', html) or re.search(r'"lede","children":"(.*?)"}', html)
    lede = lede_match.group(1) if lede_match else ''
    
    # Clean up escaped unicode like \u003C
    lede = lede.replace('\\u003C', '<').replace('\\u003E', '>')

    content_html = ""
    
    # We will find all blocks containing "surface-row"
    blocks = re.findall(r'\\"surface-row\\".*?(?=\\"surface-row\\"|\]\}\]\}\])', html)
    if not blocks:
        blocks = re.findall(r'"surface-row".*?(?="surface-row"|\]\}\]\}\])', html)
        
    for block in blocks:
        # Extract h3
        h3_match = re.search(r'\\"h3\\",null,\{\\"children\\":\\"(.*?)\\"\}', block) or re.search(r'"h3",null,{"children":"(.*?)"}', block)
        if not h3_match:
            continue
        h3_text = h3_match.group(1)
        
        # Extract all p
        p_matches = re.findall(r'\\"p\\",null,\{\\"children\\":\\"(.*?)\\"\}', block)
        if not p_matches:
            p_matches = re.findall(r'"p",null,{"children":"(.*?)"}', block)
            
        if p_matches:
            content_html += f"        <section class=\"space-y-4\">\n"
            content_html += f"          <h3 class=\"text-xl font-semibold text-[var(--color-elyan-text)]\">{h3_text}</h3>\n"
            content_html += f"          <div class=\"space-y-4 text-[15px] text-[var(--color-elyan-text-muted)] leading-relaxed\">\n"
            for p in p_matches:
                p_text = p.replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')
                content_html += f"            <p>{p_text}</p>\n"
            content_html += f"          </div>\n"
            content_html += f"        </section>\n\n"

    astro_content = layout_template.format(
        title=title,
        eyebrow=eyebrow,
        lede=lede,
        content=content_html.rstrip()
    )
    
    out_path = f"src/pages/{slug}.astro"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(astro_content)
    print(f"Generated {out_path}")

