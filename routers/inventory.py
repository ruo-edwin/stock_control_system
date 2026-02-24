from fastapi import APIRouter, Depends, HTTPException, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend import models
from backend.db import SessionLocal
from backend.auth_utils import verify_token
from fastapi.responses import HTMLResponse, JSONResponse
from backend.config import templates


router = APIRouter(prefix="/inventory", tags=["inventory"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/product_stock/{product_id}")
def get_product_stock(
    product_id: int,
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    total_stock = db.query(
        func.coalesce(func.sum(models.StockMovement.quantity), 0)
    ).filter(
        models.StockMovement.product_id == product_id,
        models.StockMovement.branch_id == current_user.branch_id,
        models.StockMovement.business_id == current_user.business_id
    ).scalar()

    return JSONResponse({"stock": total_stock})


@router.get("/overview", response_class=HTMLResponse)
def inventory_overview(
    request: Request,
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    stock_data = db.query(
        models.Product.id,
        models.Product.name,
        func.coalesce(func.sum(models.StockMovement.quantity), 0).label("stock")
    ).outerjoin(
        models.StockMovement,
        (models.StockMovement.product_id == models.Product.id) &
        (models.StockMovement.branch_id == current_user.branch_id) &
        (models.StockMovement.business_id == current_user.business_id)
    ).filter(
        models.Product.business_id == current_user.business_id
    ).group_by(
        models.Product.id
    ).all()

    return templates.TemplateResponse(
        "inventory_overview.html",
        {
            "request": request,
            "stock_data": stock_data
        }
    )


@router.get("/assign", response_class=HTMLResponse)
def assign_page(
    request: Request,
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "storekeeper"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    products = db.query(models.Product).filter(
        models.Product.business_id == current_user.business_id
    ).all()

    staff_list = db.query(models.Staff).filter(
        models.Staff.branch_id == current_user.branch_id,
        models.Staff.business_id == current_user.business_id
    ).all()

    movements = db.query(models.StockMovement).filter(
        models.StockMovement.branch_id == current_user.branch_id,
        models.StockMovement.business_id == current_user.business_id,
        models.StockMovement.movement_type == "ISSUE"
    ).order_by(models.StockMovement.created_at.desc()).limit(10).all()

    return templates.TemplateResponse(
        "assign_stock.html",
        {
            "request": request,
            "products": products,
            "staff_list": staff_list,
            "movements": movements
        }
    )


@router.get("/restock", response_class=HTMLResponse)
def restock_page(
    request: Request,
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    products = db.query(models.Product).filter(
        models.Product.business_id == current_user.business_id
    ).all()

    movements = db.query(models.StockMovement).filter(
        models.StockMovement.branch_id == current_user.branch_id,
        models.StockMovement.business_id == current_user.business_id,
        models.StockMovement.movement_type == "IN"
    ).order_by(models.StockMovement.created_at.desc()).limit(10).all()

    return templates.TemplateResponse(
        "restock.html",
        {
            "request": request,
            "products": products,
            "movements": movements
        }
    )


@router.post("/assign_stock")
def assign_stock(
    product_id: int = Form(...),
    staff_id: int = Form(...),
    quantity: int = Form(...),
    notes: str = Form(None),
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "storekeeper"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")

    staff = db.query(models.Staff).filter(
        models.Staff.id == staff_id,
        models.Staff.branch_id == current_user.branch_id,
        models.Staff.business_id == current_user.business_id
    ).first()

    if not staff:
        raise HTTPException(status_code=400, detail="Invalid staff")

    product = db.query(models.Product).filter(
        models.Product.id == product_id,
        models.Product.business_id == current_user.business_id
    ).first()

    if not product:
        raise HTTPException(status_code=400, detail="Invalid product")

    current_stock = db.query(
        func.coalesce(func.sum(models.StockMovement.quantity), 0)
    ).filter(
        models.StockMovement.product_id == product_id,
        models.StockMovement.branch_id == current_user.branch_id,
        models.StockMovement.business_id == current_user.business_id
    ).scalar()

    if current_stock < quantity:
        raise HTTPException(status_code=400, detail="Not enough stock")

    movement = models.StockMovement(
        business_id=current_user.business_id,
        branch_id=current_user.branch_id,
        product_id=product_id,
        movement_type="ISSUE",
        quantity=-quantity,
        staff_id=staff_id,
        notes=notes,
        created_by=current_user.id
    )

    db.add(movement)
    db.commit()

    return {"message": "Stock assigned successfully"}


@router.post("/restock")
def restock_product(
    product_id: int = Form(...),
    quantity: int = Form(...),
    supplier: str = Form(None),
    invoice_number: str = Form(None),
    notes: str = Form(None),
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")

    product = db.query(models.Product).filter(
        models.Product.id == product_id,
        models.Product.business_id == current_user.business_id
    ).first()

    if not product:
        raise HTTPException(status_code=400, detail="Invalid product")

    movement = models.StockMovement(
        business_id=current_user.business_id,
        branch_id=current_user.branch_id,
        product_id=product_id,
        movement_type="IN",
        quantity=quantity,
        notes=f"Supplier: {supplier or ''} | Invoice: {invoice_number or ''} | {notes or ''}",
        created_by=current_user.id
    )

    db.add(movement)
    db.commit()

    return {"message": "Stock added successfully"}