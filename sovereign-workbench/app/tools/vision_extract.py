"""
tools/vision_extract.py
=======================
VisionExtractTool — multimodal structured extraction from images and PDFs.

Design
------
* Input: a local file path.  If the file is a PDF, each page is rasterised
  to a PIL Image via pdf2image before being sent to the vision model.
  If the file is already an image (PNG, JPG, JPEG, TIFF, BMP, WEBP), it is
  sent directly.
* The vision model is prompted to return **structured JSON only** — prose
  output is rejected and retried (up to MAX_RETRIES times).
* The JSON schema expected from the model is a list of page results:
      [
        {
          "page": 1,
          "fields": [{"name": "...", "value": "...", "region": "..."}],
          "tables": [{"title": "...", "headers": [...], "rows": [[...]]}],
          "annotations": [{"text": "...", "region": "..."}]
        },
        ...
      ]
* Audit: one VISION_EXTRACT record per call, containing source file,
  page_count, aggregate field_count and table_count.  Full extracted content
  is NOT written to the log.

Sovereignty note
----------------
No network calls except via OllamaClient → localhost:11434.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from app.audit.logger import AuditLogger, EventType
from app.tools.base import BaseTool, ToolResult

_log = logging.getLogger("sovereign.tools.vision_extract")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
_PDF_SUFFIX = ".pdf"
_MAX_RETRIES = 2

# System prompt that forces the vision model to respond in JSON.
_SYSTEM_PROMPT = """\
You are a document extraction assistant.  Analyse the provided image and return
ONLY a valid JSON object with EXACTLY the following keys (do not add prose or
markdown fences):

{
  "page": <integer — page number, 1-based>,
  "fields": [
    {"name": "<field label>", "value": "<extracted value>", "region": "<approximate location e.g. top-left, header, footer>"}
  ],
  "tables": [
    {"title": "<table title or empty string>", "headers": ["<col1>", "..."], "rows": [["<cell>", "..."]]}
  ],
  "annotations": [
    {"text": "<handwritten or stamped text>", "region": "<approximate location>"}
  ]
}

If a section (fields / tables / annotations) has no entries, return an empty
list for that key.  Return NOTHING other than the JSON object."""


def _image_to_base64(img) -> str:  # img: PIL.Image.Image
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _parse_vision_json(raw: str) -> Optional[dict]:
    """
    Try to parse the model's raw output as JSON.

    Strips markdown code fences if the model added them despite the prompt.
    Returns None if parsing fails.
    """
    text = raw.strip()
    # Strip ```json ... ``` or ``` ... ``` wrappers
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "page" in obj:
            return obj
        return None
    except json.JSONDecodeError:
        return None


class VisionExtractTool(BaseTool):
    """
    Extract structured fields, tables, and annotations from an image or PDF.

    Parameters
    ----------
    llm_client:
        An OllamaClient initialised with a *vision-capable* model
        (e.g. qwen25vl_3b or qwen25vl_7b).
    audit_logger:
        Shared AuditLogger instance.
    """

    name = "vision_extract"
    description = (
        "Extract structured fields, tables, and handwritten annotations from "
        "an image (.png, .jpg, etc.) or a PDF file.  Returns a list of "
        "per-page JSON objects with fields, tables, and annotations."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to an image or PDF file.",
            },
            "request_id": {
                "type": "string",
                "description": "Correlation ID propagated through the audit log.",
            },
        },
        "required": ["file_path"],
    }

    def __init__(
        self,
        llm_client: Any,       # OllamaClient — avoid circular import
        audit_logger: Optional[AuditLogger] = None,
    ) -> None:
        self._llm = llm_client
        self._audit = audit_logger

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(self, **kwargs: Any) -> ToolResult:
        file_path_str: Optional[str] = kwargs.get("file_path")
        request_id: Optional[str] = kwargs.get("request_id")

        if not file_path_str:
            return ToolResult(
                success=False,
                output=None,
                error="Missing required argument: file_path",
            )

        path = Path(file_path_str)
        if not path.exists():
            return ToolResult(
                success=False,
                output=None,
                error=f"File not found: {file_path_str}",
            )

        suffix = path.suffix.lower()

        # Rasterise PDF, or load image directly
        try:
            images = self._load_images(path, suffix)
        except Exception as exc:
            return ToolResult(
                success=False,
                output=None,
                error=f"Failed to load file '{file_path_str}': {exc}",
            )

        page_count = len(images)
        t0 = time.monotonic()
        page_results: list[dict] = []
        field_count = 0
        table_count = 0

        for page_num, img in enumerate(images, start=1):
            result, err = await self._extract_page(img, page_num, request_id)
            if err:
                return ToolResult(
                    success=False,
                    output=None,
                    error=err,
                )
            page_results.append(result)
            field_count += len(result.get("fields", []))
            table_count += len(result.get("tables", []))

        elapsed_ms = (time.monotonic() - t0) * 1000

        # Audit log
        self._log_extraction(
            source_file=file_path_str,
            page_count=page_count,
            field_count=field_count,
            table_count=table_count,
            duration_ms=elapsed_ms,
            request_id=request_id,
        )

        return ToolResult(
            success=True,
            output=page_results,
            metadata={
                "source_file": file_path_str,
                "page_count": page_count,
                "field_count": field_count,
                "table_count": table_count,
                "duration_ms": round(elapsed_ms, 1),
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_images(self, path: Path, suffix: str) -> list:
        """Return a list of PIL Images, one per page/frame."""
        if suffix == _PDF_SUFFIX:
            # Defer import so tests can mock without requiring poppler
            from pdf2image import convert_from_path  # type: ignore
            images = convert_from_path(str(path), dpi=150, fmt="png")
            if not images:
                raise ValueError("pdf2image returned zero pages")
            return images
        elif suffix in _IMAGE_SUFFIXES:
            from PIL import Image  # type: ignore
            return [Image.open(path).convert("RGB")]
        else:
            raise ValueError(
                f"Unsupported file type '{suffix}'. "
                f"Supported: PDF, {', '.join(sorted(_IMAGE_SUFFIXES))}"
            )

    async def _extract_page(
        self,
        img,  # PIL.Image.Image
        page_num: int,
        request_id: Optional[str],
    ) -> tuple[dict, Optional[str]]:
        """
        Send one image to the vision model, retrying on non-JSON output.

        Returns (result_dict, error_string).  error_string is None on success.
        """
        b64 = _image_to_base64(img)

        for attempt in range(_MAX_RETRIES + 1):
            stronger = attempt > 0
            system = _SYSTEM_PROMPT
            if stronger:
                system = (
                    _SYSTEM_PROMPT
                    + "\n\nIMPORTANT: Your previous response was not valid JSON. "
                    "Return ONLY the JSON object, no other text."
                )

            messages = [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                f"Extract all structured information from page {page_num}. "
                                "Return ONLY the JSON object as specified."
                            ),
                        },
                    ],
                },
            ]

            try:
                resp = await self._llm.chat_completion(
                    messages,
                    request_id=request_id,
                    temperature=0.0,
                    max_tokens=2048,
                )
                parsed = _parse_vision_json(resp.content or "")
                if parsed is not None:
                    parsed["page"] = page_num  # enforce page number
                    return parsed, None

                _log.warning(
                    "Vision model returned non-JSON on attempt %d/%d for page %d",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    page_num,
                )

            except Exception as exc:
                _log.error("Vision model call failed on page %d: %s", page_num, exc)
                if attempt == _MAX_RETRIES:
                    return {}, f"Vision model call failed on page {page_num}: {exc}"

        return {}, (
            f"Vision model returned non-JSON after {_MAX_RETRIES + 1} attempt(s) "
            f"on page {page_num}. Cannot accept prose output."
        )

    def _log_extraction(
        self,
        source_file: str,
        page_count: int,
        field_count: int,
        table_count: int,
        duration_ms: float,
        request_id: Optional[str],
    ) -> None:
        if not self._audit:
            return
        try:
            self._audit.log_event(
                event_type=EventType.VISION_EXTRACT,
                request_id=request_id or "",
                payload={
                    "source_file": source_file,
                    "page_count": page_count,
                    "field_count": field_count,
                    "table_count": table_count,
                    "duration_ms": round(duration_ms, 1),
                },
            )
        except Exception as exc:
            _log.warning("Failed to write VISION_EXTRACT audit record: %s", exc)
