import numpy as np

import peri
from peri import initializers
import peri.opt.optimize as opt

from peri.logger import log
CLOG = log.getChild('addsub')

def feature_guess(st, rad, invert=True, minmass=None, use_tp=False, **kwargs):
    if minmass == None:
        #30% of the feature size mass is a good cutoff empirically for
        #initializers.local_max_featuring, less for trackpy;
        #it's easier to remove than to add
        minmass = rad**3 * 4/3.*np.pi * 0.3
        if use_tp:
            minmass *= 0.1 #magic #; works well
    if invert:
        im = 1 - st.residuals
    else:
        im = st.residuals
    if use_tp:
        diameter = np.ceil(2*rad)
        diameter += 1-(diameter % 2)
        df = peri.trackpy.locate(im, int(diameter), minmass = minmass)
        npart = np.array(df['mass']).size
        guess = np.zeros([npart,3])
        guess[:,0] = df['z']
        guess[:,1] = df['y']
        guess[:,2] = df['x']
        mass = df['mass']
    else:
        guess, _, mass = initializers.local_max_featuring(im, radius=rad, masscut=minmass)
        npart = guess.shape[0]
    #I want to return these sorted by mass:
    inds = np.argsort(mass)[::-1] #biggest mass first
    return guess[inds].copy(), npart

def check_add_particles(st, guess, rad='calc', do_opt=True, opt_box_scale=2.5,
        **kwargs):
    """
    comments
    st = state
    guess = list-like of poses to check to add,
    rad = radius to add at. Default is 'calc' = np.median(st.obj.rad)
    im_change_frac : 0.2, how good the change in error needs to be relative
        to the change in the difference image.

    """
    accepts = 0
    new_poses = []
    if rad == 'calc':
        rad = np.median(st.obj_get_radii())
    message = '-'*30 + 'ADDING' + '-'*30 + '\n  Z\t  Y\t  X\t  R\t|\t ERR0\t\t ERR1'
    with log.noformat():
        CLOG.info(message)
    for a in xrange(guess.shape[0]):
        p = guess[a]
        old_err = st.error
        ind = st.obj_add_particle(p, rad)
        if do_opt:
            opt.do_levmarq_particles(st, np.array([ind],dtype='int'),
                    damping=1.0, max_iter=2, run_length=3, eig_update=False,
                    include_rad=False)
        did_kill, p, r = check_remove_particle(st, ind, **kwargs)
        if not did_kill:
            accepts += 1
            new_poses.append(p)
            part_msg = '%2.2f\t%3.2f\t%3.2f\t%3.2f\t|\t%4.3f  \t%4.3f' % (
                    p + r + (old_err, st.error))
            with log.noformat():
                CLOG.info(part_msg)
    return accepts, new_poses

def check_remove_particle(st, ind, im_change_frac=0.2, min_derr='3sig', **kwargs):
    """
    Checks whether to remove particle 'ind' from state 'st'. If removing the
    particle increases the error by less than max( min_derr, change in image *
            im_change_frac), then the particle is removed.
    """
    if min_derr == '3sig':
        min_derr = 3 * st.sigma
    present_err = st.error; present_d = st.residuals.copy()
    p, r = st.obj_remove_particle(ind)
    absent_err = st.error; absent_d = st.residuals.copy()

    im_change = np.sum((present_d - absent_d)**2)
    if (absent_err - present_err) >= max([im_change_frac * im_change, min_derr]):
        st.obj_add_particle(p, r)
        killed = False
    else:
        killed = True
    return killed, tuple(p), (r,)

def sample_n_add(st, rad='calc', tries=20, **kwargs):
    """
    do_opt=True, im_change_frac=0.2, opt_box_scale=3,
    """
    if rad == 'calc':
        rad = np.median(st.obj_get_radii())

    guess, npart = feature_guess(st, rad, **kwargs)
    tries = np.min([tries, npart])

    accepts, new_poses = check_add_particles(st, guess[:tries], rad=rad,
            **kwargs)
    return accepts, new_poses

def remove_bad_particles(st, min_rad=2.0, max_rad=12.0, min_edge_dist=2.0,
        check_rad_cutoff=[3.5,15], check_outside_im=True, tries=100,
        im_change_frac=0.2, **kwargs):
    """
    Same syntax as before, but here I'm just trying to kill the smallest particles...
    I don't think this is good because you only check the same particles each time
    Updates a single particle (labeled ind) in the state st.

    Parameters
    -----------
    min_rad : Float
        All particles with radius below min_rad are automatically deleted.
        Set to 'calc' to make it the median rad - 15* radius std.
        Default is 2.0

    max_rad : Float
        All particles with radius above max_rad are automatically deleted.
        Set to 'calc' to make it the median rad + 15* radius std.
        Default is 12.0

    min_edge_dist : Float
        All particles within min_edge_dist of the (padded) image
        edges are automatically deleted. Default is 2.0

    check_rad_cutoff : 2-element list of floats
        Particles with radii < check_rad_cutoff[0] or > check_rad_cutoff[1]
        are checked if they should be deleted. Set to 'calc' to make it the
        median rad +- 3.5 * radius std. Default is [3.5, 15].

    check_outside_im : Bool
        If True, checks if particles located outside the unpadded image
        should be deleted. Default is True.

    tries : Int
        The maximum number of particles with radii < check_rad_cutoff
        to try to remove. Checks in increasing order of radius size.
        Default is 100.

    im_change_frac : Float, between 0 and 1.
        If removing a particle decreases the error less than im_change_frac*
        the change in the image, the particle is deleted. Default is 0.2.

    Returns
    -----------
    removed: Int
        The cumulative number of particles removed.

    """
    is_near_im_edge = lambda pos, pad: ((pos < pad) | (pos >
            np.array(st.oshape.shape) - pad)).any(axis=1)
    removed = 0
    attempts = 0

    n_tot_part = st.obj_get_positions().shape[0]
    q10 = int(0.1 * n_tot_part)#10% quartile
    r_sig = np.sort(st.obj_get_radii())[q10:-q10].std()
    r_med = np.median(st.obj_get_radii())
    if max_rad == 'calc':
        max_rad = r_med + 15*r_sig
    if min_rad == 'calc':
        min_rad = r_med - 25*r_sig
    if check_rad_cutoff == 'calc':
        check_rad_cutoff = [r_med - 7.5*r_sig, r_med + 7.5*r_sig]

    #1. Automatic deletion:
    rad_wrong_size = np.nonzero((st.obj_get_radii() < min_rad) |
            (st.obj_get_radii() > max_rad))[0]
    near_im_edge = np.nonzero(is_near_im_edge(st.obj_get_positions(),
            min_edge_dist - st.pad))[0]
    delete_inds = np.unique(np.append(rad_wrong_size, near_im_edge)).tolist()
    delete_poses = st.obj_get_positions()[delete_inds].tolist()
    message = '-'*27 + 'SUBTRACTING' + '-'*28 + '\n  Z\t  Y\t  X\t  R\t|\t ERR0\t\t ERR1'
    with log.noformat():
        CLOG.info(message)

    for pos in delete_poses:
        ind = st.obj_closest_particle(pos)
        old_err = st.error
        p, r = st.obj_remove_particle(ind)
        part_msg = '%2.2f\t%3.2f\t%3.2f\t%3.2f\t|\t%4.3f  \t%4.3f' % (
                tuple(p) + (r,) + (old_err, st.error))
        with log.noformat():
            CLOG.info(part_msg)
        removed += 1

    #2. Conditional deletion:
    check_rad_inds = np.nonzero((st.obj_get_radii() < check_rad_cutoff[0]) |
            (st.obj_get_radii() > check_rad_cutoff[1]))[0]
    if check_outside_im:
        check_edge_inds= np.nonzero(is_near_im_edge(st.obj_get_positions(),
                st.pad))[0]
        check_inds = np.unique(np.append(check_rad_inds, check_edge_inds))
    else:
        check_inds = check_rad_inds

    check_inds = check_inds[np.argsort(st.obj_get_radii()[check_inds])]
    tries = np.max([tries, check_inds.size])
    check_poses = st.obj_get_positions()[check_inds[:tries]].copy()
    for pos in check_poses:
        old_err = st.error
        ind = st.obj_closest_particle(pos)
        killed, p, r = check_remove_particle(st, ind, im_change_frac=im_change_frac)
        if killed:
            removed += 1
            check_inds[check_inds > ind] -= 1  #cleaning up indices....
            delete_poses.append(pos)
            part_msg = '%2.2f\t%3.2f\t%3.2f\t%3.2f\t|\t%4.3f  \t%4.3f' % (
                    p + r + (old_err, st.error))
            with log.noformat():
                CLOG.info(part_msg)
    return removed, delete_poses

def add_subtract(st, max_iter=5, **kwargs):
    """
    Automatically adds and subtracts missing & extra particles.

    Parameters
    ----------
        st: ConfocalImagePython
            The state to add and subtract particles to.
        max_iter : Int
            The maximum number of add-subtract loops to use. Default is 5.
            Terminates after either max_iter loops or when nothing has
            changed.

    **kwargs Parameters
    -------------------
        invert : Bool
            True if the particles are dark on a bright background, False
            if they are bright on a dark background. Default is True.
        min_rad : Float
            Particles with radius below min_rad are automatically deleted.
            Default is 2.0.
        max_rad : Float
            Particles with radius below min_rad are automatically deleted.
            Default is 12.0, but you should change this for your partilce
            sizes.
        min_edge_dist : Float
            Particles closer to the edge of the padded image than this
            are automatically deleted. Default is 2.0.
        check_rad_cutoff : 2-element float list.
            Particles with radii < check_rad_cutoff[0] or > check...[1]
            are checked if they should be deleted (not automatic).
            Default is [3.5, 15].
        check_outside_im : Bool
            Set to True to check whether to delete particles whose
            positions are outside the un-padded image.

        rad : Float
            The initial radius for added particles; added particles radii
            are not fit until the end of add_subtract. Default is 'calc',
            which uses the median radii of active particles.

        tries :
        im_change_frac
        min_derr : Float
            The minimum Default is '3sig' which uses 3*st.sigma.

        do_opt : Bool
            Set to False to avoid optimizing particle positions after
            adding them.
        minmass : Float

        use_tp : Bool
            Set to True to use trackpy to find missing particles inside
            the image. Not recommended since it trackpy deliberately
            cuts out particles at the edge of the image. Default is False.


    Outputs
    -------
        total_changed : Int.
            The total number of adds and subtracts done on the data.
            Not the same as changed_inds.size since the same particle
            or particle index can be added/subtracted multiple times.
        added_positions : [N_added,3] numpy.ndarray
            The positions of particles that have been added at any point in
            the add-subtract cycle.
        removed_positions : [N_added,3] numpy.ndarray
            The positions of particles that have been removed at any point in
            the add-subtract cycle.

    Comments
    --------
        Occasionally after the intial featuring a cluster of particles
        is featured as 1 big particle. To fix these mistakes, it helps
        to set max_rad to a physical value. This removes the big particle
        and allows it to be re-featured by (several passes of) the adding
        portion.
        The added/removed positions returned are whether or not the position
        has been added or removed ever. It's possible that a position is
        added, then removed during a later iteration.

    To implement
    ------------
        A way to check regions that are poorly fit (e.g. skew- or kurtosis-
        hunt).
    """
    total_changed = 0
    removed_poses = []
    added_poses0 = []
    added_poses = []

    for _ in xrange(max_iter):
        nr, rposes = remove_bad_particles(st, **kwargs)
        na, aposes = sample_n_add(st, **kwargs)
        current_changed = na + nr
        removed_poses.extend(rposes)
        added_poses0.extend(aposes)
        total_changed += current_changed
        if current_changed == 0:
            break

    #Now we optimize the radii too:
    for p in added_poses0:
        i = st.obj_closest_particle(p)
        opt.do_levmarq_particles(st, np.array([i]), max_iter=2, damping=0.3)
        added_poses.append(st.obj_get_positions()[i])
    return total_changed, np.array(removed_poses), np.array(added_poses)
