from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class OklahomaWithholdingTable(Base):
    """One year's OTC Packet OW-2 percentage method tables (Table 7: ANNUAL payroll
    period), entered by admins under Tax Settings. `data` holds amounts as strings:

      {"allowance": "1000",                       # annual amount per OK-W-4 allowance
       "single":  [[over, tentative_amount, rate], ...],
       "married": [...]}

    Rows run up to the next row's "over"; rate is a fraction. The number of rows
    varies by year as Oklahoma changes its brackets.
    """
    __tablename__ = "oklahoma_withholding_tables"

    year: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    data: Mapped[dict] = mapped_column(JSON)


OK_STATUSES = ("single", "married")

# Published tables shipped with the app, seeded into an empty table on startup.
DEFAULT_OKLAHOMA_TABLES = {
    2025: {  # OTC Packet OW-2, revised 11-2024, Table 7
        "allowance": "1000",
        "single": [
            ["0", "0", "0"],
            ["6350", "0", "0.0025"],
            ["7350", "2.50", "0.0075"],
            ["8850", "13.75", "0.0175"],
            ["10100", "35.63", "0.0275"],
            ["11250", "67.25", "0.0375"],
            ["13550", "153.50", "0.0475"],
        ],
        "married": [
            ["0", "0", "0"],
            ["12700", "0", "0.0025"],
            ["14700", "5.00", "0.0075"],
            ["17700", "27.50", "0.0175"],
            ["20200", "71.25", "0.0275"],
            ["22500", "134.50", "0.0375"],
            ["27100", "307.00", "0.0475"],
        ],
    },
    2026: {  # OTC Packet OW-2, revised 11-2025, Table 7 (HB 2764: three brackets, 4.5% top rate)
        "allowance": "1000",
        "single": [
            ["0", "0", "0"],
            ["10100", "0", "0.025"],
            ["11250", "28.75", "0.035"],
            ["13550", "109.25", "0.045"],
        ],
        "married": [
            ["0", "0", "0"],
            ["20200", "0", "0.025"],
            ["22500", "57.50", "0.035"],
            ["27100", "218.50", "0.045"],
        ],
    },
}
