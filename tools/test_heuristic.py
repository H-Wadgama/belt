Heuristic(
    category="separation_factor_estimation",
    condition=(
        "liquid and vapor solutions are nearly ideal "
        "and the vapor phase obeys the ideal gas law"
    ),
    principle=(
        "For vapor-liquid separation using an ESA, "
        "the separation factor equals the relative volatility."
    ),
    design_implication=(
        "Estimate separation difficulty from the ratio "
        "of the component vapor pressures."
    ),
    heuristic_type="equation",
    equation="SF = alpha_1,2 = Ps_1 / Ps_2",
    required_variables=["Ps_1", "Ps_2"],
)