import io
import json
from pathlib import Path
from pypdf import PdfReader


def extract_text(filename: str, content_type: str | None, data: bytes) -> tuple[str, dict]:
    ext = Path(filename).suffix.lower()
    meta: dict = {"extension": ext, "content_type": content_type}

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for idx, page in enumerate(reader.pages):
            pages.append(page.extract_text() or "")
        meta["pages"] = len(reader.pages)
        return "\n\n".join(pages), meta

    if ext in {".txt", ".md", ".csv", ".json", ".xml"}:
        text = data.decode("utf-8", errors="replace")
        if ext == ".json":
            try:
                meta["json_top_level_type"] = type(json.loads(text)).__name__
            except Exception:
                pass
        return text, meta

    # CAD/BIM metadata placeholder: the pipeline is wired so an IFC/DWG/RVT parser can
    # be added without changing the upload architecture. IFC parsing commonly uses
    # IfcOpenShell; DWG/RVT normally need dedicated converters or vendor SDKs.
    if ext in {".ifc", ".dwg", ".rvt"}:
        meta["cad_bim"] = True
        meta["parser_status"] = "parser_plugin_required"
        return "", meta

    return "", meta


def split_text(text: str, max_chars: int = 4000, overlap: int = 400) -> list[str]:
    if not text.strip():
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks
