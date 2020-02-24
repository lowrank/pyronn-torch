#
# Copyright © 2020 Stephan Seitz <stephan.seitz@fau.de>
#
# Distributed under terms of the GPLv3 license.

"""

"""


import argparse
from glob import glob
from os import makedirs
from os.path import basename, dirname, join
from shutil import copyfile, copytree, rmtree

import pystencils
from pystencils.astnodes import Block
from pystencils.cpu.cpujit import get_cache_config
from pystencils.data_types import TypedSymbol, create_type
from pystencils.kernelparameters import FieldPointerSymbol, FieldShapeSymbol
from pystencils_autodiff.backends.astnodes import TorchModule
from pystencils_autodiff.framework_integration.astnodes import (
    CustomFunctionCall, WrapperFunction)
from pystencils_autodiff.framework_integration.printer import \
    FrameworkIntegrationPrinter

volume = pystencils.fields('volume: float32[3d]')
projection = pystencils.fields('projection: float32[2d]')
projection_matrices = pystencils.fields('matrices: float32[3d]')
inv_matrices = pystencils.fields('inv_matrices: float32[3d]')
source_points = pystencils.fields('source_points: float32[1d]')

FUNCTIONS = {
        'Cone_Backprojection3D_Kernel_Launcher': CustomFunctionCall('Cone_Backprojection3D_Kernel_Launcher',
                                             FieldPointerSymbol(projection.name, projection.dtype, const=True),
                                             FieldPointerSymbol(volume.name, volume.dtype, const=False),
                                             FieldPointerSymbol(projection_matrices.name,
                                                                projection_matrices.dtype, const=True),
                                             FieldShapeSymbol(['matrices'], 0),
                                             *[FieldShapeSymbol(['volume'], i) for i in range(2, -1, -1)],
                                             TypedSymbol('volume_spacing_x', create_type('float32'), const=True),
                                             TypedSymbol('volume_spacing_y', create_type('float32'), const=True),
                                             TypedSymbol('volume_spacing_z', create_type('float32'), const=True),
                                             TypedSymbol('volume_origin_x', create_type('float32'), const=True),
                                             TypedSymbol('volume_origin_y', create_type('float32'), const=True),
                                             TypedSymbol('volume_origin_z', create_type('float32'), const=True),
                                             *[FieldShapeSymbol(['projection'], i) for i in range(1, -1, -1)],
                                             TypedSymbol('projection_multiplier', create_type('float32'), const=True),
                                             fields_accessed=[volume, projection, projection_matrices], custom_signature="""
void Cone_Backprojection3D_Kernel_Launcher(const float *sinogram_ptr, float *out, const float *projection_matrices, const int number_of_projections,
                                          const int volume_width, const int volume_height, const int volume_depth,
                                          const float volume_spacing_x, const float volume_spacing_y, const float volume_spacing_z,
                                          const float volume_origin_x, const float volume_origin_y, const float volume_origin_z,
                                          const int detector_width, const int detector_height, const float projection_multiplier);
"""),  # noqa
'Cone_Projection_Kernel_Launcher': CustomFunctionCall('Cone_Projection_Kernel_Launcher',
                                             FieldPointerSymbol(volume.name, volume.dtype, const=True),
                                             FieldPointerSymbol(projection.name, projection.dtype, const=False),
                                             FieldPointerSymbol(inv_matrices.name,
                                                                inv_matrices.dtype, const=True),
                                             FieldPointerSymbol(source_points.name,
                                                                source_points.dtype, const=True),
                                             FieldShapeSymbol([source_points.name], 0),
                                             *[FieldShapeSymbol(['volume'], i) for i in range(2, -1, -1)],
                                             TypedSymbol('volume_spacing_x', create_type('float32'), const=True),
                                             TypedSymbol('volume_spacing_y', create_type('float32'), const=True),
                                             TypedSymbol('volume_spacing_z', create_type('float32'), const=True),
                                             *[FieldShapeSymbol(['projection'], i) for i in range(1, -1, -1)],
                                             TypedSymbol('step_size', create_type('float32'), const=True),
                                             fields_accessed=[volume, projection, inv_matrices, source_points], custom_signature="""
void Cone_Projection_Kernel_Launcher(const float* volume_ptr, float *out, const float *inv_AR_matrix, const float *src_points, 
                                    const int number_of_projections, const int volume_width, const int volume_height, const int volume_depth, 
                                    const float volume_spacing_x, const float volume_spacing_y, const float volume_spacing_z,
                                    const int detector_width, const int detector_height, const float step_size);
"""),  # noqa
'Cone_Projection_Kernel_Tex_Interp_Launcher': CustomFunctionCall('Cone_Projection_Kernel_Tex_Interp_Launcher',
                                             FieldPointerSymbol(volume.name, volume.dtype, const=True),
                                             FieldPointerSymbol(projection.name, projection.dtype, const=False),
                                             FieldPointerSymbol(inv_matrices.name,
                                                                inv_matrices.dtype, const=True),
                                             FieldPointerSymbol(source_points.name,
                                                                source_points.dtype, const=True),
                                             FieldShapeSymbol([source_points.name], 0),
                                             *[FieldShapeSymbol(['volume'], i) for i in range(2, -1, -1)],
                                             TypedSymbol('volume_spacing_x', create_type('float32'), const=True),
                                             TypedSymbol('volume_spacing_y', create_type('float32'), const=True),
                                             TypedSymbol('volume_spacing_z', create_type('float32'), const=True),
                                             *[FieldShapeSymbol(['projection'], i) for i in range(1, -1, -1)],
                                             TypedSymbol('step_size', create_type('float32'), const=True),
                                             fields_accessed=[volume, projection, inv_matrices, source_points], custom_signature="""
void Cone_Projection_Kernel_Tex_Interp_Launcher(
    const float *__restrict__ volume_ptr, float *out,
    const float *inv_AR_matrix, const float *src_points,
    const int number_of_projections, const int volume_width,
    const int volume_height, const int volume_depth,
    const float volume_spacing_x, const float volume_spacing_y,
    const float volume_spacing_z, const int detector_width,
    const int detector_height, const float step_size);"""),  # noqa
        }


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--output-folder',  default=join(dirname(__file__), '..', 'src', 'pyronn_torch'))
    parser.add_argument('--source-files',  default=glob(join(dirname(__file__),
                                                             '..', 'src', 'pyronn_torch', 'PYRO-NN-Layers', '*.cu.cc')))
    args = parser.parse_args()
    object_cache = get_cache_config()['object_cache']

    module_name = 'PYRO_NN'

    cuda_sources = []
    makedirs(join(object_cache, module_name), exist_ok=True)
    rmtree(join(object_cache, module_name, 'helper_headers'))
    copytree(join(dirname(__file__), '..', 'src', 'pyronn_torch',
                  'PYRO-NN-Layers', 'helper_headers'), join(object_cache, module_name, 'helper_headers'))

    for s in args.source_files:
        dst = join(object_cache, module_name, basename(s).replace('.cu.cc', '.cu'))
        copyfile(s, dst)  # Torch only accepts *.cu as CUDA
        cuda_sources.append(dst)

    functions = [WrapperFunction(Block([v]), function_name=k) for k, v in FUNCTIONS.items()]
    module = TorchModule(module_name, functions, wrap_wrapper_functions=True)

    pystencils.show_code(module, custom_backend=FrameworkIntegrationPrinter())

    extension = module.compile(extra_source_files=cuda_sources, extra_cuda_flags=['-arch=sm_35'], with_cuda=True)

    for v in extension.__dict__.values():
        if hasattr(v, '__doc__'):
            print(v.__doc__)


if __name__ == '__main__':
    main()
