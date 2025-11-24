# main.py — FINAL — 100% WORKING LOGIN + DASHBOARD
import os
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# SIMPLE AUTH — WORKS 100%
@app.get("/")
def root():
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == "admin" and password == "1234":
        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("auth", "valid")
        return resp
    return templates.TemplateResponse("login.html", {"request": request, "error": "Wrong login"}, status_code=400)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if request.cookies.get("auth") != "valid":
        return RedirectResponse("/login")
    return templates.TemplateResponse("dashboard.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))