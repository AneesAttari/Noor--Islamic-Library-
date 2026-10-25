"""Generate real sample PDF booklets and one cover image for the library.

These are genuine, self-contained PDF documents written for this library
(sample editions). They exist so the catalogue can be exercised end to end;
nothing here mocks the upload pipeline — scripts/seed.py pushes these files
through the same validation and storage code the admin form uses.

Usage: python scripts/make_samples.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

OUT_DIR = Path(__file__).resolve().parent / "sample_pdfs"


def build_pdf(filename: str, title: str, subtitle: str, sections: list[tuple[str, list[str]]]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / filename

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "BookTitle", parent=styles["Title"], fontName="Times-Bold", fontSize=26, leading=32, spaceAfter=8
    )
    subtitle_style = ParagraphStyle(
        "BookSubtitle", parent=styles["Normal"], fontName="Times-Italic", fontSize=14, leading=18, spaceAfter=24
    )
    h_style = ParagraphStyle(
        "SectionHead", parent=styles["Heading1"], fontName="Times-Bold", fontSize=15, leading=19,
        spaceBefore=16, spaceAfter=6,
    )
    p_style = ParagraphStyle(
        "Body", parent=styles["Normal"], fontName="Times-Roman", fontSize=11.5, leading=16.5, spaceAfter=8,
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontName="Times-Italic", fontSize=9, textColor="#666666", spaceBefore=20
    )

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=2.4 * cm, rightMargin=2.4 * cm, topMargin=2.4 * cm, bottomMargin=2.4 * cm,
        title=title, author="Maktaba Sample Editions",
    )

    story = [
        Spacer(1, 2.2 * cm),
        Paragraph(title, title_style),
        Paragraph(subtitle, subtitle_style),
        Paragraph(
            "Maktaba — Islamic Digital Library · Sample Edition.<br/>"
            "This booklet is an original short text produced as sample content for the library.",
            footer_style,
        ),
        PageBreak(),
    ]

    for heading, paragraphs in sections:
        story.append(Paragraph(heading, h_style))
        for text in paragraphs:
            story.append(Paragraph(text, p_style))

    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph("— End of the booklet —", footer_style))

    doc.build(story)
    return path


BOOKLETS = [
    dict(
        filename="etiquette-seeking-knowledge.pdf",
        title="The Etiquette of Seeking Knowledge",
        subtitle="A short booklet on the manners of students of learning",
        sections=[
            ("Why etiquette matters", [
                "In the Islamic tradition, learning has never been only about information. "
                "Scholars of the early generations emphasised that knowledge is a trust, and "
                "that the student who carries it is expected to carry it with humility, "
                "patience, and good character.",
                "This booklet summarises widely recognised points of etiquette that teachers "
                "throughout Islamic history have passed on to their students. It is written "
                "as a plain introduction, not as a legal manual.",
            ]),
            ("Sincerity of intention", [
                "Students are reminded to begin with a sound intention: learning in order to "
                "understand and to act, rather than for status or argument. Classical manuals "
                "on the etiquette of learning open with the purification of intention, because "
                "the value of an action is measured by its purpose.",
                "A practical habit is to renew the intention regularly — before a class, before "
                "reading, before revising — so that study remains worship rather than routine.",
            ]),
            ("Respect for teachers and for other students", [
                "Respecting a teacher does not mean abandoning critical thought. It means "
                "listening carefully, asking honest questions, not humiliating others, and "
                "accepting correction with grace. The same courtesy is due to fellow students: "
                "knowledge is not a competition in which one person's gain is another's loss.",
                "Traditional study circles prized measured speech. One of the sayings commonly "
                "recalled by students of the early generations is that whoever speaks less, "
                "errs less, and whoever errs less, protects what they have been given.",
            ]),
            ("Consistency over intensity", [
                "Small, regular study outlasts occasional bursts of enthusiasm. Teachers "
                "often advise setting a modest daily portion of reading or revision and "
                "protecting that time, even when other things compete.",
                "Keeping organised notes, revisiting difficult passages, and writing questions "
                "down to ask later are simple habits that distinguish serious students.",
            ]),
            ("Sharing what one learns", [
                "Knowledge in this tradition is meant to benefit people. A student who learns "
                "something useful is encouraged to pass it on gently, without exaggeration, "
                "and without speaking confidently about matters beyond their learning. Saying "
                "'I do not know' has always been counted among the marks of honest scholarship.",
                "This booklet ends where it began: with the reminder that learning is a trust. "
                "May it be carried well.",
            ]),
        ],
    ),
    dict(
        filename="glossary-islamic-terms.pdf",
        title="A Glossary of Islamic Terms",
        subtitle="Plain-language definitions for new readers",
        sections=[
            ("How to use this glossary", [
                "This booklet defines common terms that appear throughout Islamic books. The "
                "definitions are brief and descriptive, written for readers encountering them "
                "for the first time.",
            ]),
            ("Acts of worship", [
                "<b>Salah</b> — the ritual prayer performed five times daily. "
                "<b>Sawm</b> — fasting, especially during the month of Ramadan. "
                "<b>Zakat</b> — obligatory charity calculated on qualifying wealth. "
                "<b>Hajj</b> — the pilgrimage to Mecca, obligatory once in a lifetime for "
                "those who are able. "
                "<b>Dhikr</b> — remembrance of God, often through short phrases of praise. "
                "<b>Du'a</b> — personal supplication or prayer.",
            ]),
            ("Qur'an and its sciences", [
                "<b>Qur'an</b> — the holy book of Islam, regarded by Muslims as the word of "
                "God revealed to the Prophet Muhammad. "
                "<b>Surah</b> — a chapter of the Qur'an; there are 114. "
                "<b>Ayah</b> — a verse of the Qur'an. "
                "<b>Tafsir</b> — scholarly commentary explaining the Qur'an. "
                "<b>Tajwid</b> — the rules governing the correct recitation of the Qur'an. "
                "<b>Juz'</b> — one of thirty roughly equal parts into which the Qur'an is "
                "divided for recitation over a month.",
            ]),
            ("Hadith and law", [
                "<b>Hadith</b> — a report of the Prophet's sayings, actions, or approvals. "
                "<b>Sunnah</b> — the Prophet's established practice and way of life. "
                "<b>Isnad</b> — the chain of transmitters of a hadith. "
                "<b>Sahih</b> — 'sound'; a classification for rigorously authenticated "
                "reports. <b>Hasan</b> — 'good'; a sound classification slightly below sahih. "
                "<b>Da'if</b> — 'weak'; a report whose chain does not meet the strongest "
                "standards. <b>Fiqh</b> — Islamic jurisprudence, the understanding of "
                "practical law. <b>Ijma'</b> — scholarly consensus. "
                "<b>Qiyas</b> — analogical reasoning in law.",
            ]),
            ("Community and culture", [
                "<b>Ummah</b> — the global Muslim community. "
                "<b>Masjid</b> — a mosque, a place of prostration and prayer. "
                "<b>Imam</b> — a prayer leader, or a leading scholar. "
                "<b>Mu'adhdhin</b> — the person who calls the adhan, the call to prayer. "
                "<b>Madrassa</b> — a school, traditionally one teaching religious and "
                "sometimes general sciences. "
                "<b>Ulama</b> — the collective body of Islamic scholars.",
            ]),
        ],
    ),
    dict(
        filename="sciences-of-hadith.pdf",
        title="Introduction to the Sciences of Hadith",
        subtitle="How reports about the Prophet were collected and verified",
        sections=[
            ("What a hadith is", [
                "A hadith is a report of something the Prophet Muhammad said, did, or "
                "approved. Because these reports shape Muslim practice and belief, early "
                "scholars developed an elaborate discipline for collecting, testing, and "
                "classifying them — known as the sciences of hadith (ulum al-hadith).",
            ]),
            ("Isnad and matn", [
                "Every hadith has two parts. The <b>matn</b> is the content — the actual "
                "statement or event. The <b>isnad</b> is the chain of people who transmitted "
                "the report, one from another, back to a companion of the Prophet.",
                "The isnad made transmission accountable. Critics examined each person in the "
                "chain: their integrity, their reliability as narrators, whether they could "
                "have met the person they narrate from, and whether their reports were "
                "consistent. This method, formalised within the first Islamic centuries, is "
                "among the earliest systematic source-criticism traditions in world literature.",
            ]),
            ("Classifications of strength", [
                "<b>Sahih</b> (sound): a continuous chain of upright, precise narrators, "
                "free of irregularity and hidden defect. "
                "<b>Hasan</b> (good): meeting similar conditions, with slightly less precision "
                "in the narrators' retentiveness. "
                "<b>Da'if</b> (weak): failing one or more conditions — a broken chain, a "
                "narrator of questioned reliability, a contradiction of stronger reports, or "
                "a hidden defect discovered by specialists.",
                "Weak reports are not all the same; specialists describe dozens of specific "
                "defects. Collections devoted to identifying them — such as those of al-Daraqutni "
                "and later Ibn al-Jawzi — show how seriously scholars treated the boundary "
                "between reliable and unreliable material.",
            ]),
            ("The great collections", [
                "The six collections often called the Kutub al-Sittah — of al-Bukhari, Muslim, "
                "Abu Dawud, al-Tirmidhi, al-Nasa'i, and Ibn Majah — became the most widely "
                "studied hadith books in the Sunni world. Al-Bukhari's and Muslim's collections "
                "(the two Sahihs) are treated with particular care for their authors' strict "
                "selection criteria.",
                "Hadith scholarship never stopped at compilation. Commentaries, biographical "
                "dictionaries of narrators (rijal), and abridgements continued to be written "
                "for over a thousand years, and continue today.",
            ]),
            ("A note for readers", [
                "Popular books sometimes quote reports without their classifications. Readers "
                "who want to rely on a hadith for practice are usually best served by checking "
                "how specialist works classified it, or by asking a qualified teacher.",
            ]),
        ],
    ),
    dict(
        filename="quran-short-introduction.pdf",
        title="The Qur'an: A Short Introduction",
        subtitle="Orientation for first-time readers",
        sections=[
            ("What the Qur'an is", [
                "The Qur'an is the central religious text of Islam, regarded by Muslims as "
                "the word of God revealed to the Prophet Muhammad over a period of about "
                "twenty-three years, beginning in the early seventh century.",
            ]),
            ("How the text is arranged", [
                "The Qur'an contains 114 chapters, called surahs, which vary greatly in "
                "length. Surahs are composed of verses (ayat). For reading over a month, the "
                "text is also divided into thirty parts of roughly equal length (ajza', "
                "singular juz').",
                "Surahs are traditionally described as Makki (revealed in Mecca) or Madani "
                "(revealed in Medina). Makki surahs tend to focus on faith, the afterlife, "
                "and the stories of earlier prophets; Madani surahs address communal life, "
                "law, and the growing Muslim community — though both themes appear in both "
                "periods.",
                "Surahs are arranged roughly by length rather than chronology: the longest "
                "generally stand near the beginning of the book, the shortest near its end. "
                "The opening surah, al-Fatihah, is recited in every unit of Muslim prayer.",
            ]),
            ("Language and recitation", [
                "The Qur'an is in Arabic, and Muslims regard the Arabic wording itself as "
                "revelation — translations are treated as meanings of the text rather than "
                "as the text itself. A discipline called tajwid governs correct pronunciation "
                "and melody in recitation, and memorisation of the entire text remains common "
                "throughout the Muslim world.",
            ]),
            ("Reading recommendations", [
                "New readers often start with a reliable translation alongside the opening "
                "surah and the shorter surahs at the end of the book. A good commentary "
                "(tafsir) helps with context, and knowledgeable readers in one's community "
                "can help with questions.",
            ]),
        ],
    ),
    dict(
        filename="five-daily-prayers.pdf",
        title="Understanding the Five Daily Prayers",
        subtitle="Names, times, and structure — a plain overview",
        sections=[
            ("The five prayers", [
                "Muslims pray five obligatory prayers each day: "
                "<b>Fajr</b> (dawn), <b>Dhuhr</b> (midday), <b>Asr</b> (afternoon), "
                "<b>Maghrib</b> (sunset), and <b>Isha</b> (night). Their times follow the "
                "movement of the sun and shift slightly each day and with the seasons.",
            ]),
            ("Units of prayer", [
                "Prayer is made of units called rak'ah (plural rak'at). Each rak'ah includes "
                "standing with recitation, bowing, and two prostrations. The obligatory "
                "numbers are: Fajr — two rak'at; Dhuhr — four; Asr — four; Maghrib — three; "
                "Isha — four. Voluntary prayers may be added before or after some of these.",
            ]),
            ("Preparation", [
                "Before praying, a Muslim performs ablution (wudu), a washing of the hands, "
                "mouth, nose, face, arms, head, and feet with clean water. Prayer is offered "
                "facing the Ka'bah in Mecca, which is why mosques worldwide include a niche "
                "(mihrab) marking that direction.",
            ]),
            ("Congregational prayer", [
                "Prayers may be offered alone or in congregation, led by an imam. In "
                "congregation, worshippers stand in rows and follow the imam's movements. "
                "The Friday midday prayer (Jumu'ah) replaces Dhuhr on Fridays and includes a "
                "sermon (khutbah).",
            ]),
            ("Purpose", [
                "The prayer punctuates the day with acts of remembrance — a rhythm of "
                "recitation, bowing, and prostration that Muslims regard as a direct "
                "conversation with God. Its five daily appointments are the most visible "
                "practice of Islamic life.",
            ]),
        ],
    ),
]


def make_cover(path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 800, 1200
    img = Image.new("RGB", (w, h), "#1d4f45")
    draw = ImageDraw.Draw(img)
    # frame
    draw.rectangle([32, 32, w - 32, h - 32], outline="#f2ede1", width=3)
    draw.rectangle([48, 48, w - 48, h - 48], outline="#f2ede1", width=1)

    def font(size: int):
        for name in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        ):
            if Path(name).exists():
                return ImageFont.truetype(name, size)
        return ImageFont.load_default()

    title_f = font(64)
    small_f = font(28)

    title = "A Glossary of\nIslamic Terms"
    y = 420
    for line in title.split("\n"):
        bbox = draw.textbbox((0, 0), line, font=title_f)
        x = (w - (bbox[2] - bbox[0])) / 2
        draw.text((x, y), line, font=title_f, fill="#f2ede1")
        y += 84

    author = "Maktaba Sample Editions"
    bbox = draw.textbbox((0, 0), author, font=small_f)
    draw.text(((w - (bbox[2] - bbox[0])) / 2, 860), author, font=small_f, fill="#f2ede1")

    img.save(path, format="JPEG", quality=88)
    return path


def main() -> None:
    for booklet in BOOKLETS:
        path = build_pdf(
            booklet["filename"], booklet["title"], booklet["subtitle"], booklet["sections"]
        )
        print(f"created {path} ({path.stat().st_size} bytes)")

    cover = make_cover(OUT_DIR / "cover-glossary.jpg")
    print(f"created {cover} ({cover.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
