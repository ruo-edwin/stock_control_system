```python
from fastapi import APIRouter, Depends, HTTPException, Form, Body, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend import models
from backend.config import templates
from backend.auth_utils import get_current_user
from backend.onboarding_utils import record_onboarding_event


# ---------------- CONFIG ----------------

BASE_URL = "https://pos-10-production.up.railway.app"

router = APIRouter(
    prefix="/products",
    tags=["products"]
)


# ---------------- DB DEPENDENCY ----------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------- ROLE CHECK ----------------

def require_admin_or_manager(
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Access denied"
        )

    return current_user


# ---------------- HTML ROUTES ----------------

@router.get("/addproduct", response_class=HTMLResponse)
async def add_product_page(
    request: Request,
    current_user: models.User = Depends(require_admin_or_manager)
):
    source = request.query_params.get("source")

    return templates.TemplateResponse(
        "add_product.html",
        {
            "request": request,
            "source": source
        }
    )


@router.get("/viewstocks", response_class=HTMLResponse)
async def view_stocks_page(
    request: Request,
    current_user: models.User = Depends(require_admin_or_manager),
    db: Session = Depends(get_db)
):
    return templates.TemplateResponse(
        "view_stock.html",
        {
            "request": request
        }
    )


# ---------------- ADD PRODUCT ----------------

@router.post("/add_product")
def add_product(
    request: Request,
    name: str = Form(...),
    price: float = Form(...),
    buying_price: float = Form(...),
    quantity: int = Form(...),
    current_user: models.User = Depends(require_admin_or_manager),
    db: Session = Depends(get_db)
):
    try:
        new_product = models.Product(
            name=name,
            price=price,
            buying_price=buying_price,
            quantity=quantity,
            business_id=current_user.business_id
        )

        db.add(new_product)
        db.commit()
        db.refresh(new_product)

        record_onboarding_event(
            db,
            current_user.business_id,
            "add_product"
        )

        source = request.query_params.get("source")

        if source == "onboarding":
            return RedirectResponse(
                url=f"{BASE_URL}/sales/recordsale?source=onboarding",
                status_code=303
            )

        return {
            "message": f"✅ Product '{name}' added successfully!",
            "product": new_product.id
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )


# ---------------- GET ALL PRODUCTS ----------------

@router.get("/")
def get_products(
    current_user: models.User = Depends(require_admin_or_manager),
    db: Session = Depends(get_db)
):
    products = db.query(models.Product).filter(
        models.Product.business_id == current_user.business_id
    ).all()

    return products


# ---------------- UPDATE STOCK ----------------

@router.put("/update_stock/{product_id}")
def update_stock(
    product_id: int,
    data: dict = Body(...),
    current_user: models.User = Depends(require_admin_or_manager),
    db: Session = Depends(get_db)
):
    product = db.query(models.Product).filter(
        models.Product.id == product_id,
        models.Product.business_id == current_user.business_id
    ).first()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    product.quantity = data.get(
        "quantity",
        product.quantity
    )

    product.price = data.get(
        "price",
        product.price
    )

    product.buying_price = data.get(
        "buying_price",
        product.buying_price
    )

    db.commit()
    db.refresh(product)

    return {
        "message": "✅ Product updated successfully",
        "product": product.name
    }
```
