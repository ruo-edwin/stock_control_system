from fastapi import APIRouter, Depends, HTTPException, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend import models
from backend.db import SessionLocal
from backend.auth_utils import verify_token
from fastapi.responses import HTMLResponse, JSONResponse
from backend.config import templates
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/inventory", tags=["inventory"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =============================
# PRODUCT STOCK
# =============================
@router.get("/product_stock/{product_id}")
def get_product_stock(
    product_id: int,
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    query = db.query(
        func.coalesce(func.sum(models.StockMovement.quantity), 0)
    ).filter(
        models.StockMovement.product_id == product_id,
        models.StockMovement.business_id == current_user.business_id
    )

    # 🔥 Only restrict branch if NOT admin
    if current_user.role != "admin":
        query = query.filter(
            models.StockMovement.branch_id == current_user.branch_id
        )

    total_stock = query.scalar()

    return JSONResponse({"stock": total_stock})


@router.get("/add_product", response_class=HTMLResponse)
def add_product_page(
    request: Request,
    current_user: models.User = Depends(verify_token)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Access denied")

    return templates.TemplateResponse(
        "add_product.html",
        {"request": request}
    )
@router.get("/manage_branches", response_class=HTMLResponse)
def manage_branches(
    request: Request,
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):

    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    branches = db.query(models.Branch).filter(
        models.Branch.business_id == current_user.business_id
    ).all()

    return templates.TemplateResponse(
        "manage_branches.html",
        {
            "request": request,
            "branches": branches
        }
    )
# =============================
# INVENTORY OVERVIEW
# =============================
@router.get("/dashboard", response_class=HTMLResponse)
def inventory_overview(
    request: Request,
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    join_condition = (
        (models.StockMovement.product_id == models.Product.id) &
        (models.StockMovement.business_id == current_user.business_id)
    )

    # 🔥 Restrict branch only if NOT admin
    if current_user.role != "admin":
        join_condition = join_condition & (
            models.StockMovement.branch_id == current_user.branch_id
        )

    stock_data = db.query(
        models.Product.id,
        models.Product.name,
        func.coalesce(func.sum(models.StockMovement.quantity), 0).label("stock")
    ).outerjoin(
        models.StockMovement,
        join_condition
    ).filter(
        models.Product.business_id == current_user.business_id
    ).group_by(
        models.Product.id
    ).all()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stock_data": stock_data
        }
    )


# =============================
# ASSIGN PAGE
# =============================
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

    # 🔥 Staff restricted only for non-admin
    staff_query = db.query(models.Staff).filter(
        models.Staff.business_id == current_user.business_id
    )

    if current_user.role != "admin":
        staff_query = staff_query.filter(
            models.Staff.branch_id == current_user.branch_id
        )

    staff_list = staff_query.all()

    movements_query = db.query(models.StockMovement).filter(
        models.StockMovement.business_id == current_user.business_id,
        models.StockMovement.movement_type == "ISSUE"
    )

    if current_user.role != "admin":
        movements_query = movements_query.filter(
            models.StockMovement.branch_id == current_user.branch_id
        )

    movements = movements_query.order_by(
        models.StockMovement.created_at.desc()
    ).limit(10).all()

    return templates.TemplateResponse(
        "assign_stock.html",
        {
            "request": request,
            "products": products,
            "staff_list": staff_list,
            "movements": movements
        }
    )


# =============================
# RESTOCK PAGE
# =============================
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

    branches = db.query(models.Branch).filter(
        models.Branch.business_id == current_user.business_id
    ).all()

    movements_query = db.query(models.StockMovement).filter(
        models.StockMovement.business_id == current_user.business_id,
        models.StockMovement.movement_type == "IN"
    )

    if current_user.role != "admin":
        movements_query = movements_query.filter(
            models.StockMovement.branch_id == current_user.branch_id
        )

    movements = movements_query.order_by(
        models.StockMovement.created_at.desc()
    ).limit(10).all()

    return templates.TemplateResponse(
        "restock.html",
        {
            "request": request,
            "products": products,
            "movements": movements,
            "branches": branches,
            "current_user": current_user
        }
    )
# =============================
# ASSIGN STOCK
# =============================
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

    staff_query = db.query(models.Staff).filter(
        models.Staff.id == staff_id,
        models.Staff.business_id == current_user.business_id
    )

    if current_user.role != "admin":
        staff_query = staff_query.filter(
            models.Staff.branch_id == current_user.branch_id
        )

    staff = staff_query.first()

    if not staff:
        raise HTTPException(status_code=400, detail="Invalid staff")

    product = db.query(models.Product).filter(
        models.Product.id == product_id,
        models.Product.business_id == current_user.business_id
    ).first()

    if not product:
        raise HTTPException(status_code=400, detail="Invalid product")

    stock_query = db.query(
        func.coalesce(func.sum(models.StockMovement.quantity), 0)
    ).filter(
        models.StockMovement.product_id == product_id,
        models.StockMovement.business_id == current_user.business_id
    )

    if current_user.role != "admin":
        stock_query = stock_query.filter(
            models.StockMovement.branch_id == current_user.branch_id
        )

    current_stock = stock_query.scalar()

    if current_stock < quantity:
        raise HTTPException(status_code=400, detail="Not enough stock")

    movement = models.StockMovement(
        business_id=current_user.business_id,
        branch_id=staff.branch_id,  # 🔥 movement goes to staff branch
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


# ===========================
# RESTOCK
# =============================
@router.post("/restock")
def restock_product(
    product_id: int = Form(...),
    quantity: int = Form(...),
    branch_id: int = Form(None),  # 🔥 Needed for admin
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

    # 🔥 Determine correct branch
    if current_user.role == "manager":
        branch_id_to_use = current_user.branch_id
    else:
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch is required")
        branch_id_to_use = branch_id

    movement = models.StockMovement(
        business_id=current_user.business_id,
        branch_id=branch_id_to_use,
        product_id=product_id,
        movement_type="IN",
        quantity=quantity,
        notes=f"Supplier: {supplier or ''} | Invoice: {invoice_number or ''} | {notes or ''}",
        created_by=current_user.id
    )

    db.add(movement)
    db.commit()

    return {"message": "Stock added successfully"}
@router.post("/create_branch")
def create_branch(
    name: str = Form(...),
    location: str = Form(None),
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):

    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    new_branch = models.Branch(
        business_id=current_user.business_id,
        name=name,
        location=location
    )

    db.add(new_branch)
    db.commit()

    return RedirectResponse("/inventory/manage_branches", status_code=303)

@router.post("/create_product")
def create_product(
    name: str = Form(...),
    buying_price: float = Form(0),
    min_stock: int = Form(5),
    current_user: models.User = Depends(verify_token),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Access denied")

    new_product = models.Product(
        business_id=current_user.business_id,
        name=name,
        buying_price=buying_price,
        min_stock=min_stock
    )

    db.add(new_product)
    db.commit()

    return RedirectResponse("/product/list", status_code=303)