# Copyright (C) 2020 NumS Development Team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import logging
import sys

import numpy as np

from nums.core import settings
from nums.core.array.application import ArrayApplication
from nums.core.compute import numpy_compute
from nums.core.compute.compute_manager import ComputeManager
from nums.core.grid.grid import DeviceGrid, CyclicDeviceGrid, PackedDeviceGrid
from nums.core.systems.filesystem import FileSystem
from nums.core.systems.system_interface import SystemInterface
from nums.core.systems.systems import SerialSystem, RaySystem, RaySystemStockScheduler

# pylint: disable=global-statement


_instance: ArrayApplication = None
_call_on_create: list = []


def call_on_create(func):
    global _call_on_create
    # Always include funcs in _call_on_create.
    # If the app is destroyed, the hooks need to be invoked again on creation.
    _call_on_create.append(func)
    if is_initialized():
        func(_instance)


def is_initialized():
    return _instance is not None


def instance():
    # Lazy-initialize to initialize on use instead of initializing on import.
    global _instance
    if _instance is None:
        _instance = create()
        for func in _call_on_create:
            func(_instance)
    return _instance


def create():
    configure_logging()

    global _instance

    if _instance is not None:
        raise Exception("create() called more than once.")

    # Initialize compute interface and system.
    system_name = settings.system_name
    if system_name == "serial":
        system: SystemInterface = SerialSystem(settings.num_cpus)
    elif system_name == "ray":
        use_head = settings.use_head
        num_nodes = int(np.product(settings.cluster_shape))
        system: SystemInterface = RaySystem(
            address=settings.address,
            use_head=use_head,
            num_nodes=num_nodes,
            num_cpus=settings.num_cpus,
        )
    elif system_name == "ray-scheduler":
        use_head = settings.use_head
        num_nodes = int(np.product(settings.cluster_shape))
        system: SystemInterface = RaySystemStockScheduler(
            address=settings.address,
            use_head=use_head,
            num_nodes=num_nodes,
            num_cpus=settings.num_cpus,
        )
    elif system_name == "dask":
        # pylint: disable=import-outside-toplevel
        from nums.experimental.nums_dask.dask_system import DaskSystem

        num_nodes = int(np.product(settings.cluster_shape))
        system: SystemInterface = DaskSystem(
            address=settings.address, num_nodes=num_nodes, num_cpus=settings.num_cpus
        )
    elif system_name == "dask-scheduler":
        # pylint: disable=import-outside-toplevel
        from nums.experimental.nums_dask.dask_system import DaskSystemStockScheduler

        num_nodes = int(np.product(settings.cluster_shape))
        system: SystemInterface = DaskSystemStockScheduler(
            address=settings.address, num_nodes=num_nodes, num_cpus=settings.num_cpus
        )
    else:
        raise Exception("Unexpected system name %s" % settings.system_name)
    system.init()

    compute_module = {"numpy": numpy_compute}[settings.compute_name]

    if settings.device_grid_name == "cyclic":
        device_grid: DeviceGrid = CyclicDeviceGrid(
            settings.cluster_shape, "cpu", system.devices()
        )
    elif settings.device_grid_name == "packed":
        device_grid: DeviceGrid = PackedDeviceGrid(
            settings.cluster_shape, "cpu", system.devices()
        )
    else:
        raise Exception("Unexpected device grid name %s" % settings.device_grid_name)

    cm = ComputeManager.create(system, compute_module, device_grid)
    fs = FileSystem(cm)
    return ArrayApplication(cm, fs)


def destroy():
    global _instance
    if _instance is None:
        return
    # This will shutdown ray if ray was started by NumS.
    _instance.cm.system.shutdown()
    ComputeManager.destroy()
    del _instance
    _instance = None


def configure_logging():
    # TODO (hme): Fix this to avoid debug messages for all packages.
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    root.addHandler(handler)
