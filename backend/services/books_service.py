import json
import os
import threading

BOOKS_FILE = "books.json"

# Single lock shared across all threads in a process.
# Prevents concurrent uploads from producing a torn books.json.
_lock = threading.Lock()


def _load() -> list:
    if not os.path.exists(BOOKS_FILE):
        return []
    with open(BOOKS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _save(books: list) -> None:
    with open(BOOKS_FILE, "w", encoding="utf-8") as f:
        json.dump(books, f, indent=2)


def upsert_book(book: dict) -> None:
    with _lock:
        books = _load()
        idx = next(
            (i for i, b in enumerate(books) if b.get("folder_name") == book.get("folder_name")),
            None,
        )
        if idx is not None:
            books[idx] = {**books[idx], **book}
        else:
            books.insert(0, book)
        _save(books)


def get_all_books() -> list:
    with _lock:
        return _load()


def delete_book(folder_name: str) -> bool:
    with _lock:
        books = _load()
        new_books = [b for b in books if b.get("folder_name") != folder_name]
        if len(new_books) == len(books):
            return False
        _save(new_books)
        return True
