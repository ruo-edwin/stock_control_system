from fastapi.templating import Jinja2Templates
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, "frontend")

templates = Jinja2Templates(directory=TEMPLATE_DIR)
templates.env.globals["current_user"] = lambda request: getattr(request.state, "current_user", None)