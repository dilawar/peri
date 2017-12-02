import os
import copy
import pickle
import tempfile
import numpy as np
import scipy as sp

import matplotlib.pyplot as pl
from mpl_toolkits.axes_grid1 import ImageGrid

from peri import util, runner, states
from peri.test import nbody
from peri.comp import ilms, objs, psfs, exactpsf
from peri.opt import optimize as opt
from peri.viz.plots import lbl

FIXEDSS = [31,17,29]

def create_image(N=128, size=64, radius=6.0, pad=16):
    blank = np.zeros((size,)*3)

    pos, rad, tile = nbody.initialize_particles(
        N, radius=radius, tile=util.Tile(blank.shape), polydispersity=0.0
    )
    sim = nbody.BrownianHardSphereSimulation(pos, rad, tile)
    sim.relax(2000)
    sim.step(5000)
    sim.relax(2000)

    slab_zpos = -radius
    s = runner.create_state(
        blank, pos, rad, slab=slab_zpos, sigma=1e-6,
        stateargs={'pad': pad, 'offset': 0.18},
        psftype='cheb-linescan-fixedss', psfargs={
            'zslab': 10., 'cheb_degree': 6, 'cheb_evals': 8,
            'support_size': FIXEDSS,
        },
        ilmtype='barnesleg2p1dx', ilmargs={'order': (1,1,3), 'npts': (30,10,5)}
    )
    s.ilm.randomize_parameters(ptp=0.4, vmax=1.0, fourier=False)
    s.reset()
    s.model_to_true_image()
    return s

def optimize(s):
    args = dict(eig_update=True, update_J_frequency=2,
            partial_update_frequency=1, max_iter=3)
    blocks = s.b_ilm | s.b_psf | s.b_zscale

    lm0 = opt.LMGlobals(s, blocks, **args)
    lm1 = opt.LMParticles(s, particles=np.arange(s.N), **args)

    for i in range(5):
        lm0.do_run_2()
        lm0.reset(3e-2)

        lm1.do_run_2()
        lm1.reset(3e-2)

def table(s, datas, names, vary_func):
    p0 = s.obj.pos.copy()
    r0 = s.obj.rad.copy()

    slicer = np.s_[s.image[s.inner].shape[0]/2]
    model_image = s.image[s.inner][slicer].copy()

    results = [0]*(len(names)+1)
    results[0] = ('Refernce', model_image, p0, r0)

    filename = tempfile.NamedTemporaryFile().name
    states.save(s, filename=filename)

    for i, (name, data) in enumerate(zip(names, datas)):
        print(i, name, data)
        state = states.load(filename)

        vary_func(state, data)
        state.reset()

        optimize(state)

        results[i+1] = (
            name,
            state.get_difference_image()[slicer].copy(),
            state.obj.pos.copy(),
            state.obj.rad.copy()
        )

    os.remove(filename)
    return results

def table_platonic():
    np.random.seed(10)
    s = create_image()

    platonics = [
        ('lerp', 0.05),
        ('lerp', 0.5),
        ('logistic',),
        ('constrained-cubic',),
        ('exact-gaussian-fast',)
    ]
    names = [
        r'Boolean cut',
        r'Linear interpolation',
        r'Logistic function',
        r'Constrained cubic',
        r'Approx Fourier sphere'
    ]

    def vary_func(s, data):
        if data[0] != 'exact-gaussian-fast':
            s.obj.exact_volume = False
            s.obj.volume_error = 100.
        else:
            s.obj.exact_volume = True
            s.obj.volume_error = 1e-5

        s.obj.set_draw_method(*data)

    return table(s, platonics, names, vary_func)

def table_ilms():
    np.random.seed(11)
    s = create_image()

    lilms = [
        ilms.LegendrePoly2P1D(shape=s.ilm.shape, order=(1,1,1)),
        ilms.LegendrePoly2P1D(shape=s.ilm.shape, order=(3,3,3)),
        ilms.BarnesStreakLegPoly2P1DX3(shape=s.ilm.shape, order=(1,1,1), npts=(10,5)),
        ilms.BarnesStreakLegPoly2P1DX3(shape=s.ilm.shape, order=(1,1,2), npts=(30,10)),
        ilms.BarnesStreakLegPoly2P1DX3(shape=s.ilm.shape, order=s.ilm.order, npts=(30,10,5)),
    ]
    names = [
        r'Legendre 2+1D (0,0,0)',
        r'Legendre 2+1D (2,2,2)',
        r'Barnes (10, 5) $N_z=1$',
        r'Barnes (30, 10) $N_z=2$',
        r'Barnes (30, 10, 5) $N_z=3$',
    ]

    def vary_func(s, data):
        s.set_ilm(data)

    return table(s, lilms, names, vary_func)

def table_psfs():
    np.random.seed(12)
    s = create_image()
    sh = s.psf.shape

    lpsfs = [
        psfs.IdentityPSF(shape=sh, params=np.array([0.0])),
        psfs.AnisotropicGaussian(shape=sh, params=(2.0, 1.0, 3.0)),
        psfs.Gaussian4DLegPoly(shape=sh, order=(3,3,3)),
        exactpsf.FixedSSChebLinePSF(
            shape=sh, zrange=(0, sh[0]), cheb_degree=3, cheb_evals=6,
            support_size=FIXEDSS, zslab=10., cutoffval= 1./255,
            measurement_iterations=3,
        ),
        exactpsf.FixedSSChebLinePSF(
            shape=sh, zrange=(0, sh[0]), cheb_degree=6, cheb_evals=8,
            support_size=FIXEDSS, zslab=10., cutoffval= 1./255,
            measurement_iterations=3,
        ),
    ]
    names = [
        r'Identity',
        r'Gaussian$(x,y)$',
        r'Gaussian$(x,y,z,z^{\prime})$',
        r'Cheby linescan (3,6)',
        r'Cheby linescan (6,8)',
    ]

    def vary_func(s, data):
        s.set_psf(data)

    return table(s, lpsfs, names, vary_func)

def gogogo():
    r0 = table_platonic()
    r1 = table_ilms()
    r2 = table_psfs()
    return r0, r1, r2

def scores(results):
    scores = []
    for result in results:
        ref = result[0]

        errors = []
        for val in result[1:]:
            errors.append([
                val[0],
                np.sqrt(((ref[2] - val[2])**2).sum(axis=-1)).mean(),
                np.sqrt((ref[3] - val[3])**2).mean(),
            ])

        scores.append(errors)
    return scores

def numform(x):
    p = int(np.floor(np.log10(x)))
    n = x / 10**p
    return "{:1.2f} ({:d})".format(n, p)

def numform2(x):
    return "{:0.5f}".format(x)

def print_table(tables, sections=['Platonic', 'Illumination', 'PSF'],
        fulldocument=False):

    outstr = ''

    if fulldocument:
        outstr = (
            '\\documentclass[preprint]{revtex4}\n'
            '\\usepackage{graphicx}\n'
            '\\usepackage{multirow}\n'
            '\\begin{document}\n'
        )

    outstr += (
        '\\begin{center}\n'
        '\\begin{table}\n'
        '\\begin{tabular}{c@{\hspace{1em}} | l | c | c |}\n'
        '\\cline{2-4}\n'
        '& Fitting model type &\n'
        'Position error $\\langle |\\vec{r}_{\\rm{fit}}-\\vec{r}_{\\rm{true}}|\\rangle$ &\n'
        'Radius error $\\langle a_{\\rm{fit}}-a_{\\rm{true}}\\rangle$\\\\ \\hline \\hline\n'
    )

    for sec, table in zip(sections, tables):
        ss = max([len(i[0]) for i in table]) + 3

        outstr += '\\multirow{5}{*}{\\rotatebox{90}{\\textbf{%s}}}\n' % sec
        for row in table:
            v = [numform2(i) for i in row[1:]]
            outstr += "& {:<{}s} & ${:s}$ & ${:s}$ \\\\ \\cline{{2-4}}\n".format(row[0], ss, *v)
        outstr += '\\hline\n'

    outstr += (
        '\\end{tabular}\n'
        '\\caption{\\textbf{Position and radii errors by model complexity}}\n'
        '\\label{table:model_complexity}\n'
        '\\end{table}\n'
        '\\end{center}\n'
    )

    if fulldocument:
        outstr += '\\end{document}'

    return outstr

def make_all_plots(results, categories=['Platonic', 'Illumination', 'PSF']):
    rows = len(results)
    cols = len(results[0])

    size = 3
    fig = pl.figure(figsize=(cols*size, rows*size))
    img = ImageGrid(
        fig, rect=[0.025, 0.025, 0.95, 0.95],
        nrows_ncols=[rows, cols], axes_pad=0.4
    )

    for i, (label, result, cat) in enumerate(zip('ABCDE', results, categories)):
        make_plots(result, [img[i*cols + j] for j in range(cols)], label=None, sidelabel=cat)

def make_plots(results, img=None, label='', sidelabel=''):
    ln = len(results)

    if img is None:
        size = 3
        fig = pl.figure(figsize=(ln*size, size+2.0/ln))
        img = ImageGrid(
            fig, rect=[0.05/ln, 0.05, 1-0.1/ln, 0.90],
            nrows_ncols=[1, ln], axes_pad=0.1
        )

    # get a common color bar scale for all images
    mins, maxs = [], []
    for i, v in enumerate(results):
        if v[0] == 'Reference':
            continue
        mins.append(v[1].min())
        maxs.append(v[1].max())
    mins = min(mins)
    maxs = max(maxs)

    mins = -0.5*max(np.abs([mins, maxs]))
    maxs = -mins

    for i, v in enumerate(results):
        if v[0] == 'Reference':
            img[i].imshow(v[1], vmin=0, vmax=1, cmap='bone')
        else:
            img[i].imshow(v[1], vmin=mins, vmax=maxs)

        img[i].set_title(v[0], fontsize=17)
        img[i].set_xticks([])
        img[i].set_yticks([])

        if label:
            lbl(img[i], label+str(i+1), 18)

        if i == 0 and sidelabel:
            img[i].set_ylabel(sidelabel)

def error_level(state, particle):
    f = state.fisher_information(state.blocks_particle(particle))
    e = np.sqrt(np.diag(np.linalg.inv(f)))
    pos = np.sqrt((e[:3]**2).sum())
    rad = e[-1]
    return pos, rad

def average_error(state):
    particles = np.random.choice(state.N, 12)
    pos, rad = [], []
    for i, particle in enumerate(particles):
        p, r = error_level(state, particle)
        print(i, particle, p, r)
        pos.append(p)
        rad.append(r)
    pos, rad = np.array(pos), np.array(rad)
    return np.median(pos), np.median(rad)

