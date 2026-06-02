import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
plt.rc('font',family='Arial')

import os
_dir = os.path.dirname(os.path.abspath(__file__))
df = pd.read_csv(
    os.path.join(_dir, 'lignin_saf', 'spearman_gsa_5000_runs.csv'),
    header=[0, 1], index_col=0, skiprows=[2], encoding='utf-8-sig'
)

# Read
msp_values = df[("TEA", "Minimum jet selling price [USD/gal]")]
msp_df = pd.DataFrame({'MSP ($/gal)': msp_values})
plt.figure(figsize=(1.6937007874, 3.12913386))  # Adjust figure size

# Way to fetch a color palette from seaborn
bugn = sns.color_palette('BuGn', n_colors=6)  # Get 6 shades of blue
light_bugn = bugn[2]
mid_bugn = bugn[4]
dark_bugn = bugn[5]
'''
# Create the violin plot with embedded box plot
sns.violinplot(
    data=msp_df,
    y="MSP ($/gal)",
    inner="box",
    color="#c6dbef",  # Violin body color (HEX)
    linewidth=0
)

'''

sns.boxplot(
    data=msp_df,
    y="MSP ($/gal)",
    width=0.20,
    boxprops={"facecolor": "#44AA99", "edgecolor": 'black', "linewidth": 1},
    medianprops={"color": "black", "linewidth": 1},
    whiskerprops={"color": "black", "linewidth": 1},
    capprops={"color": "black", "linewidth": 1}
)



# Add gray diamond marker at 8.6
ax = plt.gca()
ax.scatter(
    x=0, y=22.08,  # x=0 for single-category violin/box plot
    marker='D',  # Diamond marker
    s=75,       # Size of the marker
    facecolor='lightgray',
    edgecolor='black',
    linewidth=1,
    zorder=10
)


plt.tick_params(axis='both', which='major', labelsize=12, width=1.0, length=7)
# set the axis line width in pixels
ax = plt.gca()  # Get current axes
for axis in ['left', 'bottom', 'top', 'right']:
    ax.spines[axis].set_linewidth(1)
    ax.set_ylim(1, 70)
plt.yticks(fontsize = 10, color = 'black')


# Label the plot
plt.ylabel("MJSP (USD/gal)", fontsize=12, color = 'black')
#plt.title(f'Capacity: {round((saf_stream.F_vol*264.17*24*330)/1e6,1)} MM gal/yr', fontsize=16, color = 'black')
#plt.grid(True, 'major', 'y', linestyle="--", linewidth=1.2, alpha=0.5, color = 'gray')


# Add shaded area from 2.4 to 3 USD/gal
#ax.axhspan(2.4, 3.0, color='#88CCEE', alpha=0.5, zorder=0)

# Add shaded area from 4.4 
#ax.axhspan(4.6, 9.6, color='#DDCC77', alpha=0.5, zorder=0)

# Saving the plot
#plt.savefig("msp_violin_plot.png", dpi=300, bbox_inches="tight")  # PNG format (high quality)
# Show the plot

plt.savefig("box plot-5000.png", bbox_inches="tight")

plt.savefig("box plot-5000.svg", bbox_inches="tight")
plt.show()