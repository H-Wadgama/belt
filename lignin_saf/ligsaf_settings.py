"""
ligsaf_settings.py — Backward-compatibility shim.

All settings have moved to the lignin_saf/settings/ sub-package:

    lignin_saf/settings/process_params.py  — process parameters
    lignin_saf/settings/prices.py          — market prices and CEPCI escalation
    lignin_saf/settings/tea_params.py      — labor and operational assumptions

This file re-exports everything so existing imports continue to work unchanged:

    from lignin_saf.ligsaf_settings import prices, hdo_params   # still works

New code should import directly from the sub-package instead:

    from lignin_saf.settings import prices, hdo_params
    from lignin_saf.settings.prices import methanol_price
"""

from lignin_saf.settings import *
