import io
import zipfile
from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, Response
from pathlib import Path
from pydantic import BaseModel
from services.upload_service import process_upload, get_extract_files, UPLOAD_DIR, EXTRACT_DIR
from services.validate_service import validate_epub
from services.books_service import get_all_books
from services.pdf_service import find_pdf_page, render_pdf_page

router = APIRouter()


class ExportRequest(BaseModel):
    failed: int = 0
    warnings: int = 0
    pending: int = 0
    force: bool = False


class SaveFileRequest(BaseModel):
    content: str

@router.get("/health")
def health_check():
    return {"status": "healthy"}

@router.get("/books")
def list_books():
    return get_all_books()


@router.post("/upload")
async def upload_zip(file: UploadFile = File(...)):
      response = await process_upload(file)
      return response

@router.get("/files/{folder_name}")
async def list_files(folder_name: str):
    return get_extract_files(folder_name)

@router.get("/files/{folder_name}/{file_path:path}")
async def get_file_content(folder_name: str, file_path: str):
    base = (Path(UPLOAD_DIR) / folder_name / EXTRACT_DIR / "epub").resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)  # auto-detects MIME type: text/css, image/png, etc.


@router.put("/files/{folder_name}/{file_path:path}")
async def save_file_content(folder_name: str, file_path: str, body: SaveFileRequest):
    base = (Path(UPLOAD_DIR) / folder_name / EXTRACT_DIR / "epub").resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    target.write_text(body.content, encoding="utf-8")
    return {"status": True, "message": "File saved"}

@router.get("/pdf/{folder_name}")
async def get_pdf(folder_name: str):
    base = (Path(UPLOAD_DIR) / folder_name / EXTRACT_DIR).resolve()
    pdf_path = (base / f"{folder_name}.pdf").resolve()
    if not str(pdf_path).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(pdf_path, media_type="application/pdf")


@router.get("/pdf/{folder_name}/page")
async def get_pdf_page(folder_name: str, file: str = Query(...)):
    return find_pdf_page(folder_name, file)


@router.get("/pdf/{folder_name}/render")
async def render_pdf_page_endpoint(folder_name: str, page: int = Query(1)):
    try:
        png_bytes = render_pdf_page(folder_name, page)
        return Response(content=png_bytes, media_type="image/png")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PDF not found")


@router.get("/validate/{filename}")
async def validate_file(filename: str,file: str = Query(None)):

    epub_folder = f"uploads/{filename}/extract/epub"

    return validate_epub(
        epub_folder=epub_folder,
        folder_name=filename,
         target_file=file
    )


@router.post("/export/{folder_name}")
async def export_epub(folder_name: str, body: ExportRequest):
    # Block export when there are hard errors
    if body.failed > 0:
        raise HTTPException(
            status_code=400,
            detail="There are validation errors. Please fix them before downloading.",
        )

    # Require confirmation when warnings or unvalidated files are present
    if (body.warnings > 0 or body.pending > 0) and not body.force:
        parts: list[str] = []
        if body.warnings > 0:
            parts.append(f"{body.warnings} warning{'s' if body.warnings != 1 else ''}")
        if body.pending > 0:
            parts.append(f"{body.pending} unvalidated file{'s' if body.pending != 1 else ''}")
        return {
            "status": "confirm",
            "message": f"There {'are' if len(parts) > 1 else 'is'} {' and '.join(parts)}. Proceed with export anyway?",
        }

    epub_dir = (Path(UPLOAD_DIR) / folder_name / "extract" / "epub").resolve()
    if not epub_dir.is_dir():
        raise HTTPException(status_code=404, detail="EPUB source directory not found.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # EPUB spec: mimetype must be the first entry and stored uncompressed
        mimetype_path = epub_dir / "mimetype"
        if mimetype_path.is_file():
            zf.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
        else:
            info = zipfile.ZipInfo("mimetype")
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, "application/epub+zip")

        for fp in sorted(epub_dir.rglob("*")):
            if fp.is_file() and fp.name != "mimetype":
                zf.write(fp, fp.relative_to(epub_dir).as_posix(), compress_type=zipfile.ZIP_DEFLATED)

    return Response(
        content=buf.getvalue(),
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{folder_name}.epub"'},
    )