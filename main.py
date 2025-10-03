from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import os, shutil, tarfile, zipfile, tempfile
import magic

# PDF / docx 文字列抽出用
from PyPDF2 import PdfReader
from docx import Document

app = FastAPI()
UPLOAD_DIR = tempfile.mkdtemp()

# ─────────────── 展開用関数 ───────────────
def safe_extract_tar(tar_path, extract_path):
    try:
        with tarfile.open(tar_path) as tar:
            for member in tar.getmembers():
                member_path = os.path.join(extract_path, member.name)
                if not os.path.commonprefix([extract_path, member_path]) == extract_path:
                    continue
            tar.extractall(extract_path)
    except Exception as e:
        raise Exception(f"tar展開失敗: {e}")

def safe_extract_zip(zip_path, extract_path):
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.namelist():
                member_path = os.path.join(extract_path, member)
                if not os.path.commonprefix([extract_path, member_path]) == extract_path:
                    continue
            zip_ref.extractall(extract_path)
    except Exception as e:
        raise Exception(f"zip展開失敗: {e}")

def zip_dir(folder_path, zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, folder_path)
                zipf.write(full_path, arcname)

# ─────────────── 文字列抽出 ───────────────
def extract_strings(file_path, ext):
    try:
        if ext == ".pdf":
            reader = PdfReader(file_path)
            return "\n".join([page.extract_text() or "" for page in reader.pages])[:1000]
        elif ext in [".docx"]:
            doc = Document(file_path)
            return "\n".join([p.text for p in doc.paragraphs])[:1000]
        else:
            # バイナリとして文字列抽出（ASCII範囲のみ）
            with open(file_path, "rb") as bf:
                content = bf.read()
            return ''.join([chr(b) if 32 <= b < 127 else '.' for b in content])[:1000]
    except:
        return "文字列抽出不可"

# ─────────────── ルート ───────────────
@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", "r") as f:
        return f.read()

# ─────────────── アップロード ───────────────
@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        try:
            file_path = os.path.join(UPLOAD_DIR, f.filename)
            with open(file_path, "wb") as out_f:
                shutil.copyfileobj(f.file, out_f)

            ext = os.path.splitext(f.filename)[1].lower()

            # ファイル形式判定
            try:
                mime = magic.Magic(mime=True)
                file_info = mime.from_file(file_path)
            except:
                file_info = "形式判定不可"

            # 文字列抽出
            strings_out = extract_strings(file_path, ext)

            # 圧縮展開
            extracted_files = []
            temp_extract_dir = os.path.join(UPLOAD_DIR, f"{f.filename}_extracted")
            os.makedirs(temp_extract_dir, exist_ok=True)
            try:
                if ext in [".tar", ".tar.gz", ".tgz"]:
                    safe_extract_tar(file_path, temp_extract_dir)
                elif ext == ".zip":
                    safe_extract_zip(file_path, temp_extract_dir)
                extracted_files = os.listdir(temp_extract_dir)
            except Exception as e:
                extracted_files = [str(e)]

            results.append({
                "filename": f.filename,
                "file_info": file_info,
                "strings_preview": strings_out,
                "extracted_files": extracted_files
            })

        except Exception as e:
            results.append({
                "filename": f.filename,
                "error": str(e)
            })

    return JSONResponse(results)

# ─────────────── ダウンロード ───────────────
@app.get("/download/{filename}")
def download_file(filename: str):
    folder_path = os.path.join(UPLOAD_DIR, f"{filename}_extracted")
    if not os.path.exists(folder_path):
        return {"error": "ファイルが存在しません"}
    
    zip_path = os.path.join(UPLOAD_DIR, f"{filename}_extracted.zip")
    zip_dir(folder_path, zip_path)
    return FileResponse(zip_path, media_type="application/zip", filename=f"{filename}_extracted.zip")
