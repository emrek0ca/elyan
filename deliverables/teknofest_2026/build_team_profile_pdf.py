from __future__ import annotations

from pathlib import Path
from typing import Iterable

import fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
OUT_PDF = BASE_DIR / "Elyan_Takim_Tanitim_Dosyasi_TEKNOFEST_2026.pdf"
OUT_PREVIEW_1 = BASE_DIR / "preview_page_1.png"
OUT_PREVIEW_2 = BASE_DIR / "preview_page_2.png"
LOGO_PATH = ROOT_DIR / "logo.png"

FONT_REGULAR = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
FONT_BOLD = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")

PAGE_W, PAGE_H = A4
M = 42

INK = colors.HexColor("#1F272B")
MUTED = colors.HexColor("#64716C")
HAIRLINE = colors.HexColor("#E5EAE7")
PAPER = colors.HexColor("#FBFCFB")
CARD = colors.HexColor("#FFFFFF")
SOFT = colors.HexColor("#F4F7F5")
SAGE = colors.HexColor("#6F8378")
BLUE = colors.HexColor("#145CFF")
BLUE_SOFT = colors.HexColor("#EAF0FF")
GREEN_SOFT = colors.HexColor("#EDF4EF")


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("ElyanSans", str(FONT_REGULAR)))
    pdfmetrics.registerFont(TTFont("ElyanSans-Bold", str(FONT_BOLD)))


def wrap_text(text: str, font: str, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if pdfmetrics.stringWidth(candidate, font, size) <= max_width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def draw_wrapped(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "ElyanSans",
    size: float = 9.0,
    leading: float = 12.5,
    color=INK,
    max_lines: int | None = None,
) -> float:
    c.setFillColor(color)
    c.setFont(font, size)
    lines = wrap_text(text, font, size, width)
    if max_lines is not None:
        lines = lines[:max_lines]
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_label(c: canvas.Canvas, text: str, x: float, y: float, color=SAGE) -> None:
    c.setFont("ElyanSans-Bold", 7.2)
    c.setFillColor(color)
    c.drawString(x, y, text.upper())


def draw_card(c: canvas.Canvas, x: float, y: float, w: float, h: float, *, fill=CARD, stroke=HAIRLINE) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(0.8)
    c.roundRect(x, y, w, h, 16, stroke=1, fill=1)


def draw_pill(c: canvas.Canvas, text: str, x: float, y: float, w: float, *, fill=SOFT, color=SAGE) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(fill)
    c.roundRect(x, y, w, 22, 11, stroke=0, fill=1)
    c.setFont("ElyanSans-Bold", 7.4)
    c.setFillColor(color)
    c.drawCentredString(x + w / 2, y + 7, text)


def draw_bullets(c: canvas.Canvas, items: Iterable[str], x: float, y: float, width: float, *, size=8.6) -> float:
    for item in items:
        c.setFillColor(SAGE)
        c.circle(x + 2.2, y + 3.2, 2.1, stroke=0, fill=1)
        y = draw_wrapped(
            c,
            item,
            x + 11,
            y,
            width - 11,
            font="ElyanSans",
            size=size,
            leading=size + 3.2,
            color=INK,
        )
        y -= 3
    return y


def draw_background(c: canvas.Canvas) -> None:
    c.setFillColor(PAPER)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    c.setStrokeColor(colors.HexColor("#EEF3F0"))
    c.setLineWidth(0.35)
    for i in range(11):
        y = 120 + i * 55
        c.line(M, y, PAGE_W - M, y)

    c.setStrokeColor(colors.HexColor("#DCE7E2"))
    c.setLineWidth(0.55)
    cx, cy = PAGE_W - 104, PAGE_H - 132
    for r in (28, 48, 70):
        c.ellipse(cx - r, cy - r * 0.62, cx + r, cy + r * 0.62, stroke=1, fill=0)
    c.setFillColor(SAGE)
    c.circle(cx, cy, 4.2, stroke=0, fill=1)
    c.setFillColor(BLUE)
    c.circle(cx + 56, cy + 17, 2.8, stroke=0, fill=1)


def draw_header(c: canvas.Canvas, page_label: str) -> None:
    c.setFont("ElyanSans-Bold", 7.5)
    c.setFillColor(MUTED)
    c.drawString(M, PAGE_H - 30, "TEKNOFEST 2026  /  KUANTUM TEKNOLOJİLERİ  /  YAZILIM KATEGORİSİ")
    c.drawRightString(PAGE_W - M, PAGE_H - 30, page_label)


def draw_logo_lockup(c: canvas.Canvas, x: float, y: float, size: float) -> None:
    c.drawImage(ImageReader(str(LOGO_PATH)), x, y, width=size, height=size, mask="auto")


def page_one(c: canvas.Canvas) -> None:
    draw_background(c)
    draw_header(c, "TAKIM TANITIM DOSYASI")

    draw_logo_lockup(c, M, PAGE_H - 126, 66)
    c.setFont("ElyanSans-Bold", 52)
    c.setFillColor(INK)
    c.drawString(M + 84, PAGE_H - 92, "ELYAN")
    c.setFont("ElyanSans", 12.2)
    c.setFillColor(MUTED)
    c.drawString(M + 88, PAGE_H - 114, "Yerel-öncelikli yapay zekâ ajanı ve kuantum optimizasyon ekibi")

    draw_pill(c, "Kuantum + Yapay Zekâ", M, PAGE_H - 161, 128, fill=BLUE_SOFT, color=BLUE)
    draw_pill(c, "Local-first mimari", M + 138, PAGE_H - 161, 114, fill=GREEN_SOFT, color=SAGE)
    draw_pill(c, "Güvenli görev yürütme", M + 262, PAGE_H - 161, 142, fill=SOFT, color=MUTED)

    y = PAGE_H - 205
    draw_label(c, "Takım Özeti", M, y)
    y -= 20
    draw_wrapped(
        c,
        "Elyan; matematiksel modelleme, yazılım mühendisliği ve mobil/masaüstü ürün geliştirme disiplinlerini aynı hedefte birleştiren üç kişilik bir teknoloji takımıdır. Odağımız, kuantum optimizasyon problemlerini anlaşılır, ölçülebilir ve uygulanabilir yazılım çözümlerine dönüştürmektir.",
        M,
        y,
        500,
        size=10.2,
        leading=15.0,
        color=INK,
    )

    metric_y = PAGE_H - 386
    metric_w = 158
    metrics = [
        ("3", "disiplin", "Matematik, mühendislik ve uygulamalı yazılım"),
        ("1", "yerel güvenlik ilkesi", "Özel veri ve görev yürütme kullanıcı cihazında"),
        ("2026", "yarışma hedefi", "Kuantum yazılım kategorisinde güçlü final dosyası"),
    ]
    for i, (big, label, desc) in enumerate(metrics):
        x = M + i * (metric_w + 16)
        draw_card(c, x, metric_y, metric_w, 82, fill=CARD)
        c.setFont("ElyanSans-Bold", 26)
        c.setFillColor(INK)
        c.drawString(x + 16, metric_y + 45, big)
        draw_label(c, label, x + 16, metric_y + 34)
        draw_wrapped(c, desc, x + 16, metric_y + 20, metric_w - 32, size=7.6, leading=9.5, color=MUTED)

    left_x, right_x = M, M + 276
    top_y = PAGE_H - 448
    draw_card(c, left_x, top_y - 122, 250, 122, fill=CARD)
    draw_label(c, "Takım Hikayesi", left_x + 18, top_y - 25)
    draw_wrapped(
        c,
        "Ekip, sohbet eden yazılımların ötesine geçip düşünen, planlayan, yürüten ve sonucu doğrulayan sistemler üretme fikriyle bir araya geldi. Matematiksel kesinliği ürün mühendisliğiyle buluşturuyor; karmaşık problemleri sade arayüzlerle erişilebilir kılmayı hedefliyoruz.",
        left_x + 18,
        top_y - 46,
        214,
        size=8.8,
        leading=12.3,
        color=INK,
    )

    draw_card(c, right_x, top_y - 122, 237, 122, fill=CARD)
    draw_label(c, "Neden Geliştiriyoruz?", right_x + 18, top_y - 25)
    draw_wrapped(
        c,
        "Gerçek dünya karar problemleri; çizelgeleme, yönlendirme, atama ve kaynak planlama gibi alanlarda hızla büyüyor. Elyan, bu problemler için hibrit kuantum-klasik yaklaşımı kullanıcıya güven veren bir karar destek akışına taşımayı amaçlıyor.",
        right_x + 18,
        top_y - 46,
        201,
        size=8.8,
        leading=12.3,
        color=INK,
    )

    vision_y = 124
    draw_card(c, M, vision_y, PAGE_W - 2 * M, 128, fill=SOFT, stroke=colors.HexColor("#DAE4DF"))
    draw_label(c, "Elyan Vizyonu", M + 20, vision_y + 94, color=BLUE)
    c.setFont("ElyanSans-Bold", 18)
    c.setFillColor(INK)
    c.drawString(M + 20, vision_y + 68, "Kuantum farkındalıklı, güvenli ve yerel-öncelikli ajan sistemi")
    draw_wrapped(
        c,
        "Elyan'ın uzun vadeli vizyonu; mobil komut, backend koordinasyon ve masaüstü yerel runtime üçlüsünü tek bir güvenilir karar altyapısına dönüştürmektir. Sistem, kuantum çözücüleri ve yapay zekâ planlamasını aynı mimaride buluşturur: görevleri sınıflandırır, doğru yürütme ortamına aktarır, onay gerektiren adımları durdurur ve sonucu açıklanabilir şekilde sunar.",
        M + 20,
        vision_y + 44,
        PAGE_W - 2 * M - 40,
        size=8.8,
        leading=12.2,
        color=INK,
    )

    c.setStrokeColor(HAIRLINE)
    c.line(M, 72, PAGE_W - M, 72)
    c.setFont("ElyanSans", 7.2)
    c.setFillColor(MUTED)
    c.drawString(M, 55, "Resmi kapsam referansı: TEKNOFEST Kuantum Teknolojileri Yarışması 2026, Yazılım Kategorisi.")


def draw_member_card(c: canvas.Canvas, x: float, y: float, w: float, h: float, name: str, role: str, dept: str, focus: str) -> None:
    draw_card(c, x, y, w, h, fill=CARD)
    c.setFillColor(GREEN_SOFT)
    c.circle(x + 24, y + h - 26, 13, stroke=0, fill=1)
    c.setFont("ElyanSans-Bold", 10.5)
    c.setFillColor(INK)
    c.drawString(x + 45, y + h - 24, name)
    c.setFont("ElyanSans-Bold", 7.2)
    c.setFillColor(SAGE)
    c.drawString(x + 45, y + h - 39, role.upper())
    draw_wrapped(c, dept, x + 18, y + h - 60, w - 36, size=8.0, leading=10.0, color=MUTED)
    c.setStrokeColor(HAIRLINE)
    c.line(x + 18, y + 38, x + w - 18, y + 38)
    draw_wrapped(c, focus, x + 18, y + 24, w - 36, size=7.4, leading=9.4, color=INK)


def draw_architecture(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    draw_card(c, x, y, w, h, fill=CARD)
    draw_label(c, "Elyan Sistem Mimarisi", x + 18, y + h - 28, color=BLUE)

    node_w = w - 36
    node_h = 28
    nodes = [
        ("Mobile", "Tek chat yüzeyi"),
        ("Backend", "Route + lifecycle truth"),
        ("Desktop", "Local runtime + tools"),
    ]
    start_x = x + 18
    top_node_y = y + h - 72
    for i, (title, subtitle) in enumerate(nodes):
        nx = start_x
        node_y = top_node_y - i * 38
        c.setFillColor(BLUE_SOFT if i == 1 else SOFT)
        c.setStrokeColor(colors.HexColor("#DCE4E0"))
        c.roundRect(nx, node_y, node_w, node_h, 10, stroke=1, fill=1)
        c.setFont("ElyanSans-Bold", 8.4)
        c.setFillColor(INK)
        c.drawString(nx + 14, node_y + 16, title)
        c.setFont("ElyanSans", 6.6)
        c.setFillColor(MUTED)
        c.drawRightString(nx + node_w - 14, node_y + 16, subtitle)
        if i < 2:
            ax = nx + node_w / 2
            c.setStrokeColor(SAGE)
            c.line(ax, node_y - 2, ax, node_y - 9)
            c.setFillColor(SAGE)
            c.circle(ax, node_y - 9, 2.0, stroke=0, fill=1)

    draw_wrapped(
        c,
        "Mobile karar üretmez. Backend sınıflandırır ve koordine eder. Private veri, araç çalıştırma ve yan etkili işlemler masaüstü runtime sınırında kalır.",
        x + 18,
        y + 34,
        w - 36,
        size=7.3,
        leading=9.5,
        color=MUTED,
    )


def draw_quantum_flow(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    draw_card(c, x, y, w, h, fill=SOFT, stroke=colors.HexColor("#DAE4DF"))
    draw_label(c, "Kuantum Teknolojileri ile İlişki", x + 18, y + h - 28, color=BLUE)
    steps = ["Problem", "QUBO / Ising", "Hibrit Çözücü", "Karar Desteği"]
    step_w = (w - 54) / 4
    step_y = y + 44
    for i, step in enumerate(steps):
        sx = x + 18 + i * (step_w + 6)
        c.setFillColor(CARD)
        c.setStrokeColor(HAIRLINE)
        c.roundRect(sx, step_y, step_w, 31, 10, stroke=1, fill=1)
        c.setFont("ElyanSans-Bold", 7.2)
        c.setFillColor(INK)
        c.drawCentredString(sx + step_w / 2, step_y + 12.5, step)
        if i < 3:
            c.setStrokeColor(SAGE)
            c.line(sx + step_w + 2, step_y + 15.5, sx + step_w + 6, step_y + 15.5)
    draw_wrapped(
        c,
        "Elyan, kuantum optimizasyonu soyut bir araştırma başlığı olarak değil; çizelgeleme, yönlendirme, atama ve kaynak planlama problemleri için ölçülebilir bir yazılım kabiliyeti olarak ele alır.",
        x + 18,
        y + 26,
        w - 36,
        size=7.6,
        leading=10.0,
        color=INK,
    )


def page_two(c: canvas.Canvas) -> None:
    draw_background(c)
    draw_header(c, "EKİP, YETKİNLİK VE MİMARİ")

    c.setFont("ElyanSans-Bold", 28)
    c.setFillColor(INK)
    c.drawString(M, PAGE_H - 82, "Takım Kadrosu")
    c.setFont("ElyanSans", 10.0)
    c.setFillColor(MUTED)
    c.drawString(M, PAGE_H - 103, "Disiplinlerarası yapı: matematiksel doğruluk, ürün mühendisliği ve güvenli yürütme.")

    card_y = PAGE_H - 244
    card_w = 162
    draw_member_card(
        c,
        M,
        card_y,
        card_w,
        112,
        "Osman Emre KOCA",
        "Takım Kaptanı",
        "Matematik Bölümü, 4. Sınıf",
        "Optimizasyon modelleme, problem formülasyonu, yarışma stratejisi.",
    )
    draw_member_card(
        c,
        M + card_w + 13,
        card_y,
        card_w,
        112,
        "Abdullah Yahyaoğlu",
        "Takım Üyesi",
        "Bilgisayar Mühendisliği, 4. Sınıf",
        "Backend, ajan akışı, veri yapıları ve sistem entegrasyonu.",
    )
    draw_member_card(
        c,
        M + 2 * (card_w + 13),
        card_y,
        card_w,
        112,
        "Eren KOCA",
        "Takım Üyesi",
        "Bilgisayar Programcılığı, 2. Sınıf",
        "Mobil/masaüstü arayüz, runtime bağlantısı ve uygulama testleri.",
    )

    advisor_y = card_y - 58
    draw_card(c, M, advisor_y, PAGE_W - 2 * M, 42, fill=GREEN_SOFT, stroke=colors.HexColor("#D6E1DB"))
    draw_label(c, "Danışman / Mentör", M + 18, advisor_y + 24)
    c.setFont("ElyanSans-Bold", 12.0)
    c.setFillColor(INK)
    c.drawString(M + 18, advisor_y + 10, "Enis Sert")
    c.setFont("ElyanSans", 8.2)
    c.setFillColor(MUTED)
    c.drawRightString(PAGE_W - M - 18, advisor_y + 13, "Akademik ve teknik yönlendirme")

    left_x = M
    right_x = M + 246
    mid_y = 314
    draw_card(c, left_x, mid_y, 222, 178, fill=CARD)
    draw_label(c, "Teknik Yetkinlikler", left_x + 18, mid_y + 150, color=BLUE)
    draw_bullets(
        c,
        [
            "Python tabanlı optimizasyon ve prototipleme",
            "QUBO / Ising modelleme, çizelgeleme ve atama problemleri",
            "Flutter mobil istemci, backend control-plane ve desktop runtime",
            "Local LLM, güvenli approval akışı ve görev orkestrasyonu",
            "Test, doğrulama, sürümleme ve teknik dokümantasyon disiplini",
        ],
        left_x + 18,
        mid_y + 126,
        186,
        size=7.7,
    )

    draw_architecture(c, right_x, mid_y, PAGE_W - M - right_x, 178)

    draw_quantum_flow(c, M, 184, PAGE_W - 2 * M, 104)

    goals_x = M
    goals_y = 72
    draw_card(c, goals_x, goals_y, PAGE_W - 2 * M, 86, fill=CARD)
    draw_label(c, "Gelecek Hedefleri", goals_x + 18, goals_y + 58, color=BLUE)
    goal_text = (
        "Kısa vadede yarışma problem setlerine uyumlu bir benchmark paketi ve hibrit çözücü prototipi; "
        "orta vadede açıklanabilir karar raporları; uzun vadede ise kuantum optimizasyon kabiliyetlerini "
        "yerel-öncelikli ajan mimarisi içinde ürünleşebilir bir teknolojiye dönüştürmek."
    )
    draw_wrapped(c, goal_text, goals_x + 18, goals_y + 36, PAGE_W - 2 * M - 36, size=8.2, leading=11.2, color=INK)


def build_pdf() -> None:
    register_fonts()
    c = canvas.Canvas(str(OUT_PDF), pagesize=A4, pageCompression=1)
    c.setTitle("Elyan Takım Tanıtım Dosyası - TEKNOFEST 2026")
    c.setAuthor("Elyan")
    c.setSubject("TEKNOFEST 2026 Kuantum Teknolojileri Yarışması Yazılım Kategorisi takım tanıtım dosyası")
    c.setKeywords("Elyan, TEKNOFEST, Kuantum Teknolojileri, Yazılım Kategorisi, Takım Tanıtım")
    page_one(c)
    c.showPage()
    page_two(c)
    c.showPage()
    c.save()


def verify_pdf() -> None:
    doc = fitz.open(OUT_PDF)
    if doc.page_count != 2:
        raise RuntimeError(f"Expected 2 pages, got {doc.page_count}")
    text = "\n".join(page.get_text() for page in doc)
    required = [
        "Elyan",
        "Osman Emre KOCA",
        "Abdullah Yahyaoğlu",
        "Kuantum Teknolojileri",
        "Yazılım Kategorisi",
        "Görev",
        "çizelgeleme",
    ]
    lowered_text = text.lower()
    missing = [item for item in required if item.lower() not in lowered_text]
    if missing:
        raise RuntimeError(f"PDF text extraction missing: {missing}")

    for idx, out_path in enumerate([OUT_PREVIEW_1, OUT_PREVIEW_2]):
        page = doc[idx]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7), alpha=False)
        pix.save(out_path)
    doc.close()


if __name__ == "__main__":
    build_pdf()
    verify_pdf()
    print(OUT_PDF)
    print(OUT_PREVIEW_1)
    print(OUT_PREVIEW_2)
