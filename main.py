from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
import os, shutil, tarfile, zipfile, subprocess, tempfile

app = FastAPI()

UPLOAD_DIR = tempfile.mkdtemp()

def safe_extract_tar(tar_path, extract_path):
    with tarfile.open(tar_path) as tar:
        for member in tar.getmembers():
            member_path = os.path.join(extract_path, member.name)
            if not os.path.commonprefix([extract_path, member_path]) == extract_path:
                continue  # Zip Slip 対策
        tar.extractall(extract_path)

def safe_extract_zip(zip_path, extract_path):
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for member in zip_ref.namelist():
            member_path = os.path.join(extract_path, member)
            if not os.path.commonprefix([extract_path, member_path]) == extract_path:
                continue
        zip_ref.extractall(extract_path)

@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", "r") as f:
        return f.read()

@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        file_path = os.path.join(UPLOAD_DIR, f.filename)
        with open(file_path, "wb") as out_f:
            shutil.copyfileobj(f.file, out_f)

        # ファイル形式確認
        try:
            file_info = subprocess.check_output(["file", file_path]).decode().strip()
        except:
            file_info = "形式確認不可"

        # 文字列抽出
        try:
            strings_out = subprocess.check_output(["strings", file_path]).decode(errors='ignore')
        except:
            strings_out = "文字列抽出不可"

        # 圧縮ファイル展開
        extracted_files = []
        temp_extract_dir = os.path.join(UPLOAD_DIR, f"{f.filename}_extracted")
        os.makedirs(temp_extract_dir, exist_ok=True)
        try:
            if f.filename.endswith((".tar.gz", ".tar")):
                safe_extract_tar(file_path, temp_extract_dir)
            elif f.filename.endswith(".zip"):
                safe_extract_zip(file_path, temp_extract_dir)
            extracted_files = os.listdir(temp_extract_dir)
        except:
            pass

        results.append({
            "filename": f.filename,
            "file_info": file_info,
            "strings_preview": strings_out[:1000],  # 最初の1000文字
            "extracted_files": extracted_files
        })
    return JSONResponse(results)
