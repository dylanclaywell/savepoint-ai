"""RAG helpers: chunk markdown for embedding, and assemble retrieved context.

The vector storage + search lives in workspaces.py (it owns the per-game DB);
this module is the model-agnostic text side.
"""

from __future__ import annotations

CHUNK_TARGET = 600  # approx chars per chunk


def chunk_text(markdown: str) -> list[str]:
    """Split a document into retrieval-sized chunks on paragraph boundaries.

    Paragraphs (blank-line separated) are greedily merged toward CHUNK_TARGET;
    an over-long paragraph is hard-split so no chunk is unboundedly large.
    """
    paras = [p.strip() for p in markdown.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if len(para) > CHUNK_TARGET * 2:
            if buf:
                chunks.append(buf)
                buf = ""
            for i in range(0, len(para), CHUNK_TARGET):
                chunks.append(para[i : i + CHUNK_TARGET])
            continue
        if buf and len(buf) + len(para) + 2 > CHUNK_TARGET:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def build_context(snippets: list[dict]) -> str:
    """Format retrieved snippets into a system preamble the model can ground on.

    Each snippet is {title, text, ...}. Grouped/labelled by source title so the
    model can cite, and instructed not to invent beyond the notes.
    """
    blocks = []
    for s in snippets:
        blocks.append(f"[{s['title']}]\n{s['text']}")
    notes = "\n\n".join(blocks)
    return (
        "The designer has shared the following notes from this game's knowledge "
        "base. Ground your response in them where relevant, and cite the source "
        "in brackets like [Title]. If the notes don't cover something, say so "
        "rather than inventing detail.\n\n"
        f"{notes}"
    )
