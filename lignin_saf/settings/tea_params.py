"""
tea_params.py — Techno-economic analysis parameters.

Plant operational assumptions and labor costs.
Labor costs are recalculated here because BioSTEAMs cellulosic ethanol tea defaults to 2.5e6 USD/yr as labor costs, which is an underestimate

"""

# ─── Plant operating schedule ─────────────────────────────────────────────────
operating_days = 330    # [days/yr] scheduled operating days (0.9 operating factor)


# ─── Labor cost from [1]
# # [1] W. Seider et al., Product and Process Design Principles. 2016. John Wiley & Sons.
# Table 17.3 from [1]
# For RCF - 6 operators for the reactors (solids-fluids processing, and > 100 ton/day so 3 x 2 =6 ), and 2 for the distillation columns downstream for solvent recovery. Total operators: 8
# For oil purification and monomer recovery 2 operators each (and 2 secttions so 4 total operators. Total operator: 4
# For HDO: 4 operators (batch, fluids processing would be 2, and then since > 100 ton/day so 2 x 2 = 4), and 2 for the distillation columns downstream for solvent recovery. Total operators: 6
# For ethanol production, 6 operators for reactors as solids-fluids processing and large volumes so 3 x 2 = 6, and then 2 for the beer column downstream for ethanol purification. Total operators: 8
# For ETJ, 2 operators for the reactors, not treating them separately, as ETJ operations are rather conventional, (dehydration, hydrogenation atleast have been around for a while to my knowledge), 1 for 
# the distillation column. Total operators: 3
# 2 operators for the storage  - hydrogen storage will definitely need one I believe and 1 would be required for the rest. Total operators: 2
# Total operators per shift: 8 + 4 + 6 + 8 + 3 + 2 = 31

num_operators_per_shift = 31
num_shifts              = 5       # number of operator shifts (4 working + 1 relief)
pay_rate                = 40      # [USD/hr] operator base pay rate

DWandB             = num_operators_per_shift * num_shifts * 2080 * pay_rate
Dsalaries_benefits = 0.15 * DWandB          # 15% of DW&B for salaried staff + benefits
O_supplies         = 0.06 * DWandB          # 6% of DW&B for operating supplies
technical_assistance = 5 * 75_000           # 5 technical staff @ $75,000/yr
control_lab          = 5 * 80_000           # 5 lab/QC staff  @ $80,000/yr

labor = DWandB + Dsalaries_benefits + O_supplies + technical_assistance + control_lab
# [USD/yr] total annual labor cost; passed to tea.labor_cost after creating the TEA object
