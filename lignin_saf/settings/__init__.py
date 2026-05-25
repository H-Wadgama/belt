"""
lignin_saf/settings — Process parameters, prices, and TEA assumptions.

Sub-modules
-----------
process_params  Physical reactor conditions, sizing limits, LLE K-values.
                Edit when the process design changes.
prices          Market prices for feedstocks, chemicals, and utilities.
                Edit when performing a price update pass.
tea_params      Labor costs and operational assumptions (operating days,
                staffing). Edit when updating TEA assumptions.

Adding a new variable
---------------------
Add it to the appropriate sub-module only. It is automatically re-exported
here and through ligsaf_settings.py — no other files need to change.
Variables prefixed with _ are private and will NOT be re-exported.

Typical import
--------------
    from lignin_saf.settings import prices, hdo_params, labor
    from lignin_saf.settings.prices import methanol_price   # sub-module import
"""

from .process_params import *
from .prices import *
from .tea_params import *
