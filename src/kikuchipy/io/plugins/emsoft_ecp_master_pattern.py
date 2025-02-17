# Copyright 2019-2024 The kikuchipy developers
#
# This file is part of kikuchipy.
#
# kikuchipy is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# kikuchipy is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with kikuchipy. If not, see <http://www.gnu.org/licenses/>.

"""Reader of simulated ECP master patterns from an EMsoft HDF5 file.
"""

from pathlib import Path

from kikuchipy.io.plugins._emsoft_master_pattern import EMsoftMasterPatternReader

__all__ = ["file_reader"]


# Plugin characteristics
# ----------------------
format_name = "emsoft_ecp_master_pattern"
description = (
    "Read support for simulated electron channeling pattern (ECP)"
    "master patterns stored in an EMsoft HDF5 file."
)
full_support = False
# Recognised file extension
file_extensions = ["h5", "hdf5"]
default_extension = 0
# Writing capabilities
writes = False

# Unique HDF5 footprint
footprint = ["emdata/ecpmaster"]


class EMsoftECPMasterPatternReader(EMsoftMasterPatternReader):
    @property
    def diffraction_type(self) -> str:
        return "ECP"

    @property
    def cl_parameters_group_name(self) -> str:
        return "MCCL"  # Monte Carlo openCL

    @property
    def energy_string(self) -> str:
        return "EkeV"


def file_reader(
    filename: str | Path,
    energy: range | None = None,
    projection: str = "stereographic",
    hemisphere: str = "upper",
    lazy: bool = False,
    **kwargs,
) -> list[dict]:
    """Read simulated electron channeling pattern (ECP) master patterns
    from EMsoft's HDF5 file format :cite:`callahan2013dynamical`.

    Not meant to be used directly; use :func:`~kikuchipy.load`.

    Parameters
    ----------
    filename
        Full file path of the HDF file.
    energy
        Desired beam energy or energy range. If not given (default), all
        available energies are read.
    projection
        Projection(s) to read. Options are ``"stereographic"`` (default)
        or ``"lambert"``.
    hemisphere
        Projection hemisphere(s) to read. Options are ``"upper"``
        (default), ``"lower"`` or ``"both"``. If ``"both"``, these will
        be stacked in the vertical navigation axis.
    lazy
        Open the data lazily without actually reading the data from disk
        until requested. Allows opening datasets larger than available
        memory. Default is ``False``.
    **kwargs
        Keyword arguments passed to :class:`h5py.File`.

    Returns
    -------
    signal_dict_list
        Data, axes, metadata and original metadata.
    """
    reader = EMsoftECPMasterPatternReader(
        filename=filename,
        energy=energy,
        projection=projection,
        hemisphere=hemisphere,
        lazy=lazy,
    )
    return reader.read(**kwargs)
