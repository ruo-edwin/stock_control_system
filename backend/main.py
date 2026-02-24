from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from backend.db import engine, Base
import backend.models  # Ensure models are imported
from routers import auth, product, sales, superadmin, push, onboarding, inventory
from backend.auth_utils import SECRET_KEY, ALGORITHM
from jose import jwt, JWTError
from fastapi.staticfiles import StaticFiles

app = FastAPI()
# ✅ Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
# ✅ HTTPS redirect middleware
@app.middleware("http")
async def enforce_https(request: Request, call_next):
    proto = request.headers.get("x-forwarded-proto", "http")
    if proto == "http":
        https_url = request.url.replace(scheme="https")
        return RedirectResponse(url=str(https_url))
    return await call_next(request)

# ✅ JWT auth middleware
@app.middleware("http")
async def redirect_or_json_on_unauthorized(request: Request, call_next):
    public_paths = [
        "/auth/login", "/auth/login_form", "/auth/register", "/static", "/favicon.ico","/superadmin/create_superadmin",   "/docs",
    "/openapi.json",
    "/redoc",
    "/swagger-ui",
    "/swagger-ui-init.js",
    "/swagger-ui-bundle.js",
    "/swagger-ui.css",
    "/docs/oauth2-redirect"
    ]
    if any(request.url.path.startswith(p) for p in public_paths):
        return await call_next(request)

    token = request.cookies.get("access_token")
    if not token:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        return RedirectResponse(url="/auth/login")

    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})
        return RedirectResponse(url="/auth/login")

    return await call_next(request)

# ✅ Create database tables
backend.models.Base.metadata.create_all(bind=engine)
print("✅ Tables that will be created:", Base.metadata.tables.keys())

# ✅ Static files
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="backend/static"), name="static")

# ✅ CORS
origins = [
    "https://pos-10-production.up.railway.app",
    "http://localhost:3000"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Routers
app.include_router(auth.router)
app.include_router(product.router)
app.include_router(sales.router)
app.include_router(superadmin.router)
app.include_router(push.router)
app.include_router(onboarding.router)
app.include_router(inventory.router)
@app.get("/")
def root():
    return {"message": "✅ SmartPOS API is running"}
from fastapi.responses import FileResponse

@app.get("/service-worker.js")
def sw():
    return FileResponse(
        "static/service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"}  # allow scope for whole site
    )
