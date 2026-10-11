from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def money(value, places=2):
    """Dollar amount with thousand separators, for display: 1234.5 -> "1,234.50" (templates add the $)."""
    return f"{value:,.{places}f}"


templates.env.filters["money"] = money
