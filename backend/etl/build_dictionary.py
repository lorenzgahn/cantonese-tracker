"""Phase 2: one-time dictionary ETL. Downloads CC-Canto, parses it, builds
the hanzi and jyutping lookup indexes, and serializes to
backend/data/dictionary.json.

Run manually — not part of app startup:

    backend/.venv/bin/python backend/etl/build_dictionary.py

--- Scope decision (found during this ETL, not assumed in advance) ---

SPEC.md §6 names two source files: CC-Canto (`cccanto-webdist.txt`) and a
"CC-CEDICT Cantonese readings" file (`cccedict-canto-readings-*.txt`).
Inspecting the actual downloaded files showed they are NOT parallel
dictionaries — cccanto-webdist.txt has real definitions
(`[pinyin] {jyutping} /def1/def2/`), but the cc-cedict-canto-readings file
has ONLY jyutping readings with NO definitions at all
(`[pinyin] {jyutping}`, nothing after). It exists to bolt Cantonese
readings onto the *separate*, not-yet-downloaded base CC-CEDICT (Mandarin)
dictionary from MDBG — which is out of scope for this pass.

v1 therefore indexes cccanto-webdist.txt only (~34K entries, all with
real definitions). Adding the CC-CEDICT-readings file is a clearly
separable Phase-2.1 enhancement (would need the base CC-CEDICT file
merged in for it to contribute any definitions at all), not a blocker for
having a working dictionary lookup now.
"""

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import urlopen

ETL_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = ETL_DIR / "downloads"
DATA_DIR = ETL_DIR.parent / "data"
DICTIONARY_PATH = DATA_DIR / "dictionary.json"

DOWNLOAD_PAGE = "https://cantonese.org/download.html"

# `traditional simplified [pinyin] {jyutping} /def1/def2/.../  # optional trailing comment`
# Verified against all 34,335 real (non-comment) lines in cccanto-webdist.txt:
# 34,334 match; the one non-match is a malformed upstream line (stray `}`
# mid-jyutping in the source data itself) — not a regex bug.
LINE_PATTERN = re.compile(
    r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+\{([^}]*)\}\s+/(.+)/\s*(?:#.*)?$"
)


@dataclass
class DictEntry:
    traditional: str
    simplified: str
    jyutping: str
    definitions: list[str] = field(default_factory=list)


def find_cccanto_filename() -> str:
    """Scrape the live download page rather than hardcoding a filename —
    per SPEC.md, these should be re-verified at build time, not assumed."""
    with urlopen(DOWNLOAD_PAGE, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    match = re.search(r'href="(cccanto-[\d]+\.zip)"', html)
    if not match:
        raise RuntimeError(
            f"Could not find a cccanto-*.zip link on {DOWNLOAD_PAGE} — "
            "the site's file naming may have changed; inspect manually."
        )
    return match.group(1)


def download_and_extract(zip_filename: str) -> Path:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DOWNLOADS_DIR / zip_filename

    if not zip_path.exists():
        print(f"Downloading {zip_filename} from cantonese.org...")
        with urlopen(f"https://cantonese.org/{zip_filename}", timeout=30) as resp:
            zip_path.write_bytes(resp.read())
    else:
        print(f"Using cached {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(DOWNLOADS_DIR)
        extracted_names = zf.namelist()

    # The archive contains one .txt file — find it rather than assuming a name.
    txt_names = [n for n in extracted_names if n.endswith(".txt")]
    if len(txt_names) != 1:
        raise RuntimeError(f"Expected exactly one .txt in {zip_filename}, found {txt_names}")
    return DOWNLOADS_DIR / txt_names[0]


def parse_cccanto(txt_path: Path) -> list[DictEntry]:
    entries: list[DictEntry] = []
    total = 0
    unparsed = 0
    with txt_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            total += 1
            m = LINE_PATTERN.match(line)
            if not m:
                unparsed += 1
                continue
            traditional, simplified, _pinyin, jyutping, defs_raw = m.groups()
            entries.append(
                DictEntry(
                    traditional=traditional,
                    simplified=simplified,
                    jyutping=jyutping.strip(),
                    definitions=[d for d in defs_raw.split("/") if d],
                )
            )
    print(f"Parsed {len(entries)}/{total} lines ({unparsed} unparsed, left as a gap not a crash)")
    return entries


def normalize_jyutping_key(jyutping: str) -> str:
    return jyutping.replace(" ", "")


def build_indexes(entries: list[DictEntry]) -> tuple[dict, dict]:
    hanzi_index: dict[str, list[dict]] = {}
    jyutping_index: dict[str, list[dict]] = {}

    for entry in entries:
        record = {
            "traditional": entry.traditional,
            "simplified": entry.simplified,
            "jyutping": entry.jyutping,
            "definitions": entry.definitions,
        }
        for hanzi_key in {entry.traditional, entry.simplified}:
            hanzi_index.setdefault(hanzi_key, []).append(record)

        jkey = normalize_jyutping_key(entry.jyutping)
        jyutping_index.setdefault(jkey, []).append(record)

    return hanzi_index, jyutping_index


def main() -> None:
    zip_filename = find_cccanto_filename()
    print(f"Current cccanto archive on {DOWNLOAD_PAGE}: {zip_filename}")

    txt_path = download_and_extract(zip_filename)
    entries = parse_cccanto(txt_path)
    hanzi_index, jyutping_index = build_indexes(entries)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DICTIONARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            {"hanzi_index": hanzi_index, "jyutping_index": jyutping_index},
            f,
            ensure_ascii=False,
        )

    print(f"\nWrote {DICTIONARY_PATH}")
    print(f"  entries:         {len(entries)}")
    print(f"  hanzi keys:      {len(hanzi_index)}")
    print(f"  jyutping keys:   {len(jyutping_index)}")


if __name__ == "__main__":
    main()
