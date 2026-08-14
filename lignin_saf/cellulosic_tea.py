# -*- coding: utf-8 -*-
"""
Created on Thu Aug  1 21:48:12 2019

@author: yoelr
"""
from biosteam import TEA
import thermosteam as tmo
import biosteam as bst
import pandas as pd
import numpy as np
import flexsolve as flx
# Internal helpers reused verbatim from biosteam._tea (not in its __all__) to
# replicate the cashflow-table / breakeven-price machinery for
# MultiYearCellulosicEthanolTEA. Pinned to biosteam==2.47.0 -- if biosteam is
# upgraded, diff biosteam/_tea.py's TEA.get_cashflow_table,
# TEA._taxable_nontaxable_depreciation_cashflows, and TEA.solve_sales against
# the overrides below and resync.
from biosteam._tea import (
    cashflow_columns,
    add_all_replacement_costs_to_cashflow_array,
    loan_principal_with_interest,
    solve_payment,
    taxable_earnings_with_fowarded_losses,
    NPV_with_sales,
)

__all__ = ('CellulosicEthanolTEA', 'MultiYearCellulosicEthanolTEA',
           'create_cellulosic_ethanol_tea',
           'capex_table', 'voc_table', 'foc_table')

class CAPEXTableBuilder:
    __slots__ = ('index', 'data')
    
    def __init__(self):
        self.index = []
        self.data =[]
    
    def entry(self, index: str, cost: list, notes: str = '-'):
        self.index.append(index)
        self.data.append([notes, *cost])

    @property
    def total_costs(self):
        N = len(self.data[0])
        return [sum([i[index] for i in self.data]) for index in range(1, N)]
    
    def table(self, names):
        return pd.DataFrame(self.data, 
                            index=self.index,
                            columns=('Notes', *[i + '\n[MM$]' for i in names])
        )


class CellulosicEthanolTEA(TEA):
    
    __slots__ = ('OSBL_units', 'warehouse', 'site_development',
                 'additional_piping', 'proratable_costs', 'field_expenses',
                 'construction', 'contingency', 'other_indirect_costs', 
                 'labor_cost', 'labor_burden', 'property_insurance',
                 'maintenance', '_ISBL_DPI_cached', '_FCI_cached',
                 '_utility_cost_cached', '_steam_power_depreciation',
                 '_steam_power_depreciation_array',
                 'boiler_turbogenerator', '_DPI_cached')
    
    def __init__(self, system, IRR, duration, depreciation, income_tax,
                 operating_days, lang_factor, construction_schedule,
                 startup_months, startup_FOCfrac, startup_VOCfrac,
                 startup_salesfrac, WC_over_FCI,  finance_interest,
                 finance_years, finance_fraction, OSBL_units, warehouse,
                 site_development, additional_piping, proratable_costs,
                 field_expenses, construction, contingency,
                 other_indirect_costs, labor_cost, labor_burden,
                 property_insurance, maintenance, steam_power_depreciation,
                 boiler_turbogenerator):
        super().__init__(system, IRR, duration, depreciation, income_tax,
                         operating_days, lang_factor, construction_schedule,
                         startup_months, startup_FOCfrac, startup_VOCfrac,
                         startup_salesfrac, WC_over_FCI,  finance_interest,
                         finance_years, finance_fraction)
        self.OSBL_units = OSBL_units
        self.warehouse = warehouse
        self.site_development = site_development
        self.additional_piping = additional_piping
        self.proratable_costs = proratable_costs
        self.field_expenses = field_expenses
        self.construction = construction
        self.contingency = contingency
        self.other_indirect_costs = other_indirect_costs
        self.labor_cost = labor_cost
        self.labor_burden = labor_burden
        self.property_insurance = property_insurance
        self.maintenance = maintenance
        self.steam_power_depreciation = steam_power_depreciation
        self.boiler_turbogenerator = boiler_turbogenerator
        
    @property
    def steam_power_depreciation(self):
        """[str] 'MACRS' + number of years (e.g. 'MACRS7')."""
        return self._steam_power_depreciation
    @steam_power_depreciation.setter
    def steam_power_depreciation(self, depreciation):
        self._steam_power_depreciation_array = self._depreciation_array_from_key(
            self._depreciation_key_from_name(depreciation)
        )
        self._steam_power_depreciation = depreciation
    
    @property
    def ISBL_installed_equipment_cost(self):
        return self._ISBL_DPI(self.installed_equipment_cost)
    
    @property
    def OSBL_installed_equipment_cost(self):
        if self.lang_factor:
            raise NotImplementedError('lang factor cannot yet be used')
        elif isinstance(self.system, bst.AgileSystem):
            unit_capital_costs = self.system.unit_capital_costs
            OSBL_units = self.OSBL_units
            return sum([unit_capital_costs[i].installed_cost for i in OSBL_units])
        else:
            return sum([i.installed_cost for i in self.OSBL_units])
    
    def _fill_depreciation_array(self, D, start, years, TDC):
        depreciation_array = self._get_depreciation_array()
        N_depreciation_years = depreciation_array.size
        if N_depreciation_years > years:
            dummy = depreciation_array[:years]
            dummy[-1] = depreciation_array[years-1:].sum()
            depreciation_array = dummy
        system = self.system
        BT = self.boiler_turbogenerator
        if BT is None:
            D[start:start + N_depreciation_years] = TDC * depreciation_array
        else:
            if isinstance(system, bst.AgileSystem): BT = system.unit_capital_costs[BT]
            BT_TDC = BT.installed_cost 
            D[start:start + N_depreciation_years] = (TDC - BT_TDC) * depreciation_array
            depreciation_array = self._steam_power_depreciation_array
            N_depreciation_years = depreciation_array.size
            if N_depreciation_years > years:
                dummy = depreciation_array[:years]
                dummy[-1] = depreciation_array[years-1:].sum()
                depreciation_array = dummy
            D[start:start + N_depreciation_years] += BT_TDC * depreciation_array
    
    def _ISBL_DPI(self, installed_equipment_cost):
        """Direct permanent investment of units inside battery limits."""
        if self.lang_factor:
            raise NotImplementedError('lang factor cannot yet be used')
        else:
            self._ISBL_DPI_cached = installed_equipment_cost - self.OSBL_installed_equipment_cost
        return self._ISBL_DPI_cached
        
    def _DPI(self, installed_equipment_cost): # Direct Permanent Investment
        factors = self.warehouse + self.site_development + self.additional_piping
        self._DPI_cached = DPI = installed_equipment_cost + self._ISBL_DPI(installed_equipment_cost) * factors
        return DPI
    
    def _TDC(self, DPI): # Total Depreciable Capital
        return DPI + self._depreciable_indirect_costs(DPI)
    
    def _nondepreciable_indirect_costs(self, DPI):
        return DPI * self.other_indirect_costs
    
    def _depreciable_indirect_costs(self, DPI):
        return DPI * (self.proratable_costs + self.field_expenses
                      + self.construction + self.contingency)
    
    def _FCI(self, TDC): # Fixed Capital Investment
        self._FCI_cached = FCI = TDC + self._nondepreciable_indirect_costs(self._DPI_cached)
        return FCI
    
    def _FOC(self, FCI): # Fixed Operating Costs
        return (FCI * self.property_insurance
                + self._ISBL_DPI_cached * self.maintenance
                + self.labor_cost * (1 + self.labor_burden))
    
    def CAPEX_table(self):
        return capex_table(self)

    def FOC_table(self):
        return foc_table(self)


class MultiYearCellulosicEthanolTEA(CellulosicEthanolTEA):
    """
    Same as `CellulosicEthanolTEA`, but `operating_days` is a sequence
    giving the number of operating days for each year of the plant's
    operating lifetime (length must equal `duration[1] - duration[0]`),
    instead of one constant value applied to every year -- e.g. to model
    a ramp-up year, scheduled turnarounds, or feedstock-driven seasonal
    downtime that varies year to year.

    CAPEX (FCI/TDC/TCI) and fixed operating costs (labor, maintenance,
    property insurance) are unaffected by the schedule, since they don't
    depend on annual operating hours. Only sales and variable operating
    costs (material + utility cost) are rescaled per year, using
    `self.sales` / `self.VOC` -- evaluated at the *mean* of the schedule,
    the "nominal" year -- as the per-hour baseline rate that gets scaled
    up or down by each year's actual operating_days.

    Decoupled from `self.system.operating_hours`
    ----------------------------------------------
    BioSTEAM's base `TEA` reads/writes `self.system.operating_hours` --
    a single mutable attribute shared by every TEA wrapping that System.
    Building a second TEA around the *same* simulated system (e.g. to
    compare operating_days scenarios) silently overwrites that shared
    value and corrupts the first TEA's `sales`/`material_cost`/
    `utility_cost`/`solve_price` results. This class instead keeps its
    own private `operating_hours` (never reads or writes
    `self.system.operating_hours`), so any number of instances of this
    class can safely wrap the same System at once -- e.g. one per
    operating_days scenario, for a genuine side-by-side comparison.

    Note
    ----
    Only the NPV-based methods (`get_cashflow_table`, `solve_price`,
    `solve_IRR`, `solve_sales`, `NPV`, `cashflow_array`,
    `net_earnings_array`, `production_costs`, `total_production_cost`)
    account for the full year-by-year schedule and use the private,
    decoupled `operating_hours`. Simple scalar summary properties
    inherited unchanged from `TEA` (`annual_depreciation`, `net_earnings`,
    `ROI`, `PBP`) still report figures for the nominal (mean-schedule)
    year, not a year-by-year breakdown. `VOC_table` (which calls
    `bst.report.voc_table` on `self.system` directly) is not decoupled
    and will reflect whichever TEA last wrote `self.system.operating_hours`
    -- avoid it when comparing multiple TEAs on one system.
    """
    __slots__ = ('_operating_days_schedule', '_nominal_operating_hours')

    def __init__(self, *args, operating_days, **kwargs):
        schedule = np.asarray(operating_days, dtype=float)
        if schedule.ndim != 1:
            raise ValueError(
                'operating_days schedule must be a 1-d sequence, one value per operating year'
            )
        # Nominal baseline year (mean of the schedule) -- self.sales / self.VOC
        # are computed at this rate and then rescaled per year below.
        super().__init__(*args, operating_days=float(schedule.mean()), **kwargs)
        if schedule.size != self._years:
            raise ValueError(
                f"operating_days schedule has {schedule.size} entries but the plant "
                f"operates for {self._years} years given duration={self.duration} "
                "(duration[1] - duration[0]); provide exactly one entry per operating "
                "year, or pass a matching `duration` to create_cellulosic_ethanol_tea()"
            )
        self._operating_days_schedule = schedule

    @property
    def operating_hours(self) -> float:
        """[float] TEA-private nominal operating hours per year. Does NOT
        read or write `self.system.operating_hours` -- see class docstring."""
        return self._nominal_operating_hours
    @operating_hours.setter
    def operating_hours(self, hours):
        self._nominal_operating_hours = hours

    @property
    def operating_days(self) -> float:
        """[float] Mean operating days per year across `operating_days_schedule` (informational only)."""
        return self.operating_hours / 24.
    @operating_days.setter
    def operating_days(self, days):
        if hasattr(self, '_operating_days_schedule'):
            raise AttributeError(
                f"cannot set a single 'operating_days' value on '{type(self).__name__}'; "
                "set 'operating_days_schedule' instead (one value per operating year)"
            )
        self.operating_hours = 24. * days

    @property
    def operating_days_schedule(self):
        """[1d array] Operating days for each year of the plant's operating lifetime."""
        return self._operating_days_schedule
    @operating_days_schedule.setter
    def operating_days_schedule(self, schedule):
        schedule = np.asarray(schedule, dtype=float)
        if schedule.size != self._years:
            raise ValueError(
                f"operating_days_schedule must have {self._years} entries "
                f"(one per operating year), got {schedule.size}"
            )
        self._operating_days_schedule = schedule
        self.operating_hours = 24. * schedule.mean()

    @property
    def sales(self) -> float:
        """[float] Annual sales revenue [USD/yr] at the nominal (mean-schedule)
        year, using this TEA's private `operating_hours` -- see class docstring."""
        system = self.system
        return self.operating_hours * (
            sum([s.cost for s in system.products if s.price])
            + sum([i._outlet_revenue for i in system.cost_units])
        )
    @property
    def material_cost(self) -> float:
        """[float] Annual material cost [USD/yr] at the nominal (mean-schedule)
        year, using this TEA's private `operating_hours` -- see class docstring."""
        system = self.system
        return self.operating_hours * (
            sum([s.cost for s in system.feeds if s.price])
            + sum([i._inlet_cost for i in system.cost_units])
        )
    @property
    def utility_cost(self) -> float:
        """[float] Annual utility cost [USD/yr] at the nominal (mean-schedule)
        year, using this TEA's private `operating_hours` -- see class docstring."""
        return sum([u.utility_cost for u in self.system.cost_units]) * self.operating_hours

    def _market_value(self, stream):
        """Annual market value [USD/yr] of a stream, using this TEA's private
        `operating_hours` (in place of `self.system.get_market_value`)."""
        return stream.cost * self.operating_hours

    def _price2cost(self, stream):
        """Factor to convert a stream's price to annual cost, using this
        TEA's private `operating_hours` (in place of `self.system._price2cost`)."""
        F_mass = stream.F_mass
        if not F_mass:
            from warnings import warn
            warn(RuntimeWarning(f"stream '{stream}' is empty"))
        price2cost = F_mass * self.operating_hours
        if stream.sink and not stream.source:
            return -price2cost
        elif stream.source:
            return price2cost
        else:
            raise ValueError("stream must be either a feed or a product")

    def solve_price(self, streams):
        """Same as TEA.solve_price, but uses this TEA's private `_price2cost`/
        `_market_value` instead of `self.system._price2cost`/`get_market_value`,
        so the result is unaffected by any other TEA sharing this system."""
        if isinstance(streams, bst.Stream): streams = [streams]
        price2cost = sum([self._price2cost(i) for i in streams])
        if price2cost == 0.: raise ValueError('cannot solve price of empty streams')
        try:
            sales = self.solve_sales()
        except:
            original_prices = [i.price for i in streams]
            for i in streams: i.price = 0.
            sales = self.solve_sales()
            current_price = 0.
            for i, j in zip(streams, original_prices): i.price = j
        else:
            current_price = sum([self._market_value(i) for i in streams]) / abs(price2cost)
        return current_price + sales / price2cost

    def production_costs(self, products, with_annual_depreciation=True):
        """Same as TEA.production_costs, but uses this TEA's private
        `_market_value` instead of `self.system.get_market_value`."""
        market_values = np.array([self._market_value(i) for i in products])
        total_market_value = market_values.sum()
        weights = market_values / total_market_value
        return weights * self.total_production_cost(products, with_annual_depreciation)

    def total_production_cost(self, products, with_annual_depreciation=True):
        """Same as TEA.total_production_cost, but uses this TEA's private
        `_market_value` instead of `self.system.get_market_value`."""
        coproduct_sales = self.sales - sum([self._market_value(i) for i in products])
        if with_annual_depreciation:
            TDC = self.TDC
            annual_depreciation = TDC / (self.duration[1] - self.duration[0])
            AOC = self._AOC(self._FCI(TDC))
            return AOC - coproduct_sales + annual_depreciation
        else:
            return self.AOC - coproduct_sales

    def _year_hours_ratio(self):
        """Ratio of each operating year's hours to the nominal (mean-schedule)
        hours that `self.sales` / `self.VOC` are computed at."""
        return 24. * self._operating_days_schedule / self.operating_hours

    def get_cashflow_table(self):
        """Return DataFrame of the cash flow analysis, with sales and VOC
        rescaled per year by `operating_days_schedule`."""
        ratio = self._year_hours_ratio()
        TDC = self.TDC
        FCI = self._FCI(TDC)
        start = self._start
        years = self._years
        FOC = self._FOC(FCI)
        VOC = self.VOC
        sales = self.sales
        length = start + years
        C_D, C_FC, C_WC, D, L, LI, LP, LPl, C, S, T, I, TE, FL, NE, CF, DF, NPV, CNPV = data = np.zeros((19, length))
        self._fill_depreciation_array(D, start, years, TDC)
        w0 = self._startup_time
        w1 = 1. - w0
        C[start] = ratio[0]*(w0*self.startup_VOCfrac*VOC + w1*VOC) + (w0*self.startup_FOCfrac*FOC + w1*FOC)
        S[start] = ratio[0]*(w0*self.startup_salesfrac*sales + w1*sales)
        start1 = start + 1
        C[start1:] = VOC*ratio[1:] + FOC
        S[start1:] = sales*ratio[1:]
        WC = self.WC_over_FCI * FCI
        C_D[:start] = TDC*self._construction_schedule
        C_FC[:start] = FCI*self._construction_schedule
        C_WC[start-1] = WC
        C_WC[-1] = -WC
        system = self.system
        lang_factor = system.lang_factor
        unit_capital_costs = system.unit_capital_costs.values() if isinstance(system, bst.AgileSystem) else system.cost_units
        for i in unit_capital_costs: add_all_replacement_costs_to_cashflow_array(i, C_FC, years, start, lang_factor)
        if self.finance_interest:
            interest = self.finance_interest
            finance_years = self.finance_years
            end = start + finance_years
            L[:start] = loan = self.finance_fraction*(C_FC[:start])
            accumulate_interest_during_construction = self.accumulate_interest_during_construction
            if accumulate_interest_during_construction:
                initial_loan_principal = loan_principal_with_interest(loan, interest)
            else:
                initial_loan_principal = loan.sum()
            LP[start:end] = solve_payment(initial_loan_principal, interest, finance_years)
            loan_principal = 0
            if accumulate_interest_during_construction:
                for i in range(end):
                    LI[i] = li = (loan_principal + L[i]) * interest
                    LPl[i] = loan_principal = loan_principal - LP[i] + li + L[i]
            else:
                for i in range(end):
                    li = 0 if i < start else (loan_principal + L[i]) * interest
                    LI[i] = li
                    LPl[i] = loan_principal = loan_principal - LP[i] + li + L[i]
                LI[:start] = L[:start] * interest
            taxable_cashflow = S - C - D - LP
            nontaxable_cashflow = D + L - C_FC - C_WC
            if not accumulate_interest_during_construction:
                nontaxable_cashflow[:start] -= LI[:start]
        else:
            taxable_cashflow = S - C - D
            nontaxable_cashflow = D - C_FC - C_WC
        TE[:] = taxable_earnings_with_fowarded_losses(taxable_cashflow)
        FL[1:] = (taxable_cashflow - TE).cumsum()[:-1]
        self._fill_tax_and_incentives(I, TE, nontaxable_cashflow, T, D)
        NE[:] = taxable_cashflow + I - T
        CF[:] = NE + nontaxable_cashflow
        DF[:] = 1/(1.+self.IRR)**self._get_duration_array()
        NPV[:] = CF * DF
        CNPV[:] = NPV.cumsum()
        DF *= 1e6
        data /= 1e6
        return pd.DataFrame(data.transpose(),
                            index=np.arange(self.duration[0]-start, self.duration[1]),
                            columns=cashflow_columns)

    def _taxable_nontaxable_depreciation_cashflows(self):
        """Same as TEA._taxable_nontaxable_depreciation_cashflows, but sales
        and VOC are rescaled per year by `operating_days_schedule`."""
        ratio = self._year_hours_ratio()
        TDC = self.TDC
        FCI = self._FCI(TDC)
        start = self._start
        years = self._years
        FOC = self._FOC(FCI)
        VOC = self.VOC
        sales = self.sales
        D, C_FC, C_WC, Loan, LP, C, S = np.zeros((7, start + years))
        self._fill_depreciation_array(D, start, years, TDC)
        WC = self.WC_over_FCI * FCI
        system = self.system
        w0 = self._startup_time
        w1 = 1. - w0
        C[start] = ratio[0]*(w0*self.startup_VOCfrac*VOC + w1*VOC) + (w0*self.startup_FOCfrac*FOC + w1*FOC)
        S[start] = ratio[0]*(w0*self.startup_salesfrac*sales + w1*sales)
        start1 = start + 1
        C[start1:] = VOC*ratio[1:] + FOC
        S[start1:] = sales*ratio[1:]
        C_FC[:start] = FCI * self._construction_schedule
        C_WC[start-1] = WC
        C_WC[-1] = -WC
        unit_capital_costs = system.unit_capital_costs.values() if isinstance(system, bst.AgileSystem) else system.cost_units
        for i in unit_capital_costs:
            add_all_replacement_costs_to_cashflow_array(i, C_FC, years, start, self.lang_factor)
        if self.finance_interest:
            interest = self.finance_interest
            finance_years = self.finance_years
            Loan[:start] = loan = self.finance_fraction*(C_FC[:start])
            if self.accumulate_interest_during_construction:
                loan_principal = loan_principal_with_interest(loan, interest)
            else:
                loan_principal = loan.sum()
            LP[start:start + finance_years] = solve_payment(loan_principal, interest, finance_years)
            taxable_cashflow = S - C - D - LP
            nontaxable_cashflow = D + Loan - C_FC - C_WC
            if not self.accumulate_interest_during_construction:
                nontaxable_cashflow[:start] -= loan * interest
        else:
            taxable_cashflow = S - C - D
            nontaxable_cashflow = D - C_FC - C_WC
        return taxable_cashflow, nontaxable_cashflow, D

    def solve_sales(self):
        """Same as TEA.solve_sales, but the incremental-sales coefficient
        for each operating year is scaled by that year's operating_days,
        so the solved price reflects actual per-year production instead of
        assuming a flat annual sales volume."""
        ratio = self._year_hours_ratio()
        discount_factors = (1 + self.IRR)**self._get_duration_array()
        sales_coefficients = np.zeros_like(discount_factors, dtype=float)
        start = self._start
        w0 = self._startup_time
        sales_coefficients[start] = ratio[0] * (w0*self.startup_salesfrac + (1.-w0))
        sales_coefficients[start+1:] = ratio[1:]
        taxable_cashflow, nontaxable_cashflow, depreciation = self._taxable_nontaxable_depreciation_cashflows()
        if np.isnan(taxable_cashflow).any():
            from warnings import warn
            warn('nan encountered in cashflow array; resimulating system', category=RuntimeWarning)
            self.system.simulate()
            taxable_cashflow, nontaxable_cashflow, depreciation = self._taxable_nontaxable_depreciation_cashflows()
            if np.isnan(taxable_cashflow).any():
                raise RuntimeError('nan encountered in cashflow array')
        args = (taxable_cashflow,
                nontaxable_cashflow,
                depreciation,
                sales_coefficients,
                discount_factors,
                self._fill_tax_and_incentives)
        x0 = self._sales if np.isfinite(self._sales) else 0
        f = NPV_with_sales
        y0 = f(x0, *args)
        x1 = x0 - y0 / self._years
        try:
            sales = flx.aitken_secant(f, x0, x1, xtol=10, ytol=100.,
                                      maxiter=1000, args=args, checkiter=True)
        except:
            bracket = flx.find_bracket(f, x0, x1, args=args)
            sales = flx.IQ_interpolation(f, *bracket, args=args, xtol=10, ytol=100, maxiter=1000, checkiter=False)
        self._sales = sales
        return sales


def create_cellulosic_ethanol_tea(sys, operating_days=330, duration=(2016, 2046), OSBL_units=None, cls=None):
    # Default parameters are from NREL 2011 report for cornstover ethanol
    if OSBL_units is None: OSBL_units = bst.get_OSBL(sys.cost_units)
    try:
        BT = tmo.utils.get_instance(OSBL_units, (bst.BoilerTurbogenerator, bst.Boiler))
    except:
        BT = None
    if cls is None:
        # A sequence (list/tuple/array) of operating_days -> one entry per
        # operating year -> dispatch to the multi-year variant automatically.
        cls = MultiYearCellulosicEthanolTEA if np.ndim(operating_days) > 0 else CellulosicEthanolTEA
    tea = cls(
        system=sys,
        IRR=0.1,
        duration=duration,
        depreciation='MACRS7',
        income_tax=0.21,
        operating_days=operating_days,
        lang_factor=None,
        construction_schedule=(0.08, 0.60, 0.32),
        startup_months=3, 
        startup_FOCfrac=1,
        startup_salesfrac=0.5,
        startup_VOCfrac=0.75,
        WC_over_FCI=0.05,
        finance_interest=0.08,
        finance_years=10,
        finance_fraction=0.6,
        OSBL_units=OSBL_units,
        warehouse=0.04, 
        site_development=0.09, 
        additional_piping=0.045,
        proratable_costs=0.10,
        field_expenses=0.10,
        construction=0.20,
        contingency=0.10,
        other_indirect_costs=0.10, 
        labor_cost=2.5e6,
        labor_burden=0.90,
        property_insurance=0.007, 
        maintenance=0.03,
        steam_power_depreciation='MACRS20',
        boiler_turbogenerator=BT)
    return tea

def capex_table(teas, names=None, dataframe=True):
    if isinstance(teas, bst.TEA): teas = [teas]
    if names is None: 
        if len(teas) == 1:
            names = None
        else:
            names = [i.system.ID for i in teas]
    tea, *_ = teas
    capex = tea.Accounting('MM$', names=names)
    ISBL_installed_equipment_costs = np.array([i.ISBL_installed_equipment_cost / 1e6 for i in teas])
    OSBL_installed_equipment_costs = np.array([i.OSBL_installed_equipment_cost / 1e6 for i in teas])
    capex.entry(('Direct costs', 'ISBL installed equipment cost'), ISBL_installed_equipment_costs)
    capex.entry(('Direct costs', 'OSBL installed equipment cost'), OSBL_installed_equipment_costs)
    ISBL_factor_entry = lambda name, value: capex.entry(name, ISBL_installed_equipment_costs * value, f"{value:.1%} of ISBL")
    ISBL_factor_entry(('Direct costs', 'Warehouse'), tea.warehouse)
    ISBL_factor_entry(('Direct costs', 'Site development'), tea.site_development)
    ISBL_factor_entry(('Direct costs', 'Additional piping'), tea.additional_piping)
    TDC = np.array(capex.total_costs)
    capex.entry(('Total direct cost (TDC)', ''), TDC)
    TDC_factor_entry = lambda name, value: capex.entry(name, TDC * value, f"{value:.1%} of TDC")
    TDC_factor_entry(('Indirect costs', 'Proratable costs'), tea.proratable_costs)
    TDC_factor_entry(('Indirect costs', 'Field expenses'), tea.field_expenses)
    TDC_factor_entry(('Indirect costs', 'Construction'), tea.construction)
    TDC_factor_entry(('Indirect costs', 'Contingency'), tea.contingency)
    TDC_factor_entry(('Indirect costs', 'Other (start-up, permits, etc.)'), tea.other_indirect_costs)
    TIC = np.array(capex.total_costs) - 2 * TDC
    capex.entry(('Total indirect cost (TIC)', ''), TIC)
    FCI = TDC + TIC
    capex.entry(('Fixed capital investment (FCI)', ''), FCI, 'TDC + TIC')
    working_capital = FCI * tea.WC_over_FCI
    capex.entry(('Working capital (WC)', ''), working_capital, f"{tea.WC_over_FCI:.1%} of FCI")
    TCI = FCI + working_capital
    capex.entry(('Total capital investment (TCI)', ''), TCI, 'FCI + WC')
    return capex.table() if dataframe else capex

voc_table = bst.report.voc_table

def foc_table(teas, names=None, dataframe=True):
    if isinstance(teas, bst.TEA): teas = [teas]
    tea, *_ = teas
    if names is None: 
        if len(teas) == 1: 
            names = None
        else:
            names = [i.system.ID for i in teas]
    accounting = tea.Accounting('MM$ / yr', names=names)
    ISBL = np.array([i.ISBL_installed_equipment_cost / 1e6 for i in teas])
    labor_cost = np.array([i.labor_cost / 1e6 for i in teas])
    accounting.entry('Labor salary', labor_cost)
    accounting.entry('Labor burden', tea.labor_burden * labor_cost, '90% of labor salary')
    accounting.entry('Maintenance', tea.maintenance * ISBL, f'{tea.maintenance:.1%} of ISBL')
    accounting.entry('Property insurance', tea.property_insurance * ISBL, f'{tea.property_insurance:.1%} of ISBL')
    return accounting.table() if dataframe else accounting