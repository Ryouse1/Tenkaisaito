from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
import os
import zipfile, tarfile, shutil, subprocess

app = FastAPI()

# 保存用ディレクトリ
UPLOAD_DIR = "uploads"
EXTRACT_DIR = "extracted"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(EXTRACT_DIR, exist_ok=True)


# --- HTML (ローディングバー付き) ---
@app.get("/")
def index():
    return HTMLResponse("""
    <html>
    <head>
        <title>ファイル展開 & ウイルススキャン</title>
        <style>
            body { font-family: sans-serif; margin: 20px; }
            .progress { width: 100%; background: #eee; margin-top: 10px; }
            .bar { width: 0%; height: 20px; background: green; text-align: center; color: white; }
            #status { margin-top: 15px; white-space: pre-wrap; }
        </style>
    </head>
    <body>
        <h2>ファイルをアップロードして展開＆ウイルスチェック</h2>
        <form id="uploadForm" enctype="multipart/form-data">
            <input type="file" name="file" required>
            <input type="submit" value="アップロード">
        </form>
        <div class="progress"><div class="bar" id="bar">0%</div></div>
        <pre id="status"></pre>
        <script>
            const form = document.getElementById("uploadForm");
            form.onsubmit = async (e) => {
                e.preventDefault();
                const formData = new FormData(form);
                const xhr = new XMLHttpRequest();
                xhr.open("POST", "/upload");
                xhr.upload.onprogress = (event) => {
                    if (event.lengthComputable) {
                        let percent = (event.loaded / event.total) * 100;
                        document.getElementById("bar").style.width = percent + "%";
                        document.getElementById("bar").innerText = Math.floor(percent) + "%";
                    }
                };
                xhr.onload = () => document.getElementById("status").innerText = xhr.responseText;
                xhr.send(formData);
            };
        </script>
    </body>
    </html>
    """)


# --- ファイルアップロード & 展開 ---
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # 保存
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # 展開ディレクトリ作成
    extract_path = os.path.join(EXTRACT_DIR, os.path.splitext(file.filename)[0])
    os.makedirs(extract_path, exist_ok=True)

    # 展開処理
    try:
        if zipfile.is_zipfile(file_path):
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                zip_ref.extractall(extract_path)
        elif tarfile.is_tarfile(file_path):
            with tarfile.open(file_path, "r:*") as tar_ref:
                tar_ref.extractall(extract_path)
        else:
            shutil.copy(file_path, extract_path)  # 非アーカイブはそのまま保存
    except Exception as e:
        return JSONResponse({"error": f"展開エラー: {str(e)}"})

    # --- ウイルススキャン (ClamAV必須) ---
    result = subprocess.run(["clamscan", "-r", extract_path], capture_output=True, text=True)
    infected = "Infected files: 0" not in result.stdout

    if infected:
        shutil.rmtree(extract_path, ignore_errors=True)
        return JSONResponse({"error": "⚠️ ウイルスが検知されました。ファイルは削除されました。"})

    return JSONResponse({
        "message": "✅ ファイルを展開し、ウイルスチェック完了。安全です。",
        "download_url": f"/download/{os.path.basename(extract_path)}"
    })


# --- ダウンロード処理 ---
@app.get("/download/{folder}")
def download_files(folder: str):
    folder_path = os.path.join(EXTRACT_DIR, folder)
    if not os.path.exists(folder_path):
        return JSONResponse({"error": "ファイルが存在しません"})
    zip_path = f"{folder_path}.zip"
    shutil.make_archive(folder_path, 'zip', folder_path)
    return FileResponse(zip_path, filename=f"{folder}.zip")
