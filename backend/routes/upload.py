from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, Response
from pathlib import Path
from services.upload_service import process_upload, get_extract_files, UPLOAD_DIR, EXTRACT_DIR
from services.validate_service import validate_epub, build_book_summary
from services.books_service import get_all_books
from services.pdf_service import find_pdf_page, render_pdf_page

router = APIRouter()


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


@router.get("/summary/{folder_name}")
async def get_book_summary(folder_name: str):
    """Book-level summary for the UI's BookSummaryCard. Runs the three
    book-scope rules (LinkChecker, NavValidator, StyleComparator) and
    returns grouped-by-category rows with worst-status-wins per row."""
    return build_book_summary(folder_name)