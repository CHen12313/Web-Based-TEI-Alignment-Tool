from bs4 import BeautifulSoup, Tag
from pathlib import Path

SAMPLES_FOLDER = Path(__file__).resolve().parent.parent / "celt_samples"

def load_tei(file_path: str) -> BeautifulSoup:
    raw_text = Path(file_path).read_text(encoding="iso-8859-1")
    return BeautifulSoup(raw_text, "html.parser")

def load_file_pair(file_code: str, file_storage_dir: str = SAMPLES_FOLDER) -> BeautifulSoup:
    original_file_path: Path = file_storage_dir / Path(f"G{file_code}.xml") 
    translation_file_path: Path = file_storage_dir / Path(f"T{file_code}.xml")

    raw_original_text = original_file_path.read_text(encoding="iso-8859-1")
    raw_translation_text = translation_file_path.read_text(encoding="iso-8859-1")

    return BeautifulSoup(raw_original_text, "html.parser"), BeautifulSoup(raw_translation_text, "html.parser")