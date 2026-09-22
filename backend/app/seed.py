"""Sample corpus for the 'Load sample dataset' first-run experience.

English texts that exercise every built-in detector: quality rules
(too short/long, repetition, spam, code, toxicity, PII) plus exact and
near duplicates for the dedup jobs.
"""
from __future__ import annotations

SEED_FILES: list[tuple[str, str]] = [
    ("01-instruction.txt",
     "Summarize the following article in three bullet points, then explain "
     "the main takeaway in one sentence for a general audience."),
    ("02-instruction.txt",
     "Rewrite the given paragraph in a friendlier tone while keeping all "
     "the facts intact. Answer in the same language as the input."),
    ("03-instruction.txt",
     "Classify the customer message into billing, technical, or general "
     "support, and reply with a short acknowledgment template."),
    ("04-knowledge.txt",
     "The mitochondrion is the site of cellular respiration. It converts "
     "nutrients into ATP, the energy currency of the cell, through a "
     "multi-step cycle that also requires oxygen."),
    ("05-knowledge.txt",
     "Photosynthesis lets plants convert sunlight into chemical energy, "
     "releasing oxygen as a by-product. Chlorophyll absorbs red and "
     "blue light while reflecting green wavelengths."),
    ("06-review.txt",
     "The product arrived on time and matches the description. Setup took "
     "five minutes and the manual was clear. Would recommend to anyone "
     "starting with home automation."),
    ("07-review.txt",
     "The product arrived on time and matches the description. Setup took "
     "five minutes and the manual was clear. Would recommend to anyone "
     "beginning with home automation."),  # near duplicate of 06
    ("08-exact-a.txt",
     "Returns are accepted within 30 days when the item is unused and the "
     "original packaging is intact. Refunds are issued to the original "
     "payment method within five business days."),
    ("09-exact-b.txt",
     "Returns are accepted within 30 days when the item is unused and the "
     "original packaging is intact. Refunds are issued to the original "
     "payment method within five business days."),  # exact duplicate of 08
    ("10-too-short.txt", "ok"),
    ("11-spam.txt",
     "BUY NOW!!! LIMITED OFFER!!! CLICK HERE!!! 100% FREE!!! "
     "ACT TODAY!!! GUARANTEED WINNINGS!!! NO RISK!!!"),
    ("12-code.txt",
     "def process(items):\n    for item in items:\n        if item.valid:\n"
     "            yield transform(item)\n    return None"),
    ("13-toxicity.txt", "fuck shit bitch"),
    ("14-pii.txt",
     "Contact John at john.doe@example.com or call 555-867-5309. "
     "His card is 4111 1111 1111 1111 and he asked for a callback."),
    ("15-repetition.txt",
     "the quick brown fox jumps over the lazy dog the quick brown fox "
     "jumps over the lazy dog the quick brown fox jumps over the lazy "
     "dog the quick brown fox jumps over the lazy dog"),
    ("16-dialogue.txt",
     "User: I need to reschedule my delivery.\n"
     "Agent: Sure, I can move it to next Tuesday. Does that work?\n"
     "User: Yes, after 5pm please.\n"
     "Agent: Done — you will get a confirmation email shortly."),
]


def long_unique_text() -> str:
    """~120k chars of varied sentences so the too-long detector fires without repetition."""
    parts = []
    i = 0
    target = 120_000
    while sum(len(p) for p in parts) < target:
        parts.append(f"Sentence number {i} discusses subject {i} with "
                     f"measure {i} and conclusion {i} for record {i}. ")
        i += 1
    return "".join(parts)
