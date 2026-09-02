from fastapi import APIRouter, Depends, HTTPException, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend import models
from backend.db import SessionLocal
from backend.auth_utils import get_current_user
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from backend.config import templates


router = APIRouter(
    prefix="/inventory",
    tags=["inventory"]
)


# ====================================================
# DB DEPENDENCY
# ====================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ====================================================
# PRODUCT STOCK
# BRANCH AWARE
#
# Authenticated users can check stock.
# The requested branch MUST belong to their business.
# ====================================================

@router.get("/product_stock/{product_id}/{branch_id}")
def get_product_stock(
    product_id: int,
    branch_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    # ------------------------------------------------
    # Make sure branch belongs to current user's business
    # ------------------------------------------------

    branch = (
        db.query(models.Branch)
        .filter(
            models.Branch.id == branch_id,
            models.Branch.business_id == current_user.business_id
        )
        .first()
    )

    if not branch:
        return JSONResponse({"stock": 0})

    # ------------------------------------------------
    # Managers/storekeepers should only see their branch
    # ------------------------------------------------

    if current_user.role in ["manager", "storekeeper"]:

        if current_user.branch_id != branch_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have access to this branch"
            )

    total_stock = (
        db.query(
            func.coalesce(
                func.sum(models.StockMovement.quantity),
                0
            )
        )
        .filter(
            models.StockMovement.product_id == product_id,
            models.StockMovement.business_id == current_user.business_id,
            models.StockMovement.branch_id == branch_id
        )
        .scalar()
    )

    return JSONResponse({
        "stock": int(total_stock or 0)
    })


# ====================================================
# PRODUCTS PAGE
# MULTI-BRANCH VIEW
#
# Admin:
#   sees all branches
#
# Manager:
#   sees own branch only
#
# Storekeeper:
#   denied
# ====================================================

@router.get(
    "/products",
    response_class=HTMLResponse
)
def products_page(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Not authorized"
        )

    # ------------------------------------------------
    # Get branches
    # ------------------------------------------------

    if current_user.role == "admin":

        branches = (
            db.query(models.Branch)
            .filter(
                models.Branch.business_id == current_user.business_id
            )
            .all()
        )

    else:

        branches = (
            db.query(models.Branch)
            .filter(
                models.Branch.business_id == current_user.business_id,
                models.Branch.id == current_user.branch_id
            )
            .all()
        )

    # ------------------------------------------------
    # Get all products for this business
    # ------------------------------------------------

    products = (
        db.query(models.Product)
        .filter(
            models.Product.business_id == current_user.business_id
        )
        .all()
    )

    # ------------------------------------------------
    # Get stock grouped by product + branch
    # ------------------------------------------------

    stock_rows = (
        db.query(
            models.StockMovement.product_id,
            models.StockMovement.branch_id,
            func.coalesce(
                func.sum(models.StockMovement.quantity),
                0
            ).label("quantity")
        )
        .filter(
            models.StockMovement.business_id == current_user.business_id
        )
    )

    if current_user.role != "admin":
        stock_rows = stock_rows.filter(
            models.StockMovement.branch_id == current_user.branch_id
        )

    stock_rows = (
        stock_rows
        .group_by(
            models.StockMovement.product_id,
            models.StockMovement.branch_id
        )
        .all()
    )

    # ------------------------------------------------
    # Convert stock rows to dictionary
    # ------------------------------------------------

    stock_map = {}

    for row in stock_rows:

        stock_map.setdefault(
            row.product_id,
            {}
        )

        stock_map[row.product_id][row.branch_id] = row.quantity

    # ------------------------------------------------
    # Structure data for template
    # ------------------------------------------------

    product_data = []

    for product in products:

        row = {
            "id": product.id,
            "name": product.name,
            "branches": {},
            "total": 0
        }

        for branch in branches:

            qty = (
                stock_map
                .get(product.id, {})
                .get(branch.id, 0)
            )

            row["branches"][branch.id] = qty
            row["total"] += qty

        product_data.append(row)

    return templates.TemplateResponse(
        "products.html",
        {
            "request": request,
            "products": product_data,
            "current_user": current_user,
            "branches": branches
        }
    )


# ====================================================
# ADD PRODUCT PAGE
# ADMIN + MANAGER
# ====================================================

@router.get(
    "/add_product",
    response_class=HTMLResponse
)
def add_product_page(
    request: Request,
    success: str | None = None,
    current_user: models.User = Depends(get_current_user)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Access denied"
        )

    return templates.TemplateResponse(
        "add_product.html",
        {
            "request": request,
            "success": success,
            "current_user": current_user
        }
    )


# ====================================================
# MANAGE BRANCHES
# ADMIN ONLY
# ====================================================

@router.get(
    "/manage_branches",
    response_class=HTMLResponse
)
def manage_branches(
    request: Request,
    success: str | None = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    if current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Access denied"
        )

    branches = (
        db.query(models.Branch)
        .filter(
            models.Branch.business_id == current_user.business_id
        )
        .all()
    )

    return templates.TemplateResponse(
        "manage_branches.html",
        {
            "request": request,
            "branches": branches,
            "current_user": current_user,
            "success": success
        }
    )


# ====================================================
# INVENTORY OVERVIEW
#
# Admin:
#   all branches
#
# Manager:
#   own branch
#
# Storekeeper:
#   denied
# ====================================================

@router.get(
    "/dashboard",
    response_class=HTMLResponse
)
def inventory_overview(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Not authorized"
        )

    # ------------------------------------------------
    # BRANCHES VISIBLE TO USER
    # ------------------------------------------------

    if current_user.role == "admin":

        branches = (
            db.query(models.Branch)
            .filter(
                models.Branch.business_id == current_user.business_id
            )
            .all()
        )

    else:

        branches = (
            db.query(models.Branch)
            .filter(
                models.Branch.business_id == current_user.business_id,
                models.Branch.id == current_user.branch_id
            )
            .all()
        )

    branch_ids = [
        branch.id
        for branch in branches
    ]

    # ------------------------------------------------
    # ALL PRODUCTS
    # ------------------------------------------------

    products = (
        db.query(models.Product)
        .filter(
            models.Product.business_id == current_user.business_id
        )
        .all()
    )

    total_products = len(products)

    # ------------------------------------------------
    # STOCK BY PRODUCT + BRANCH
    # ------------------------------------------------

    stock_rows = (
        db.query(
            models.StockMovement.product_id,
            models.StockMovement.branch_id,
            func.coalesce(
                func.sum(models.StockMovement.quantity),
                0
            ).label("stock")
        )
        .filter(
            models.StockMovement.business_id == current_user.business_id
        )
    )

    if current_user.role != "admin":

        stock_rows = stock_rows.filter(
            models.StockMovement.branch_id == current_user.branch_id
        )

    stock_rows = (
        stock_rows
        .group_by(
            models.StockMovement.product_id,
            models.StockMovement.branch_id
        )
        .all()
    )

    # ------------------------------------------------
    # STOCK MAP
    # ------------------------------------------------

    stock_map = {}

    for row in stock_rows:

        stock_map.setdefault(
            row.product_id,
            {}
        )

        stock_map[row.product_id][row.branch_id] = int(
            row.stock or 0
        )

    # ------------------------------------------------
    # TOTAL UNITS
    # ------------------------------------------------

    total_units = 0

    for product in products:

        for branch in branches:

            qty = (
                stock_map
                .get(product.id, {})
                .get(branch.id, 0)
            )

            if qty < 0:
                qty = 0

            total_units += qty

    # ------------------------------------------------
    # LOW STOCK / OUT OF STOCK
    # ------------------------------------------------

    low_stock_products = []
    out_of_stock_products = []

    for product in products:

        min_stock = int(
            getattr(product, "min_stock", 5) or 5
        )

        for branch in branches:

            qty = (
                stock_map
                .get(product.id, {})
                .get(branch.id, 0)
            )

            if qty < 0:
                qty = 0

            if qty == 0:

                out_of_stock_products.append({
                    "name": product.name,
                    "branch_name": branch.name,
                    "stock": 0
                })

            elif qty <= min_stock:

                low_stock_products.append({
                    "name": product.name,
                    "branch_name": branch.name,
                    "stock": qty
                })

    # ------------------------------------------------
    # RECENT MOVEMENTS
    # ------------------------------------------------

    recent_q = (
        db.query(
            models.StockMovement.created_at,
            models.StockMovement.movement_type,
            models.StockMovement.quantity,
            models.Product.name.label("product_name")
        )
        .join(
            models.Product,
            models.Product.id == models.StockMovement.product_id
        )
        .filter(
            models.StockMovement.business_id == current_user.business_id
        )
    )

    if current_user.role != "admin":

        recent_q = recent_q.filter(
            models.StockMovement.branch_id == current_user.branch_id
        )

    recent_movements = (
        recent_q
        .order_by(
            models.StockMovement.created_at.desc()
        )
        .limit(10)
        .all()
    )

    # ------------------------------------------------
    # BRANCH SUMMARY
    # ------------------------------------------------

    branches_summary = []

    if branches:

        branch_sums = (
            db.query(
                models.StockMovement.branch_id,
                func.coalesce(
                    func.sum(models.StockMovement.quantity),
                    0
                ).label("total_units")
            )
            .filter(
                models.StockMovement.business_id == current_user.business_id,
                models.StockMovement.branch_id.in_(branch_ids)
            )
            .group_by(
                models.StockMovement.branch_id
            )
            .all()
        )

        sums_map = {
            int(row.branch_id): int(
                row.total_units or 0
            )
            for row in branch_sums
        }

        for branch in branches:

            units = sums_map.get(
                branch.id,
                0
            )

            if units < 0:
                units = 0

            branches_summary.append({
                "name": branch.name,
                "total_units": units
            })

    # ------------------------------------------------
    # STOCK DATA
    # ------------------------------------------------

    stock_data = []

    for product in products:

        total = 0

        for branch in branches:

            qty = (
                stock_map
                .get(product.id, {})
                .get(branch.id, 0)
            )

            if qty < 0:
                qty = 0

            total += qty

        stock_data.append({
            "id": product.id,
            "name": product.name,
            "stock": total
        })

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "current_user": current_user,
            "total_products": total_products,
            "total_units": total_units,
            "low_stock_products": low_stock_products,
            "out_of_stock_products": out_of_stock_products,
            "recent_movements": recent_movements,
            "branches_summary": branches_summary,
            "stock_data": stock_data
        }
    )


# ====================================================
# ASSIGN PAGE
#
# Admin:
#   all branches
#
# Storekeeper:
#   own branch
#
# Manager:
#   denied
# ====================================================

@router.get(
    "/assign",
    response_class=HTMLResponse
)
def assign_page(
    request: Request,
    success: str | None = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "storekeeper"]:
        raise HTTPException(
            status_code=403,
            detail="Not authorized"
        )

    products = (
        db.query(models.Product)
        .filter(
            models.Product.business_id == current_user.business_id
        )
        .all()
    )

    # ------------------------------------------------
    # STAFF
    # ------------------------------------------------

    staff_query = (
        db.query(models.Staff)
        .filter(
            models.Staff.business_id == current_user.business_id
        )
    )

    if current_user.role != "admin":

        staff_query = staff_query.filter(
            models.Staff.branch_id == current_user.branch_id
        )

    staff_list = staff_query.all()

    # ------------------------------------------------
    # RECENT ISSUE MOVEMENTS
    # ------------------------------------------------

    movements_query = (
        db.query(models.StockMovement)
        .filter(
            models.StockMovement.business_id == current_user.business_id,
            models.StockMovement.movement_type == "ISSUE"
        )
    )

    if current_user.role != "admin":

        movements_query = movements_query.filter(
            models.StockMovement.branch_id == current_user.branch_id
        )

    movements = (
        movements_query
        .order_by(
            models.StockMovement.created_at.desc()
        )
        .limit(10)
        .all()
    )

    return templates.TemplateResponse(
        "assign_stock.html",
        {
            "request": request,
            "products": products,
            "staff_list": staff_list,
            "current_user": current_user,
            "movements": movements,
            "success": success
        }
    )


# ====================================================
# RESTOCK PAGE
#
# Admin:
#   all branches
#
# Manager:
#   own branch
#
# Storekeeper:
#   denied
# ====================================================

@router.get(
    "/restock",
    response_class=HTMLResponse
)
def restock_page(
    request: Request,
    success: str | None = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Not authorized"
        )

    products = (
        db.query(models.Product)
        .filter(
            models.Product.business_id == current_user.business_id
        )
        .all()
    )

    # ------------------------------------------------
    # BRANCHES
    # ------------------------------------------------

    if current_user.role == "admin":

        branches = (
            db.query(models.Branch)
            .filter(
                models.Branch.business_id == current_user.business_id
            )
            .all()
        )

    else:

        branches = (
            db.query(models.Branch)
            .filter(
                models.Branch.business_id == current_user.business_id,
                models.Branch.id == current_user.branch_id
            )
            .all()
        )

    # ------------------------------------------------
    # RECENT RESTOCK MOVEMENTS
    # ------------------------------------------------

    movements_query = (
        db.query(models.StockMovement)
        .filter(
            models.StockMovement.business_id == current_user.business_id,
            models.StockMovement.movement_type == "IN"
        )
    )

    if current_user.role != "admin":

        movements_query = movements_query.filter(
            models.StockMovement.branch_id == current_user.branch_id
        )

    movements = (
        movements_query
        .order_by(
            models.StockMovement.created_at.desc()
        )
        .limit(10)
        .all()
    )

    return templates.TemplateResponse(
        "restock.html",
        {
            "request": request,
            "products": products,
            "movements": movements,
            "branches": branches,
            "current_user": current_user,
            "success": success
        }
    )


# ====================================================
# ASSIGN STOCK
#
# Admin + Storekeeper
# ====================================================

@router.post("/assign_stock")
def assign_stock(
    product_id: int = Form(...),
    staff_id: int = Form(...),
    quantity: int = Form(...),
    notes: str = Form(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "storekeeper"]:
        raise HTTPException(
            status_code=403,
            detail="Not authorized"
        )

    if quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than zero"
        )

    # ------------------------------------------------
    # VALIDATE STAFF
    # ------------------------------------------------

    staff_query = (
        db.query(models.Staff)
        .filter(
            models.Staff.id == staff_id,
            models.Staff.business_id == current_user.business_id
        )
    )

    if current_user.role != "admin":

        staff_query = staff_query.filter(
            models.Staff.branch_id == current_user.branch_id
        )

    staff = staff_query.first()

    if not staff:
        raise HTTPException(
            status_code=400,
            detail="Invalid staff"
        )

    # ------------------------------------------------
    # VALIDATE PRODUCT
    # ------------------------------------------------

    product = (
        db.query(models.Product)
        .filter(
            models.Product.id == product_id,
            models.Product.business_id == current_user.business_id
        )
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=400,
            detail="Invalid product"
        )

    # ------------------------------------------------
    # CHECK STOCK
    # ------------------------------------------------

    stock_query = (
        db.query(
            func.coalesce(
                func.sum(models.StockMovement.quantity),
                0
            )
        )
        .filter(
            models.StockMovement.product_id == product_id,
            models.StockMovement.business_id == current_user.business_id
        )
    )

    if current_user.role != "admin":

        stock_query = stock_query.filter(
            models.StockMovement.branch_id == current_user.branch_id
        )

    current_stock = stock_query.scalar() or 0

    if current_stock < quantity:
        raise HTTPException(
            status_code=400,
            detail="Not enough stock"
        )

    # ------------------------------------------------
    # CREATE ISSUE MOVEMENT
    # ------------------------------------------------

    movement = models.StockMovement(
        business_id=current_user.business_id,
        branch_id=staff.branch_id,
        product_id=product_id,
        movement_type="ISSUE",
        quantity=-quantity,
        staff_id=staff_id,
        notes=notes,
        created_by=current_user.id
    )

    db.add(movement)
    db.commit()

    return RedirectResponse(
        "/inventory/assign?success=Stock assigned successfully",
        status_code=303
    )


# ====================================================
# RESTOCK
#
# Admin + Manager
# ====================================================

@router.post("/restock")
def restock_product(
    product_id: int = Form(...),
    quantity: int = Form(...),
    branch_id: int = Form(None),
    supplier: str = Form(None),
    invoice_number: str = Form(None),
    notes: str = Form(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Not authorized"
        )

    if quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than zero"
        )

    # ------------------------------------------------
    # VALIDATE PRODUCT
    # ------------------------------------------------

    product = (
        db.query(models.Product)
        .filter(
            models.Product.id == product_id,
            models.Product.business_id == current_user.business_id
        )
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=400,
            detail="Invalid product"
        )

    # ------------------------------------------------
    # SELECT BRANCH
    # ------------------------------------------------

    if current_user.role == "manager":

        if not current_user.branch_id:
            raise HTTPException(
                status_code=400,
                detail="Manager has no assigned branch"
            )

        branch_id_to_use = current_user.branch_id

    else:

        if not branch_id:
            raise HTTPException(
                status_code=400,
                detail="Branch is required"
            )

        # Admin can choose any branch, but it must belong
        # to their own business.

        branch = (
            db.query(models.Branch)
            .filter(
                models.Branch.id == branch_id,
                models.Branch.business_id == current_user.business_id
            )
            .first()
        )

        if not branch:
            raise HTTPException(
                status_code=400,
                detail="Invalid branch"
            )

        branch_id_to_use = branch_id

    # ------------------------------------------------
    # CREATE RESTOCK MOVEMENT
    # ------------------------------------------------

    movement = models.StockMovement(
        business_id=current_user.business_id,
        branch_id=branch_id_to_use,
        product_id=product_id,
        movement_type="IN",
        quantity=quantity,
        notes=(
            f"Supplier: {supplier or ''} | "
            f"Invoice: {invoice_number or ''} | "
            f"{notes or ''}"
        ),
        created_by=current_user.id
    )

    db.add(movement)
    db.commit()

    return RedirectResponse(
        "/inventory/restock?success=Stock added successfully",
        status_code=303
    )


# ====================================================
# CREATE BRANCH
# ADMIN ONLY
# ====================================================

@router.post("/create_branch")
def create_branch(
    name: str = Form(...),
    location: str = Form(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    if current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Access denied"
        )

    new_branch = models.Branch(
        business_id=current_user.business_id,
        name=name,
        location=location
    )

    db.add(new_branch)
    db.commit()

    return RedirectResponse(
        "/inventory/manage_branches?success=Branch created successfully",
        status_code=303
    )


# ====================================================
# CREATE PRODUCT
# ADMIN + MANAGER
# ====================================================

@router.post("/create_product")
def create_product(
    name: str = Form(...),
    buying_price: float = Form(0),
    min_stock: int = Form(5),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Access denied"
        )

    new_product = models.Product(
        business_id=current_user.business_id,
        name=name,
        buying_price=buying_price,
        min_stock=min_stock
    )

    db.add(new_product)
    db.commit()

    return RedirectResponse(
        "/inventory/add_product?success=Product created successfully",
        status_code=303
    )