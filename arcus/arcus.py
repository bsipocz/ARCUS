import os

import numpy as np
import xlrd
from scipy.interpolate import interp1d
import transforms3d

import marxs
from marxs.simulator import Sequence, KeepCol
from marxs.optics import (GlobalEnergyFilter, EnergyFilter,
                          FlatDetector, CATGrating,
                          PerfectLens, RadialMirrorScatter)
from marxs import optics
from marxs.design.rowland import (RowlandTorus, design_tilted_torus,
                                  GratingArrayStructure,
                                  RectangularGrid,
                                  LinearCCDArray, RowlandCircleArray)
import marxs.analysis

from read_grating_data import InterpolateRalfTable

path = os.path.dirname(__file__)

# Reading in data for grating reflectivity, filtercurves etc.
arcusefficiencytable = xlrd.open_workbook(os.path.join(path, '../inputdata/ArcusEffectiveArea-v3.xls'))
mastersheet = arcusefficiencytable.sheet_by_name('Master')
energy = np.array(mastersheet.col_values(0, start_rowx=6)) / 1000.  # ev to keV
spogeometricthroughput = np.array(mastersheet.col_values(3, start_rowx=6))
doublereflectivity = np.array(mastersheet.col_values(4, start_rowx=6))
sifiltercurve = np.array(mastersheet.col_values(20, start_rowx=6))
uvblocking = np.array(mastersheet.col_values(21, start_rowx=6))
opticalblocking = np.array(mastersheet.col_values(22, start_rowx=6))
ccdcontam = np.array(mastersheet.col_values(23, start_rowx=6))
qebiccd = np.array(mastersheet.col_values(24, start_rowx=6))


blazeang = 1.91

alpha = np.deg2rad(2 * blazeang)
beta = np.deg2rad(4 * blazeang)
R, r, pos4d = design_tilted_torus(12e3, alpha, beta)
rowland = RowlandTorus(R, r, pos4d=pos4d)

Rm, rm, pos4dm = design_tilted_torus(12e3, - alpha, -beta)
rowlandm = RowlandTorus(Rm, rm, pos4d=pos4dm)
d = r * np.sin(alpha)
shift_optical_axis = np.eye(4)
shift_optical_axis[1, 3] = 2. * d
rowlandm.pos4d = np.dot(shift_optical_axis, rowlandm.pos4d)


mirrorefficiency = GlobalEnergyFilter(filterfunc=interp1d(energy, spogeometricthroughput * doublereflectivity))

entrancepos = np.array([12000., 0., 0.])

# Set a little above entrance pos (the mirror) for display purposes.
# Thus, needs to be geometrically bigger for off-axis sources.

# aper = optics.CircleAperture(position=[12200, 0, 0], zoom=300,
#                       phi=[-0.3 + np.pi / 2, .3 + np.pi / 2])\

aper_rect1 = optics.RectangleAperture(position=[12200, 0, 550], zoom=[1, 180, 250])
aper_rect2 = optics.RectangleAperture(position=[12200, 0, -550], zoom=[1, 180, 250])

aper_rect1m = optics.RectangleAperture(pos4d=np.dot(shift_optical_axis, aper_rect1.pos4d))
aper_rect2m = optics.RectangleAperture(pos4d=np.dot(shift_optical_axis, aper_rect2.pos4d))

aper = optics.MultiAperture(elements=[aper_rect1, aper_rect2])
aperm = optics.MultiAperture(elements=[aper_rect1m, aper_rect2m])

lens = PerfectLens(focallength=12000., position=entrancepos)
lensm = PerfectLens(focallength=12000., pos4d=np.dot(shift_optical_axis, lens.pos4d))
# Scatter as FWHM ~8 arcsec. Divide by 2.3545 to get Gaussian sigma.
rms = RadialMirrorScatter(inplanescatter=8. / 2.3545 / 3600 / 180. * np.pi,
                          perpplanescatter=1. / 2.345 / 3600. / 180. * np.pi,
                          position=entrancepos)

rmsm = RadialMirrorScatter(inplanescatter=8. / 2.3545 / 3600 / 180. * np.pi,
                           perpplanescatter=1. / 2.345 / 3600. / 180. * np.pi,
                           pos4d=np.dot(shift_optical_axis, rms.pos4d))


mirror = Sequence(elements=[lens, rms, mirrorefficiency])
mirrorm = Sequence(elements=[lensm, rmsm, mirrorefficiency])


# CAT grating
ralfdata = os.path.join(path, '../inputdata/Si_4um_deep_30pct_dc.xlsx')
order_selector = InterpolateRalfTable(ralfdata)

# Define L1, L2 blockage as simple filters due to geometric area
# L1 support: blocks 18 %
# L2 support: blocks 19 %
catsupport = GlobalEnergyFilter(filterfunc=lambda e: 0.81 * 0.82)


class CATSupportbars(marxs.optics.base.OpticalElement):
    '''Metal structure that holds grating facets will absorb all photons
    that do not pass through a grating facet.

    We might want to call this L3 support ;-)
    '''
    def process_photons(self, photons):
        photons['probability'][photons['facet'] < 0] = 0.
        return photons

catsupportbars = CATSupportbars()

blazemat = transforms3d.axangles.axangle2mat(np.array([0, 0, 1]), np.deg2rad(-blazeang))
blazematm = transforms3d.axangles.axangle2mat(np.array([0, 0, 1]), np.deg2rad(blazeang))

gratinggrid = {'rowland': rowland, 'd_element': 32., 'x_range': [1e4, 1.4e4],
               'elem_class': CATGrating,
               'elem_args': {'d': 2e-4, 'zoom': [1., 15., 15.], 'orientation': blazemat,
                             'order_selector': order_selector}
              }
gas_1 = RectangularGrid(z_range=[300, 800], y_range=[-180, 180], **gratinggrid)
gas_2 = RectangularGrid(z_range=[-800, -300], y_range=[-180, 180],
                        id_num_offset=1000, **gratinggrid)
gas = Sequence(elements=[gas_1, gas_2, catsupport, catsupportbars])

gratinggrid['rowland'] = rowlandm
gratinggrid['elem_args']['orientation'] = blazematm
gas_1m = RectangularGrid(z_range=[300, 800], y_range=[-180 + 2 * d, 180 + 2 * d],
                         normal_spec=np.array([0, 2 * d, 0, 1.]),
                         id_num_offset=2000, **gratinggrid)
gas_2m = RectangularGrid(z_range=[-800, -300], y_range=[-180 + 2* d, 180 + 2 * d],
                         normal_spec=np.array([0, 2 * d, 0, 1.]),
                         id_num_offset=3000, **gratinggrid)
gasm = Sequence(elements=[gas_1m, gas_2m, catsupport, catsupportbars])


flatstackargs = {'zoom': [1, 24.576, 12.288],
                 'elements': [EnergyFilter, FlatDetector],
                 'keywords': [{'filterfunc': interp1d(energy, sifiltercurve * uvblocking * opticalblocking * ccdcontam * qebiccd)}, {'pixsize': 0.024}]
                 }
# 500 mu gap between detectors

det = RowlandCircleArray(rowland=rowland, elem_class=marxs.optics.FlatStack,
                         elem_args=flatstackargs, d_element=49.652,
                         theta=[np.pi - 0.2, np.pi + 0.5])

# This is just one way to establish a global coordinate system for
# detection on detectors that follow a curved surface.
# Project (not propagate) down to the focal plane.
projectfp = marxs.analysis.ProjectOntoPlane()

# Place an additional detector on the Rowland circle.
detcirc = marxs.optics.CircularDetector.from_rowland(rowland, width=20)
detcirc.loc_coos_name = ['detcirc_phi', 'detcirc_y']
detcirc.detpix_name = ['detcircpix_x', 'detcircpix_y']
detcirc.display['opacity'] = 0.1

# Place an additional detector in the focal plane for comparison
# Detectors are transparent to allow this stuff
detfp = marxs.optics.FlatDetector(zoom=[.2, 10000, 10000])
detfp.loc_coos_name = ['detfp_x', 'detfp_y']
detfp.detpix_name = ['detfppix_x', 'detfppix_y']
detfp.display['opacity'] = 0.1

### Put together ARCUS in different configurations ###
arcus = Sequence(elements=[aper, mirror, gas, det, projectfp])
arcusm = Sequence(elements=[aperm, mirrorm, gasm, det, projectfp])


keeppos = KeepCol('pos')
keepposm = KeepCol('pos')

arcus_extra_det = Sequence(elements=[aper, mirror, gas, detcirc, det, projectfp, detfp],
                   postprocess_steps=[keeppos])

arcus_extra_det_m = Sequence(elements=[aperm, mirrorm, gasm, detcirc, det, projectfp, detfp],
                    postprocess_steps=[keepposm])

# No detector effects - Joern's simulator handles that itself.
arcus_joern = Sequence(elements=[aper, mirror, gas, detfp])