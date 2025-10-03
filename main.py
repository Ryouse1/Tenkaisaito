import os
import shutil
import tarfile
import zipfile
import tempfile
import uuid
from fastapi import FastAPI, File, UploadFile, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import magic

# optional libs
from PyPDF2 import PdfReader
from docx import Document
try:
    import py7zr
    HAS_PY7ZR = True
except:
    HAS_PY7ZR = False

app = FastAPI()
BASE_TMP = tempfile.mkdtemp(prefix="file_analyzer_")
# map: id -> extracted folder path
EXTRACT_MAP = {}

# ----------------- ヘルパー -----------------
def is_within_directory(directory: str, target: str) -> bool:
    abs_directory = os.path.abspath(directory)
    abs_target = os.path.abspath(target)
    # os.path.commonpath の方が堅牢
    return os.path.commonpath([abs_directory, abs_target]) == abs_directory

def safe_extract_zip(zip_path: str, extract_path: str):
    with zipfile.ZipFile(zip_path, 'r') as z:
        for member in z.namelist():
            member_path = os.path.join(extract_path, member)
            if not is_within_directory(extract_path, member_path):
                raise Exception("Zip contains path traversal (Zip Slip)")
        z.extractall(extract_path)

def safe_extract_tar(tar_path: str, extract_path: str):
    with tarfile.open(tar_path) as tar:
        for member in tar.getmembers():
            member_path = os.path.join(extract_path, member.name)
            if not is_within_directory(extract_path, member_path):
                raise Exception("Tar contains path traversal (Zip Slip)")
        tar.extractall(extract_path)

def safe_extract_7z(archive_path: str, extract_path: str):
    if not HAS_PY7ZR:
        raise Exception("py7zr is not installed; cannot extract 7z")
    with py7zr.SevenZipFile(archive_path, 'r') as z:
        # py7zr handles names but still check after extraction
        z.extractall(path=extract_path)
        # validate extracted paths
        for root, dirs, files in os.walk(extract_path):
            for name in files + dirs:
                p = os.path.join(root, name)
                if not is_within_directory(extract_path, p):
                    raise Exception("7z extraction produced path outside target")

def zip_dir(folder_path: str, zip_path: str):
    # zip 作成（相対パスで格納）
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                full_path = os.path.join(root, file)
                # arcname は基点からの相対パス
                arcname = os.path.relpath(full_path, folder_path)
                zipf.write(full_path, arcname)

def is_archive_by_extension(fname: str) -> bool:
    ext = fname.lower()
    return ext.endswith(".zip") or ext.endswith(".tar") or ext.endswith(".tar.gz") or ext.endswith(".tgz") or ext.endswith(".7z")

def is_archive_by_signature(path: str) -> bool:
    # 最も確実ではないが補助判定
    try:
        if zipfile.is_zipfile(path): return True
        if tarfile.is_tarfile(path): return True
        if HAS_PY7ZR:
            # crude check: 7z signature
            with open(path, "rb") as f:
                head = f.read(6)
            if head.startswith(b"7z\xBC\xAF\x27\x1C"):
                return True
        return False
    except:
        return False

def extract_recursively(base_dir: str, max_depth: int = 2):
    """
    指定ディレクトリ内のアーカイブを再帰展開する（max_depthまで）。
    発見したアーカイブはその場でフォルダを作って展開する。
    """
    for depth in range(max_depth):
        found = False
        for root, dirs, files in os.walk(base_dir):
            for fname in files:
                path = os.path.join(root, fname)
                # Skip files already extracted as part of archive dirs (heuristic)
                if path.endswith("_extracted.zip"):  # our own zips
                    continue
                # detect archive
                if zipfile.is_zipfile(path) or tarfile.is_tarfile(path) or (HAS_PY7ZR and path.lower().endswith(".7z")):
                    found = True
                    # create folder next to file
                    target_dir = os.path.join(root, fname + "_extracted")
                    os.makedirs(target_dir, exist_ok=True)
                    try:
                        if zipfile.is_zipfile(path):
                            safe_extract_zip(path, target_dir)
                        elif tarfile.is_tarfile(path):
                            safe_extract_tar(path, target_dir)
                        elif HAS_PY7ZR and path.lower().endswith(".7z"):
                            safe_extract_7z(path, target_dir)
                    except Exception as e:
                        # write error file into target_dir for user to see
                        with open(os.path.join(target_dir, "EXTRACT_ERROR.txt"), "w", encoding="utf-8") as ef:
                            ef.write(str(e))
        if not found:
            break

def extract_strings_preview(file_path: str, ext: str):
    try:
        if ext == ".pdf":
            reader = PdfReader(file_path)
            return "\n".join([page.extract_text() or "" for page in reader.pages])[:2000]
        elif ext == ".docx":
            doc = Document(file_path)
            return "\n".join([p.text for p in doc.paragraphs])[:2000]
        else:
            with open(file_path, "rb") as bf:
                content = bf.read(4096)  # 先頭4KBのみでpreview
            return ''.join([chr(b) if 32 <= b < 127 else '.' for b in content])
    except Exception as e:
        return f"文字列抽出不可: {e}"

# ----------------- ルート -----------------
@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

# ----------------- アップロード -----------------
@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        fid = uuid.uuid4().hex
        base_dir = os.path.join(BASE_TMP, fid)
        os.makedirs(base_dir, exist_ok=True)

        # save uploaded file (streamed)
        saved_path = os.path.join(base_dir, f.filename)
        with open(saved_path, "wb") as out_f:
            shutil.copyfileobj(f.file, out_f)

        # optional: detect mime
        try:
            mime = magic.Magic(mime=True)
            file_info = mime.from_file(saved_path)
        except:
            file_info = "形式判定不可"

        # create extraction target dir
        extracted_dir = os.path.join(base_dir, "extracted")
        os.makedirs(extracted_dir, exist_ok=True)

        # decide how to handle:
        try:
            # If file is archive by signature or extension -> extract
            if is_archive_by_signature(saved_path) or is_archive_by_extension(f.filename):
                # handle based on type
                if zipfile.is_zipfile(saved_path):
                    safe_extract_zip(saved_path, extracted_dir)
                elif tarfile.is_tarfile(saved_path):
                    safe_extract_tar(saved_path, extracted_dir)
                elif HAS_PY7ZR and f.filename.lower().endswith(".7z"):
                    safe_extract_7z(saved_path, extracted_dir)
                else:
                    # unknown archive type -> attempt both zip/tar
                    try:
                        safe_extract_zip(saved_path, extracted_dir)
                    except:
                        safe_extract_tar(saved_path, extracted_dir)

                # nested extraction (depth-limited)
                extract_recursively(extracted_dir, max_depth=2)
            else:
                # not an archive: copy uploaded file into extracted_dir so download always returns a zip
                shutil.copy2(saved_path, os.path.join(extracted_dir, f.filename))
        except Exception as e:
            # extraction error: include an error file so user can see
            with open(os.path.join(extracted_dir, "EXTRACT_ERROR.txt"), "w", encoding="utf-8") as ef:
                ef.write(str(e))

        # gather extracted file list (relative paths)
        extracted_files = []
        for root, dirs, files in os.walk(extracted_dir):
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), extracted_dir)
                extracted_files.append(rel)

        # store mapping for download
        EXTRACT_MAP[fid] = {
            "base_dir": base_dir,
            "extracted_dir": extracted_dir,
            "orig_filename": f.filename
        }

        # prepare a small preview (first file if exists)
        preview_text = None
        if extracted_files:
            # preview first file
            first = os.path.join(extracted_dir, extracted_files[0])
            ext = os.path.splitext(first)[1].lower()
            preview_text = extract_strings_preview(first, ext)
        else:
            # preview original file
            preview_text = extract_strings_preview(saved_path, os.path.splitext(saved_path)[1].lower())

        results.append({
            "id": fid,
            "filename": f.filename,
            "file_info": file_info,
            "extracted_count": len(extracted_files),
            "extracted_files": extracted_files,
            "preview": preview_text,
            "download_url": f"/download/{fid}"
        })

    return JSONResponse(results)

# ----------------- ダウンロード -----------------
def cleanup_paths(paths):
    for p in paths:
        try:
            if os.path.isfile(p):
                os.remove(p)
            elif os.path.isdir(p):
                shutil.rmtree(p)
        except Exception:
            pass

@app.get("/download/{fid}")
def download_extracted(fid: str, background_tasks: BackgroundTasks):
    info = EXTRACT_MAP.get(fid)
    if not info:
        return JSONResponse({"error": "IDが見つかりません"}, status_code=404)

    extracted_dir = info["extracted_dir"]
    if not os.path.exists(extracted_dir):
        return JSONResponse({"error": "展開ディレクトリが存在しません"}, status_code=404)

    zip_path = os.path.join(BASE_TMP, f"{fid}_extracted.zip")
    # recreate zip each time (safe)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    zip_dir(extracted_dir, zip_path)

    # schedule cleanup of zip and base_dir after response is sent
    base_dir = info["base_dir"]
    background_tasks.add_task(cleanup_paths, [zip_path, base_dir])
    # remove map immediately to avoid reuse
    EXTRACT_MAP.pop(fid, None)

    return FileResponse(zip_path, media_type="application/zip", filename=f"{info['orig_filename']}_extracted.zip")
