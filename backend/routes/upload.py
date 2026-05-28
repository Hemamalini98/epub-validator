import asyncio
import io
import shutil
import zipfile
from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, Response
from pathlib import Path
from pydantic import BaseModel
from services.upload_service import process_upload, get_extract_files, UPLOAD_DIR, EXTRACT_DIR
from services.validate_service import validate_epub
from services.books_service import get_all_books, delete_book as delete_book_record
from services.pdf_service import find_pdf_page, render_pdf_page, get_chapter_pdf

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


@router.delete("/books/{folder_name}")
async def remove_book(folder_name: str):
    removed = delete_book_record(folder_name)
    if not removed:
        raise HTTPException(status_code=404, detail="Book not found")
    folder_path = Path(UPLOAD_DIR) / folder_name
    if folder_path.exists():
        await asyncio.to_thread(shutil.rmtree, folder_path)
    return {"status": True, "message": "Book deleted"}


@router.post("/upload")
async def upload_zip(file: UploadFile = File(...)):
    return await process_upload(file)


@router.get("/file-data/{folder_name}")
def list_files(folder_name: str):
    return get_extract_files(folder_name)


@router.get("/file-data/{folder_name}/{file_path:path}")
async def get_file_content(folder_name: str, file_path: str):
    base = (Path(UPLOAD_DIR) / folder_name / EXTRACT_DIR / "epub").resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


@router.put("/file-data/{folder_name}/{file_path:path}")
async def save_file_content(folder_name: str, file_path: str, body: SaveFileRequest):
    base = (Path(UPLOAD_DIR) / folder_name / EXTRACT_DIR / "epub").resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # Write file in thread pool so the event loop stays free
    await asyncio.to_thread(target.write_text, body.content, encoding="utf-8")
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
    # PyMuPDF is CPU-bound; run in thread so other requests aren't blocked
    return await asyncio.to_thread(find_pdf_page, folder_name, file)


@router.get("/pdf/{folder_name}/chapter")
async def get_chapter_pdf_endpoint(folder_name: str, file: str = Query(...)):
    try:
        path = await asyncio.to_thread(get_chapter_pdf, folder_name, file)
        return FileResponse(path, media_type="application/pdf")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PDF not found")


@router.get("/pdf/{folder_name}/render")
async def render_pdf_page_endpoint(folder_name: str, page: int = Query(1)):
    try:
        png_bytes = await asyncio.to_thread(render_pdf_page, folder_name, page)
        return Response(content=png_bytes, media_type="image/png")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PDF not found")


@router.get("/validate/{filename}")
async def validate_file(filename: str, file: str = Query(None)):
    # validate_epub does heavy file I/O + network calls — run in thread pool
    # so every concurrent user gets their own thread and the event loop stays free
    epub_folder = f"uploads/{filename}/extract/epub"
    return await asyncio.to_thread(
        validate_epub,
        epub_folder=epub_folder,
        folder_name=filename,
        target_file=file,
    )


@router.post("/export/{folder_name}")
async def export_epub(folder_name: str, body: ExportRequest):
    if body.failed > 0:
        raise HTTPException(
            status_code=400,
            detail="There are validation errors. Please fix them before downloading.",
        )

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

    # Build the zip in a thread — file traversal + compression are CPU/IO bound
    def _build_zip() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
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
        return buf.getvalue()

    zip_bytes = await asyncio.to_thread(_build_zip)
    return Response(
        content=zip_bytes,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{folder_name}.epub"'},
    )
