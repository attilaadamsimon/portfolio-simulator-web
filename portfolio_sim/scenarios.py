import numpy as np



SP500_RETURNS = [-9.03,-11.85,-21.97,28.36,10.74,4.83,15.61,5.48,-36.55,25.94,
                 14.82,2.10,15.89,32.15,13.52,1.38,11.77,21.61,-4.23,31.21,
                 18.02,28.47,-18.04,26.06,24.88,17.78]
_sp_logs = np.log1p(np.array(SP500_RETURNS)/100)
PRESETS = {
    'conservative': {'name':'Conservative', 'drift':.04, 'volatility':.10, 'years':10, 'paths':2000,
                     'note':'Illustrative lower-risk equity assumptions: 4% annual log drift and 10% volatility.'},
    'aggressive': {'name':'Aggressive', 'drift':.10, 'volatility':.30, 'years':10, 'paths':5000,
                   'note':'Illustrative higher-risk equity assumptions: 10% annual log drift and 30% volatility.'},
    'sp500': {'name':'S&P 500 historical', 'drift':round(float(_sp_logs.mean()),6),
              'volatility':round(float(_sp_logs.std(ddof=1)),6), 'years':10, 'paths':5000,
              'note':'S&P 500 USD annual total returns, 2000–2025 (NYU Stern/Damodaran). Mean and sample standard deviation of annual log returns. Applied to your portfolio in the selected currency; not an FX-adjusted index replay.',
              'source':'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html'},
}

SCENARIOS = {
    'crisis2008': {'name':'2008 financial crisis', 'drift':-.45, 'volatility':.45,
                  'jump_frequency':2., 'jump_mean':-.20, 'jump_std':.12, 'theta_vol':.45, 'xi':.6,
                  'note':'Illustrative severe recession: persistent losses, high volatility and frequent negative jumps. Not a calibrated replay of 2008.'},
    'covid2020': {'name':'2020 COVID crash', 'drift':-.60, 'volatility':.60,
                 'jump_frequency':3., 'jump_mean':-.15, 'jump_std':.15, 'theta_vol':.60, 'xi':.8,
                 'note':'Illustrative acute crash conditions, not the subsequent recovery or the full 2020 return.'},
    'rates': {'name':'Interest rate shock', 'drift':-.18, 'volatility':.30,
              'jump_frequency':1., 'jump_mean':-.10, 'jump_std':.08, 'theta_vol':.30, 'xi':.45,
              'note':'Illustrative equity repricing after a sharp rise in interest rates; no bond or yield-curve model.'},
}
