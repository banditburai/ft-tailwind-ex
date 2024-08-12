from fasthtml.fastapp import *
from fasthtml.common import Script
from fasthtml.svg import *
import httpx
from starlette.responses import StreamingResponse, PlainTextResponse, FileResponse
from starlette.requests import Request
from starlette.datastructures import UploadFile
import asyncio
import random
import uuid
import os
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError

load_dotenv()

fouc_script="""
 if (localStorage.theme === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }"""

tailwindLink = Link(rel="stylesheet", href="styles/output.css", type="text/css")
app = FastHTML(hdrs=[Script(fouc_script), tailwindLink])

@app.route("/styles/{file_name:path}", methods=["GET"])
async def serve_static(file_name: str):
    return FileResponse(f"styles/{file_name}")

BACKEND_URL = os.getenv("BACKEND_URL")
ACCOUNT_ID = os.getenv("account_id")
ACCESS_KEY_ID = os.getenv("access_key_id")
ACCESS_KEY_SECRET = os.getenv("access_key_secret")
BUCKET_NAME= os.getenv("bucket_name")

r2 = boto3.client('s3',
    endpoint_url=f'https://{ACCOUNT_ID}.r2.cloudflarestorage.com',
    aws_access_key_id=ACCESS_KEY_ID,
    aws_secret_access_key=ACCESS_KEY_SECRET
)

def upload_file(file_name, bucket_name, object_name=None):
    if object_name is None:
        object_name = file_name
 
    try:
        r2.upload_file(file_name, bucket_name, object_name)
    except ClientError as e:
        print(f"An error occurred: {e}")
        return False
    return True

@app.route("/")
def get():
    preview_script = """
    document.addEventListener('DOMContentLoaded', function() {
    var dropzone = document.querySelector('div.border-dashed');
    var fileInput = document.getElementById('image');
    var preview = document.getElementById('preview');

    dropzone.onclick = function() {
        fileInput.click();
    };

    dropzone.ondragover = function(e) {
        e.preventDefault();
        this.classList.add('border-blue-500');
    };

    dropzone.ondragleave = function() {
        this.classList.remove('border-blue-500');
    };

    dropzone.ondrop = function(e) {
        e.preventDefault();
        this.classList.remove('border-blue-500');
        fileInput.files = e.dataTransfer.files;
        updatePreview(e.dataTransfer.files[0]);
    };

    fileInput.onchange = function() {
        updatePreview(this.files[0]);
    };

    function updatePreview(file) {
        if (file) {
            preview.src = URL.createObjectURL(file);
            preview.style.display = 'block';
        } else {
            preview.src = '#';
            preview.style.display = 'none';
        }
    }
    });"""

    dark_mode_toggle_script = """   
    function toggleDarkMode() {
        if (document.documentElement.classList.contains('dark')) {
            document.documentElement.classList.remove('dark');
            localStorage.theme = 'light';
        } else {
            document.documentElement.classList.add('dark');
            localStorage.theme = 'dark';
        }
    }
    """
    return Div(
        Main(
            Div(                
                Button(
                    Img(src='styles/moon.svg', cls="w-6 h-6 dark:hidden"),
                    Img(src='styles/sun.svg', cls="w-6 h-6 hidden dark:block"),
                    onclick="toggleDarkMode()",
                    cls="fixed top-4 right-4 bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-white p-2 rounded-full shadow-md"),
                H1("Gather round and speak to the oracle", cls="text-3xl sm:text-4xl font-bold text-center mb-6 text-gray-800 dark:text-white"),
                Form(
                    Label("Upload an image:", For="image", cls="block mb-2 font-semibold text-gray-700 dark:text-gray-300"),
                    Input(type="file", name="image", id="image", accept="image/*", required=True, cls="hidden"),
                    Div(P("Select your image", cls="text-gray-500 dark:text-gray-400"),
                        cls="w-full h-32 border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg flex items-center justify-center cursor-pointer"
                    ),
                    Img(id="preview", cls="max-w-full mx-auto my-4 hidden"),
                    Label("Enter your prompt:", For="prompt", cls="block mb-2 font-semibold text-gray-700 dark:text-gray-300"),
                    Input(type="text", name="prompt", id="prompt", placeholder="What would you like to know?", required=True, cls="w-full p-2 border rounded dark:bg-gray-700 dark:text-white"),
                    Button("Submit", type="submit", hx_target="#result", hx_indicator="#loading", cls="w-full bg-blue-500 text-white py-2 px-4 rounded hover:bg-blue-600 transition duration-300 mt-4"),
                    cls="max-w-md w-full mx-auto bg-white dark:bg-gray-800 p-6 rounded-lg shadow-md space-y-4",
                    hx_post="/process"
                ),
                Div(id="loading", cls="htmx-indicator hidden"),
                P("Loading...", cls="htmx-indicator text-center text-gray-600 dark:text-gray-400"),
                Div(id="result", cls="mt-4 text-gray-800 dark:text-white"),
                cls="container mx-auto px-4 py-8"
            ),
            cls="transition-colors duration-300"
        ),
        Script(preview_script),
        Script(dark_mode_toggle_script)
    )

async def stream_response(response):
    async for chunk in response.aiter_text():
        yield chunk

@app.route("/process", methods=['POST'])
async def post(request: Request):
    form = await request.form()
    image = form["image"]
    prompt = form.get("prompt")

    if not image or not isinstance(image, UploadFile):
        return PlainTextResponse("No image file uploaded.", status_code=400)

    if not image.content_type.startswith('image/'):
        return PlainTextResponse("File uploaded is not an image.", status_code=400)

    if not prompt:
        return PlainTextResponse("No prompt provided.", status_code=400)

    # Generate a random UUID for the filename
    file_extension = os.path.splitext(image.filename)[1]
    random_filename = f"{uuid.uuid4()}{file_extension}"

    # Upload directly to R2
    r2_object_name = f"uploads/{random_filename}"
    try:
        r2.upload_fileobj(image.file, BUCKET_NAME, r2_object_name)
        print(f"File {random_filename} uploaded successfully to {BUCKET_NAME}")
        r2_path = f"s3://{BUCKET_NAME}/{r2_object_name}"
    except ClientError as e:
        print(f"An error occurred: {e}")
        return PlainTextResponse("File upload to R2 failed", status_code=500)
    
    try:
        async with httpx.AsyncClient() as client:
            data = {
                "image": r2_path,
                "prompt": prompt,
                "top_p": 1.0,
                "temperature": 0.2,
                "max_tokens": 1024
            }
            response = await client.post(BACKEND_URL, json=data)
            response.raise_for_status()

        return StreamingResponse(stream_response(response))
    except httpx.HTTPError as e:
        return PlainTextResponse(f"Error communicating with backend: {str(e)}", status_code=500)
    except Exception as e:
        return PlainTextResponse(f"An unexpected error occurred: {str(e)}", status_code=500)
    
@app.route("/process", methods=['GET'])
def get():
    return PlainTextResponse("Shake out your pockets", status_code=405)

async def stream_response(response):
    try:
        async for chunk in response.aiter_text():
            yield chunk
    except Exception as e:
        print(f"Error in stream_response: {str(e)}")
        yield f"Error: {str(e)}"

if __name__ == "__main__":
    serve()