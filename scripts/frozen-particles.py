import matplotlib as mpl
mpl.use('Agg')
import numpy as np
import pylab as pl
import pickle

from cbamf import states, runner, initializers
from cbamf.comp import objs, psfs, ilms
from cbamf.viz import plots

def pad_fake_particles(pos, rad, nfake):
    opos = np.vstack([pos, np.zeros((nfake, 3))])
    orad = np.hstack([rad, rad[0]*np.ones(nfake)])
    return opos, orad

def zero_particles(n):
    return np.zeros((n,3)), np.ones(n), np.zeros(n)

#raise IOError
ORDER = (3,3,2)
sweeps = 30
samples = 20
burn = sweeps - samples

sigma = 0.05
PSF = (2.4, 4.6)
PAD, FSIZE, RAD, INVERT, IMSIZE, zstart, zscale = 16, 5, 5.0, True, 72, 14, 1.056
raw = initializers.load_tiff("/media/scratch/bamf/frozen-particles/zstack_dx0/0.tif")

feat = initializers.normalize(raw[zstart:,:IMSIZE,:IMSIZE], INVERT)
feat = initializers.remove_background(feat, order=ORDER)
xstart, proc = initializers.local_max_featuring(feat, FSIZE, FSIZE/3.)
#xstart, rstart = pickle.load(open("/media/scratch/fff.pkl"))

itrue = initializers.normalize(raw[zstart:,:IMSIZE,:IMSIZE], not INVERT)
itrue = np.pad(itrue, PAD, mode='constant', constant_values=-10)
xstart += PAD
rstart = RAD*np.ones(xstart.shape[0])
initializers.remove_overlaps(xstart, rstart, zscale=zscale)
nfake = 100
#xstart, rstart, tstart = zero_particles(nfake)
xstart, rstart = pad_fake_particles(xstart, rstart, nfake)

imsize = itrue.shape
obj = objs.SphereCollectionRealSpace(pos=xstart, rad=rstart, shape=imsize, pad=nfake)
psf = psfs.AnisotropicGaussian(PSF, shape=imsize)
ilm = ilms.LegendrePoly3D(order=ORDER, shape=imsize)
ilm.from_data(itrue, mask=itrue > -10)

diff = (ilm.get_field() - itrue)
params = ilm.get_params()
params[0] += diff[itrue > -10].max() / 2
#params = np.load("/media/scratch/bamf/frozen-particles/ilm.npy")
ilm.update(params)

s = states.ConfocalImagePython(itrue, obj=obj, psf=psf, ilm=ilm,
        zscale=zscale, pad=16, sigma=sigma, constoff=True, offset=0.45,
        doprior=False)

import scipy.ndimage as nd

def sample_particle_add(s, rad, tries=5):
    diff = (s.get_model_image() - s.image).copy()

    smoothdiff = nd.gaussian_filter(diff, rad/2.0)
    maxfilter = nd.maximum_filter(smoothdiff, size=rad)
    eq = smoothdiff == maxfilter
    lbl = nd.label(eq)[0]
    pos = np.array(nd.center_of_mass(eq, lbl, np.unique(lbl)))[1:].astype('int')
    ind = np.arange(len(pos))

    val = [maxfilter[tuple(pos[i])] for i in ind]
    vals = sorted(zip(val, ind))

    accepts = 0
    for _, i in vals[-tries:][::-1]:
        diff = (s.get_model_image() - s.image)/(2*s.sigma**2)

        p = pos[i].reshape(-1,3)
        n = s.obj.typ.argmin()

        bp = s.block_particle_pos(n)
        br = s.block_particle_rad(n)
        bt = s.block_particle_typ(n)

        s.update(bp, p)
        s.update(br, np.array([rad]))
        s.update(bt, np.array([1]))

        bl = s.blocks_particle(n)[:-1]
        runner.sample_state(s, bl, stepout=1, N=1)

        diff2 = (s.get_model_image() - s.image)/(2*s.sigma**2)

        print p, (diff**2).sum(), (diff2**2).sum()
        if not (np.log(np.random.rand()) > (diff2**2).sum() - (diff**2).sum()):
            s.update(bt, np.array([0]))
        else:
            accepts += 1
    return accepts

def sample_particle_remove(s, rad, tries=5):
    diff = (s.get_model_image() - s.image).copy()

    smoothdiff = nd.gaussian_filter(diff, rad/2.0)
    maxfilter = nd.maximum_filter(smoothdiff, size=rad)
    eq = smoothdiff == maxfilter
    lbl = nd.label(eq)[0]
    pos = np.array(nd.center_of_mass(eq, lbl, np.unique(lbl)))[1:].astype('int')
    ind = np.arange(len(pos))

    val = [maxfilter[tuple(pos[i])] for i in ind]
    vals = sorted(zip(val, ind))

    accepts = 0
    for _, i in vals[-tries:]:
        diff = (s.get_model_image() - s.image)/(2*s.sigma**2)

        n = ((s.obj.pos - pos[i])**2).sum(axis=0).argmin()

        bt = s.block_particle_typ(n)
        s.update(bt, np.array([0]))

        diff2 = (s.get_model_image() - s.image)/(2*s.sigma**2)

        print s.obj.pos[n], (diff**2).sum(), (diff2**2).sum()
        if not (np.log(np.random.rand()) > (diff2**2).sum() - (diff**2).sum()):
            s.update(bt, np.array([1]))
        else:
            accepts += 1
    return accepts

def full_feature(s, rad, globaloptimizes=2, add_remove_tries=20):
    for i in xrange(globaloptimizes):
        accepts = 1
        while accepts > 0:
            accepts = 0
            accepts += sample_particle_add(s, rad=rad, tries=add_remove_tries)
            accepts += sample_particle_remove(s, rad=rad, tries=add_remove_tries/5)
            runner.sample_particle_pos(s, stepout=1)
            runner.sample_block(s, 'ilm', stepout=0.1)
            runner.sample_block(s, 'off', stepout=0.1)

        for i in xrange(2):
            runner.sample_particle_pos(s, stepout=1)
            runner.sample_particle_rad(s, stepout=1)

        runner.do_samples(s, 5, 5)

    return runner.do_samples(s, 20, 10)