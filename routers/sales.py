from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import List, Optional

from backend.db import SessionLocal
from backend import models
from backend.config import templates
from backend.auth_utils import get_current_user
from backend.onboarding_utils import record_onboarding_event


# ----------------------------------------------------
# CONFIG
# ----------------------------------------------------

BASE_URL = "https://pos-10-production.up.railway.app"


router = APIRouter(
    prefix="/sales",
    tags=["sales"]
)


# ----------------------------------------------------
# DB SESSION
# ----------------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------------------------------
# ROLE CHECKS
# ----------------------------------------------------

def require_sales_access(
    current_user: models.User = Depends(get_current_user)
):
    """
    Users allowed to record sales:
    - admin
    - manager
    - storekeeper
    """

    if current_user.role not in ["admin", "manager", "storekeeper"]:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access sales."
        )

    return current_user


def require_admin(
    current_user: models.User = Depends(get_current_user)
):
    """
    Admin-only areas.
    """

    if current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin access required."
        )

    return current_user


# ----------------------------------------------------
# PAGES
# ----------------------------------------------------

@router.get(
    "/recordsale",
    response_class=HTMLResponse
)
async def record_sale_page(
    request: Request,
    current_user: models.User = Depends(require_sales_access)
):
    source = request.query_params.get("source")

    return templates.TemplateResponse(
        "record_sale.html",
        {
            "request": request,
            "source": source,
            "current_user": current_user
        }
    )


@router.get(
    "/salesreport",
    response_class=HTMLResponse
)
async def sales_report_page(
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    record_onboarding_event(
        db,
        current_user.business_id,
        "view_report"
    )

    return templates.TemplateResponse(
        "sales_report.html",
        {
            "request": request,
            "current_user": current_user
        }
    )


# ----------------------------------------------------
# INPUT MODELS
# ----------------------------------------------------

class SaleItem(BaseModel):
    product_name: str
    quantity: int
    selling_price: float


class SaleRequest(BaseModel):
    client_name: Optional[str] = None
    sales_person: Optional[str] = None
    items: List[SaleItem]


# ====================================================
# RECORD SALE
# ====================================================

@router.post("/record_sale/")
def record_sale(
    sale_data: SaleRequest,
    request: Request,
    current_user: models.User = Depends(require_sales_access),
    db: Session = Depends(get_db)
):

    business_id = current_user.business_id

    # ------------------------------------------------
    # DETECT ONBOARDING SOURCE
    # ------------------------------------------------

    source = request.query_params.get("source")
    is_onboarding = source == "onboarding"

    # ------------------------------------------------
    # CHECK IF BUSINESS ALREADY HAS A REAL SALE
    # ------------------------------------------------

    has_real_sale = (
        db.query(models.Sales)
        .join(
            models.Order,
            models.Sales.order_id == models.Order.id
        )
        .filter(
            models.Order.business_id == business_id,
            models.Sales.is_demo == False
        )
        .first()
    )

    # ------------------------------------------------
    # DEMO SALE ONLY FOR ONBOARDING + NO REAL SALES
    # ------------------------------------------------

    is_demo_sale = (
        is_onboarding
        and has_real_sale is None
    )

    # ------------------------------------------------
    # REMOVE OLD DEMO SALES WHEN REAL SALE IS MADE
    # ------------------------------------------------

    if not is_demo_sale:

        demo_order_ids_rows = (
            db.query(models.Order.id)
            .join(
                models.Sales,
                models.Sales.order_id == models.Order.id
            )
            .filter(
                models.Order.business_id == business_id,
                models.Sales.is_demo == True
            )
            .distinct()
            .all()
        )

        demo_order_ids_list = [
            row[0]
            for row in demo_order_ids_rows
        ]

        if demo_order_ids_list:

            # Delete demo sales
            db.query(models.Sales).filter(
                models.Sales.order_id.in_(demo_order_ids_list),
                models.Sales.is_demo == True
            ).delete(
                synchronize_session=False
            )

            # Delete demo orders
            db.query(models.Order).filter(
                models.Order.id.in_(demo_order_ids_list),
                models.Order.business_id == business_id
            ).delete(
                synchronize_session=False
            )

            db.commit()

    # ------------------------------------------------
    # GENERATE ORDER CODE
    # ------------------------------------------------

    last_order = db.execute(
        text(
            "SELECT id FROM orders ORDER BY id DESC LIMIT 1"
        )
    ).fetchone()

    next_number = (
        1
        if not last_order
        else last_order[0] + 1
    )

    order_code = f"ORD-{next_number:05d}"

    # ------------------------------------------------
    # CREATE ORDER
    # ------------------------------------------------

    new_order = models.Order(
        order_code=order_code,
        business_id=business_id,
        client_name=sale_data.client_name,

        # Use logged-in user's username
        sales_person=current_user.username,

        # Use actual logged-in user's ID
        created_by=current_user.id,

        total_amount=0
    )

    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    total_amount = 0
    total_profit = 0.0

    # ------------------------------------------------
    # PROCESS EACH PRODUCT
    # ------------------------------------------------

    for item in sale_data.items:

        product = (
            db.query(models.Product)
            .filter(
                models.Product.name == item.product_name,
                models.Product.business_id == business_id
            )
            .first()
        )

        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product '{item.product_name}' not found"
            )

        # --------------------------------------------
        # STOCK CHECK FOR REAL SALES
        # --------------------------------------------

        if not is_demo_sale:

            if product.quantity < item.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Not enough stock for "
                        f"'{item.product_name}'"
                    )
                )

        # --------------------------------------------
        # SELLING PRICE CHECK
        # --------------------------------------------

        if (
            product.buying_price is not None
            and item.selling_price < product.buying_price
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Selling price for "
                    f"'{product.name}' cannot be "
                    f"below buying price"
                )
            )

        # --------------------------------------------
        # CALCULATE TOTALS
        # --------------------------------------------

        subtotal = (
            item.selling_price * item.quantity
        )

        total_amount += subtotal

        # --------------------------------------------
        # REDUCE STOCK FOR REAL SALES
        # --------------------------------------------

        if not is_demo_sale:
            product.quantity -= item.quantity

        # --------------------------------------------
        # CALCULATE PROFIT
        # --------------------------------------------

        buying_price = (
            product.buying_price
            if product.buying_price is not None
            else 0
        )

        total_profit += (
            (item.selling_price - buying_price)
            * item.quantity
        )

        # --------------------------------------------
        # CREATE SALE ROW
        # --------------------------------------------

        sale_row = models.Sales(
            order_id=new_order.id,
            product_id=product.id,
            quantity=item.quantity,
            total_price=subtotal,
            is_demo=is_demo_sale
        )

        db.add(sale_row)

    # ------------------------------------------------
    # SAVE ORDER TOTAL
    # ------------------------------------------------

    new_order.total_amount = total_amount

    db.commit()

    # ------------------------------------------------
    # ONBOARDING EVENT
    # ------------------------------------------------

    record_onboarding_event(
        db,
        business_id,
        "sell_product"
    )

    # ------------------------------------------------
    # RESPONSE MESSAGE
    # ------------------------------------------------

    message = "Order recorded successfully!"

    if is_demo_sale:
        message = (
            "Demo sale recorded successfully. "
            "Your stock was NOT reduced. "
            "When you record your next sale, "
            "this demo will be removed automatically."
        )

    return {
        "message": message,
        "order_code": order_code,
        "total_amount": total_amount,
        "total_profit": round(
            float(total_profit),
            2
        ),
        "is_demo": is_demo_sale
    }


# ====================================================
# GET SALES ITEMS
# ADMIN ONLY
# ====================================================

@router.get("/get_sales_items")
def get_sales_items(
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):

    business_id = current_user.business_id

    sales_items = (
        db.query(
            models.Sales,
            models.Order,
            models.Product
        )
        .join(
            models.Order,
            models.Sales.order_id == models.Order.id
        )
        .join(
            models.Product,
            models.Sales.product_id == models.Product.id
        )
        .filter(
            models.Order.business_id == business_id
        )
        .order_by(
            models.Sales.id.desc()
        )
        .all()
    )

    output = []

    for sale, order, product in sales_items:

        output.append({
            "order_code": order.order_code,
            "date": order.created_at,
            "client_name": order.client_name,
            "sales_person": order.sales_person,
            "product_name": product.name,
            "quantity": sale.quantity,
            "subtotal": sale.total_price,
            "buying_price": (
                product.buying_price
                or 0
            ),
            "is_demo": getattr(
                sale,
                "is_demo",
                False
            )
        })

    return output