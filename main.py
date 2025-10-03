from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
import os, shutil, tarfile, zipfile, tempfile
import magic

app = FastAPI()
UPLOAD_DIR = tempfile.mkdtemp()

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

@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", "r") as f:
        return f.read()

@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        try:
            file_path = os.path.join(UPLOAD_DIR, f.filename)
            with open(file_path, "wb") as out_f:
                shutil.copyfileobj(f.file, out_f)

            # ファイル形式判定
            try:
                mime = magic.Magic(mime=True)
                file_info = mime.from_file(file_path)
            except:
                file_info = "形式判定不可"

            # 文字列抽出（バイナリ安全）
            try:
                with open(file_path, "rb") as bf:
                    content = bf.read()
                strings_out = ''.join([chr(b) if 32 <= b < 127 else '.' for b in content])
            except:
                strings_out = "文字列抽出不可"

            # 圧縮展開
            extracted_files = []
            temp_extract_dir = os.path.join(UPLOAD_DIR, f"{f.filename}_extracted")
            os.makedirs(temp_extract_dir, exist_ok=True)
            try:
                if f.filename.endswith((".tar.gz", ".tar")):
                    safe_extract_tar(file_path, temp_extract_dir)
                elif f.filename.endswith(".zip"):
                    safe_extract_zip(file_path, temp_extract_dir)
                extracted_files = os.listdir(temp_extract_dir)
            except Exception as e:
                extracted_files = [str(e)]

            results.append({
                "filename": f.filename,
                "file_info": file_info,
                "strings_preview": strings_out[:1000],
                "extracted_files": extracted_files
            })

        except Exception as e:
            results.append({
                "filename": f.filename,
                "error": str(e)
            })

    return JSONResponse(results)
