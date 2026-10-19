"""Plan kartını Claude'a yapıştırılacak tek metne çevirir (Kopyala düğmesi)."""
from __future__ import annotations


def format_card(card: dict) -> str:
    lines = [f"# {card['title'] or '(başlıksız kart)'}", ""]
    if (card.get("note") or "").strip():
        lines += ["## Notlarım", card["note"].strip(), ""]
    lines.append("## Videolar")
    if not card["items"]:
        lines.append("(henüz video eklenmedi)")
    for n, it in enumerate(card["items"], 1):
        title = it.get("title") or "(başlıksız)"
        lines.append(f"{n}. [{it['category']} / {it['subcategory']}] {title} ({it['platform']})")
        lines.append(f"   Link: {it['url']}")
        if (it.get("card_note") or "").strip():
            lines.append(f"   Not: {_indent(it['card_note'])}")
        if (it.get("note") or "").strip():
            lines.append(f"   Kayıt notu: {_indent(it['note'])}")
        if it.get("file_path"):
            lines.append(f"   Dosya: {it['file_path']}")
    return "\n".join(lines).rstrip() + "\n"


def _indent(text: str) -> str:
    return text.strip().replace("\n", "\n        ")
