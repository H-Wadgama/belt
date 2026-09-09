"""Direct light-first multicomponent ShortcutColumn train.

The user supplies minimum total-stream mole purities. This module chooses
BioSTEAM ``y_top``/``x_bot`` composition specifications with a constrained
outer optimization, then returns a plain-data result suitable for diagnostics
and user validation. No LLM calls are made here.
"""
import math

import biosteam as bst
import numpy as np
from scipy.optimize import minimize

from multicomponent_biosteam_feed import build_multicomponent_biosteam_feed
from multicomponent_feed_state import record_unit, record_value
from multicomponent_units import temperature_to_K


CHECK_NAME = 'multicomponent_direct_shortcut_train'
COLUMN_PRESSURE_PA = 101325.0
REFLUX_MULTIPLIER_K = 2.0
PARTIAL_CONDENSER = False
SPEC_LOWER_BOUND = 0.001
SPEC_UPPER_BOUND = 0.999
PURITY_TOLERANCE = 1e-6


def _failure(error, message, **extra):
    return {
        'check': CHECK_NAME, 'valid': False, 'status': 'failed',
        'error': error, 'message': message, **extra,
    }


def _plain_stream(stream, component_names):
    return {
        'total_molar_flow_kmol_per_hr': float(stream.F_mol),
        'component_molar_flows_kmol_per_hr': {
            name: float(stream.imol[name]) for name in component_names
        },
    }


def direct_sequence_pairs(order_low_to_high):
    """Return adjacent LHK pairs for the fixed direct/light-first sequence."""
    order = list(order_low_to_high or [])
    return list(zip(order, order[1:]))


def design_direct_shortcut_train(state, order_low_to_high):
    """Optimize and simulate a fixed-pressure direct ShortcutColumn train."""
    component_names = list(state.get('component_names') or [])
    order = list(order_low_to_high or [])
    if len(order) < 3 or set(order) != set(component_names):
        return _failure(
            'invalid_component_order',
            'The internal boiling-point order does not match the feed components.',
        )

    purity_records = state.get('product_purities') or {}
    if not all(name in purity_records for name in component_names):
        return _failure(
            'missing_product_purities',
            'A minimum mole purity is required for every product component.',
        )
    targets = {name: float(record_value(purity_records[name])) for name in component_names}

    try:
        feed, _feed_pressure = build_multicomponent_biosteam_feed(state, stream_id=None)
        feed.T = temperature_to_K(
            record_value(state['feed_temperature']), record_unit(state['feed_temperature']),
        )
        # Current implementation deliberately models every column at one fixed
        # pressure and includes no pressure-changing equipment or pressure drop.
        feed.P = COLUMN_PRESSURE_PA

        columns = []
        column_feed = feed
        products = []
        for index, (light_key, heavy_key) in enumerate(direct_sequence_pairs(order), start=1):
            column = bst.ShortcutColumn(
                None, ins=column_feed, outs=(None, None),
                LHK=(light_key, heavy_key),
                y_top=SPEC_UPPER_BOUND, x_bot=SPEC_LOWER_BOUND,
                k=REFLUX_MULTIPLIER_K, P=COLUMN_PRESSURE_PA,
                partial_condenser=PARTIAL_CONDENSER,
                product_specification_format='Composition',
            )
            columns.append(column)
            products.append(column.outs[0])
            column_feed = column.outs[1]
        products.append(columns[-1].outs[1])
        system = bst.System(None, path=tuple(columns))
    except Exception as err:
        return _failure('train_build_failed', str(err))

    target_vector = np.array([targets[name] for name in order], dtype=float)
    cache = {}

    def set_specifications(values):
        for column, y_top, x_bot in zip(columns, values[0::2], values[1::2]):
            column.y_top = float(y_top)
            column.x_bot = float(x_bot)

    def evaluate(values):
        key = tuple(round(float(i), 12) for i in values)
        if key in cache:
            return cache[key]
        try:
            set_specifications(values)
            system.simulate(design_and_cost=False)
            purities = np.array([
                float(product.imol[name] / product.F_mol) if product.F_mol > 0 else 0.0
                for product, name in zip(products, order)
            ])
            if not np.isfinite(purities).all():
                raise ValueError('non-finite product purity')
            result = (purities, None)
        except Exception as err:
            result = (np.zeros(len(order), dtype=float), str(err))
        cache[key] = result
        return result

    def specification_severity(values):
        # A transparent placeholder objective for the initial implementation:
        # find the least-extreme composition specifications that meet purity.
        y_top = values[0::2]
        x_bot = values[1::2]
        return float(np.sum((y_top - 0.5) ** 2 + (0.5 - x_bot) ** 2))

    initial = np.array(
        [value for _ in columns for value in (SPEC_UPPER_BOUND, SPEC_LOWER_BOUND)],
        dtype=float,
    )
    bounds = [
        bound for _ in columns
        for bound in ((0.500001, SPEC_UPPER_BOUND), (SPEC_LOWER_BOUND, 0.499999))
    ]
    optimization = minimize(
        specification_severity,
        initial,
        method='SLSQP',
        bounds=bounds,
        constraints={
            'type': 'ineq',
            'fun': lambda values: evaluate(values)[0] - target_vector,
        },
        options={'maxiter': 250, 'ftol': 1e-10, 'disp': False},
    )
    achieved, last_error = evaluate(optimization.x)
    constraints_met = bool(np.all(achieved + PURITY_TOLERANCE >= target_vector))
    if not optimization.success or not constraints_met:
        return _failure(
            'purity_optimization_failed',
            last_error or optimization.message,
            optimizer={
                'success': bool(optimization.success),
                'message': str(optimization.message),
                'iterations': int(getattr(optimization, 'nit', 0)),
                'objective_value': float(optimization.fun),
            },
            achieved_product_purities={
                name: float(value) for name, value in zip(order, achieved)
            },
        )

    try:
        set_specifications(optimization.x)
        system.simulate(design_and_cost=True)
    except Exception as err:
        return _failure(
            'final_column_simulation_failed', str(err),
            optimized_specifications=[float(i) for i in optimization.x],
        )

    feed_component_flows = {name: float(feed.imol[name]) for name in component_names}
    product_results = []
    for product, name in zip(products, order):
        purity = float(product.imol[name] / product.F_mol) if product.F_mol else 0.0
        feed_flow = feed_component_flows[name]
        recovery = float(product.imol[name] / feed_flow) if feed_flow else 0.0
        product_results.append({
            'component': name,
            'target_minimum_mole_purity': targets[name],
            'achieved_mole_purity': purity,
            'component_recovery': recovery,
            'stream': _plain_stream(product, component_names),
        })

    column_results = []
    for index, column in enumerate(columns, start=1):
        design = column.design_results
        column_results.append({
            'column_number': index,
            'light_key': column.LHK[0],
            'heavy_key': column.LHK[1],
            'distillate_product': order[index - 1],
            'bottoms_continues_to_next_column': index < len(columns),
            'y_top': float(column.y_top),
            'x_bot': float(column.x_bot),
            'k': float(column.k),
            'partial_condenser': PARTIAL_CONDENSER,
            'pressure_Pa': float(column.P),
            'theoretical_stages': float(design.get('Theoretical stages', math.nan)),
            'minimum_reflux_ratio': float(design.get('Minimum reflux', math.nan)),
            'reflux_ratio': float(design.get('Reflux', math.nan)),
            'purchase_cost_USD': float(column.purchase_cost),
            'utility_cost_USD_per_hr': float(column.utility_cost),
        })

    return {
        'check': CHECK_NAME,
        'valid': True,
        'status': 'complete',
        'error': None,
        'message': None,
        'sequence': 'direct_light_first',
        'component_order_low_to_high': order,
        'column_pressure_Pa': COLUMN_PRESSURE_PA,
        'pressure_drop_Pa_per_column': 0.0,
        'k': REFLUX_MULTIPLIER_K,
        'partial_condenser': PARTIAL_CONDENSER,
        'product_specification_format': 'Composition',
        'objective': 'minimize_composition_specification_severity',
        'optimizer': {
            'method': 'SLSQP',
            'success': True,
            'message': str(optimization.message),
            'iterations': int(optimization.nit),
            'objective_value': float(optimization.fun),
        },
        'columns': column_results,
        'products': product_results,
        'total_purchase_cost_USD': float(sum(c.purchase_cost for c in columns)),
        'total_utility_cost_USD_per_hr': float(sum(c.utility_cost for c in columns)),
    }
