import os
import bs4

files = {
    'gizlilik': '/Users/emrekoca/.gemini/antigravity-ide/brain/2b0b466f-c109-47c6-b1de-64f40a534e65/.system_generated/steps/783/content.md',
    'kullanim-kosullari': '/Users/emrekoca/.gemini/antigravity-ide/brain/2b0b466f-c109-47c6-b1de-64f40a534e65/.system_generated/steps/786/content.md',
    'destek': '/Users/emrekoca/.gemini/antigravity-ide/brain/2b0b466f-c109-47c6-b1de-64f40a534e65/.system_generated/steps/789/content.md',
    'yapay-zeka-bildirimi': '/Users/emrekoca/.gemini/antigravity-ide/brain/2b0b466f-c109-47c6-b1de-64f40a534e65/.system_generated/steps/790/content.md',
    'veri-silme': '/Users/emrekoca/.gemini/antigravity-ide/brain/2b0b466f-c109-47c6-b1de-64f40a534e65/.system_generated/steps/791/content.md'
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
    
    # HTML inside md starts after --- usually, but we can just parse the whole thing
    soup = bs4.BeautifulSoup(html, 'html.parser')
    
    hero = soup.find('section', class_='page-hero')
    if not hero:
        print(f"Skipping {slug}, no hero")
        continue
    
    eyebrow = hero.find('span', class_='eyebrow').text if hero.find('span', class_='eyebrow') else ''
    title = hero.find('h1').text if hero.find('h1') else ''
    lede = hero.find('p', class_='lede').text if hero.find('p', class_='lede') else ''
    
    content_html = ""
    content_section = soup.find('section', class_='content-section')
    if content_section:
        cards = content_section.find_all('div', class_='surface-card')
        for card in cards:
            h3 = card.find('h3')
            h3_text = h3.text if h3 else ''
            
            copy_div = card.find('div', class_='legal-copy')
            paragraphs = []
            if copy_div:
                for p in copy_div.find_all('p'):
                    paragraphs.append(p.text)
            
            if h3_text:
                content_html += f"        <section class=\"space-y-4\">\n"
                content_html += f"          <h3 class=\"text-xl font-semibold text-[var(--color-elyan-text)]\">{h3_text}</h3>\n"
                content_html += f"          <div class=\"space-y-4 text-[15px] text-[var(--color-elyan-text-muted)] leading-relaxed\">\n"
                for p in paragraphs:
                    content_html += f"            <p>{p}</p>\n"
                content_html += f"          </div>\n"
                content_html += f"        </section>\n\n"
    else:
        print(f"No content section for {slug}")

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

