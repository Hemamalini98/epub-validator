from fastapi import UploadFile
from fastapi.responses import JSONResponse
import os
import zipfile
from pathlib import Path
import shutil
from datetime import date
from services.books_service import upsert_book

UPLOAD_DIR = "uploads"
EXTRACT_DIR = "extract"

os.makedirs(UPLOAD_DIR, exist_ok=True)

async def process_upload(file: UploadFile):

    # Validate ZIP
    if not file.filename.endswith(".zip"):
        return JSONResponse(
            status_code=400,
            content={"status": False, "message": "Only ZIP files are allowed"}
        )

    filename = Path(file.filename).stem

    zip_path = os.path.join(
        UPLOAD_DIR,
        filename,
        file.filename
    )

    upload_folder = os.path.join(
        UPLOAD_DIR,
        filename,      
    )

    os.makedirs(upload_folder, exist_ok=True)


    # Save ZIP
    with open(zip_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    expected_epub = f"{filename}.epub"
    expected_pdf = f"{filename}.pdf"

    extract_folder = os.path.join(
        upload_folder,
        EXTRACT_DIR,
    )

    # Already exists
    if os.path.exists(extract_folder):
        return JSONResponse(
            status_code=400,
            content={
                "status": False,
                "message": f"{filename} already present"
            }
        )

    try:

        with zipfile.ZipFile(zip_path, "r") as zip_ref:

            file_list = zip_ref.namelist()

            epub_found = False
            pdf_found = False

            for item in file_list:

                base_name = os.path.basename(item)

                if base_name == expected_epub:
                    epub_found = True

                if base_name == expected_pdf:
                    pdf_found = True

            # Validate files
            if not epub_found or not pdf_found:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": False,
                        "message": (
                            f"ZIP must contain "
                            f"{expected_epub} and {expected_pdf}"
                        )
                    }
                )

            # Create folder
            os.makedirs(extract_folder)

            # Extract ZIP
            zip_ref.extractall(extract_folder)

        # EPUB extract path
        epub_path = os.path.join(
            extract_folder,
            expected_epub
        )

        epub_extract_path = os.path.join(
            extract_folder,
            "epub"
        )

        os.makedirs(epub_extract_path, exist_ok=True)

        # Extract EPUB
        with zipfile.ZipFile(epub_path, "r") as epub_ref:
            epub_ref.extractall(epub_extract_path)

        total_files = sum(len(files) for _, _, files in os.walk(epub_extract_path))

        upsert_book({
            "folder_name": filename,
            "epub_path": epub_extract_path,
            "uploaded_at": date.today().isoformat(),
            "total_files": total_files,
        })

        return {
            "status": True,
            "message": "Upload successful",
            "extract_folder": extract_folder,
            "epub_extract_path": epub_extract_path,
            "epub_file": epub_path,
            "pdf_file": os.path.join(
                extract_folder,
                expected_pdf
            )
        }

    except zipfile.BadZipFile:
        return JSONResponse(
            status_code=400,
            content={"status": False, "message": "Invalid ZIP file"}
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": False, "message": str(e)}
        )
    
def get_extract_files(folder_name: str):

    extract_folder = os.path.join(
        UPLOAD_DIR,
        folder_name,
        EXTRACT_DIR,
        "epub"
    )

    # Folder not found
    if not os.path.exists(extract_folder):
        return {
            "status": False,
            "message": "Folder not found"
        }

    files_data = []

    for root, dirs, files in os.walk(extract_folder):

        for file in files:

            full_path = os.path.join(root, file)

            relative_path = os.path.relpath(
                full_path,
                extract_folder
            )

            files_data.append({
                "file_name": file,
                "path": relative_path
            })

    return {
        "status": True,
        "folder": folder_name,
        "total_files": len(files_data),
        "files": files_data
    }