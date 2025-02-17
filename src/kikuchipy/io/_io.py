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

import glob
import os
from pathlib import Path
from typing import TYPE_CHECKING

import h5py
from hyperspy.io_plugins import hspy
from hyperspy.misc.io.tools import overwrite as overwrite_method
from hyperspy.misc.utils import find_subclasses, strlist2enumeration
from hyperspy.signal import BaseSignal
import numpy as np

from kikuchipy.io._util import _ensure_directory, _get_input_bool
from kikuchipy.io.plugins import (
    bruker_h5ebsd,
    ebsd_directory,
    edax_binary,
    edax_h5ebsd,
    emsoft_ebsd,
    emsoft_ebsd_master_pattern,
    emsoft_ecp_master_pattern,
    emsoft_tkd_master_pattern,
    kikuchipy_h5ebsd,
    nordif,
    nordif_calibration_patterns,
    oxford_binary,
    oxford_h5ebsd,
)
import kikuchipy.signals

plugins: list = [
    bruker_h5ebsd,
    ebsd_directory,
    edax_binary,
    edax_h5ebsd,
    emsoft_ebsd,
    emsoft_ebsd_master_pattern,
    emsoft_ecp_master_pattern,
    emsoft_tkd_master_pattern,
    hspy,
    kikuchipy_h5ebsd,
    nordif,
    nordif_calibration_patterns,
    oxford_binary,
    oxford_h5ebsd,
]

if TYPE_CHECKING:  # pragma: no cover
    from kikuchipy.signals.ebsd import EBSD, LazyEBSD
    from kikuchipy.signals.ebsd_master_pattern import (
        EBSDMasterPattern,
        LazyEBSDMasterPattern,
    )
    from kikuchipy.signals.ecp_master_pattern import ECPMasterPattern

default_write_ext = set()
for plugin in plugins:
    if plugin.writes:
        default_write_ext.add(plugin.file_extensions[plugin.default_extension])


def load(
    filename: str | Path, lazy: bool = False, **kwargs
) -> "EBSD | EBSDMasterPattern | ECPMasterPattern | list[EBSD] | list[EBSDMasterPattern] | list[ECPMasterPattern]":
    """Load an :class:`~kikuchipy.signals.EBSD`,
    :class:`~kikuchipy.signals.EBSDMasterPattern` or
    :class:`~kikuchipy.signals.ECPMasterPattern` signal from one of the
    :ref:`/tutorials/load_save_data.ipynb#Supported-file-formats`.

    This function is a modified version of :func:`hyperspy.io.load`.

    Parameters
    ----------
    filename
        Name of file to load.
    lazy
        Open the data lazily without actually reading the data from disk
        until required. Allows opening arbitrary sized datasets. Default
        is ``False``.
    **kwargs
        Keyword arguments passed to the corresponding kikuchipy reader.
        See their individual documentation for available options.

    Returns
    -------
    out
        Signal or a list of signals.

    Raises
    ------
    IOError
        If the file was not found or could not be read.

    Examples
    --------
    Import nine patterns from an HDF5 file in a directory ``DATA_PATH``

    >>> import kikuchipy as kp
    >>> s = kp.load(DATA_PATH / "patterns.h5")
    >>> s
    <EBSD, title: patterns Scan 1, dimensions: (3, 3|60, 60)>
    """
    filename = str(filename)

    if not os.path.isfile(filename):
        is_wildcard = False
        filenames = glob.glob(filename)
        if len(filenames) > 0:
            is_wildcard = True
        if not is_wildcard:
            raise IOError(f"No filename matches {filename!r}")

    # Find matching reader for file extension
    extension = os.path.splitext(filename)[1][1:]
    readers = []
    for plugin in plugins:
        if extension.lower() in plugin.file_extensions:
            readers.append(plugin)
    if len(readers) == 0:
        raise IOError(
            f"Could not read {filename!r}. If the file format is supported, please "
            "report this error"
        )
    elif len(readers) > 1 and h5py.is_hdf5(filename):
        reader = _plugin_from_footprints(filename, plugins=readers)
    else:
        reader = readers[0]

    # Get data and metadata (from potentially multiple signals if an h5ebsd
    # file)
    signal_dicts = reader.file_reader(filename, lazy=lazy, **kwargs)
    out = []
    for signal in signal_dicts:
        out.append(_dict2signal(signal, lazy=lazy))
        directory, filename = os.path.split(os.path.abspath(filename))
        filename, extension = os.path.splitext(filename)
        out[-1].tmp_parameters.folder = directory
        out[-1].tmp_parameters.filename = filename
        out[-1].tmp_parameters.extension = extension.replace(".", "")

    if len(out) == 1:
        out = out[0]

    return out


def _dict2signal(
    signal_dict: dict, lazy: bool = False
) -> "EBSD | LazyEBSD | EBSDMasterPattern | LazyEBSDMasterPattern":
    """Create a signal instance from a dictionary.

    This function is a modified version :func:`hyperspy.io.dict2signal`.

    Parameters
    ----------
    signal_dict
        Signal dictionary with ``data``, ``metadata`` and
        ``original_metadata``.
    lazy
        Open the data lazily without actually reading the data from disk
        until required. Allows opening arbitrary sized datasets. Default
        is False.

    Returns
    -------
    signal
        Signal instance with ``data``, ``metadata`` and
        ``original_metadata`` from dictionary.
    """
    signal_type = ""
    if "metadata" in signal_dict:
        md = signal_dict["metadata"]
        if "Signal" in md and "record_by" in md["Signal"]:
            record_by = md["Signal"]["record_by"]
            if record_by != "image":
                raise ValueError(
                    "kikuchipy only supports `record_by = image`, not " f"{record_by}."
                )
            del md["Signal"]["record_by"]
        if "Signal" in md and "signal_type" in md["Signal"]:
            signal_type = md["Signal"]["signal_type"]

    signal = _assign_signal_subclass(
        signal_dimension=2,
        signal_type=signal_type,
        dtype=signal_dict["data"].dtype,
        lazy=lazy,
    )(**signal_dict)

    if signal._lazy:
        signal._make_lazy()

    return signal


def _plugin_from_footprints(filename: str, plugins) -> object:
    """Get HDF5 correct plugin from a list of potential plugins based on
    their unique footprints.

    The unique footprint is a list of strings that can take on either of
    two formats:
        * group/dataset names separated by "/", indicating nested
          groups/datasets
        * single group/dataset name indicating that the groups/datasets
          are in the top group

    Parameters
    ----------
    filename
        Input file name.
    plugins
        Potential plugins reading HDF5 files.

    Returns
    -------
    plugin
        One of the potential plugins, or ``None`` if no footprint was
        found.
    """

    def _hdf5group2dict(group):
        d = {}
        for key, val in group.items():
            key_lower = key.lstrip().lower()
            if isinstance(val, h5py.Group):
                d[key_lower] = _hdf5group2dict(val)
            elif key_lower == "manufacturer":
                d[key_lower] = key
            else:
                d[key_lower] = 1
        return d

    def _exists(obj, chain):
        key = chain.pop(0)
        if key in obj:
            return _exists(obj[key], chain) if chain else obj[key]

    with h5py.File(filename) as f:
        d = _hdf5group2dict(f["/"])

        plugins_with_footprints = [p for p in plugins if hasattr(p, "footprint")]
        plugins_with_manufacturer = [
            p for p in plugins_with_footprints if hasattr(p, "manufacturer")
        ]

        matching_plugin = None
        # Check manufacturer if possible (all h5ebsd files have this)
        for key, val in d.items():
            if key == "manufacturer":
                # Extracting the manufacturer is finicky
                man = f[val][()]
                if isinstance(man, np.ndarray) and len(man) == 1:
                    man = man[0]
                if isinstance(man, bytes):
                    man = man.decode("latin-1")
                for p in plugins_with_manufacturer:
                    if man.lower() == p.manufacturer:
                        matching_plugin = p
                        break

        # If no match found, continue searching
        if matching_plugin is None:
            for p in plugins_with_footprints:
                n_matches = 0
                n_desired_matches = len(p.footprint)
                for fp in p.footprint:
                    fp = fp.lower().split("/")
                    if _exists(d, fp) is not None:
                        n_matches += 1
                if n_matches == n_desired_matches:
                    matching_plugin = p
                    break

    return matching_plugin


def _assign_signal_subclass(
    dtype: np.dtype,
    signal_dimension: int,
    signal_type: str = "",
    lazy: bool = False,
) -> "EBSD | EBSDMasterPattern | ECPMasterPattern":
    """Given ``record_by`` and ``signal_type`` return the matching
    signal subclass.

    This function is a modified version of
    :func:`hyperspy.io.assign_signal_subclass`.

    Parameters
    ----------
    dtype
        Data type of signal data.
    signal_dimension
        Number of signal dimensions.
    signal_type
        Signal type. Options are '', 'EBSD', 'EBSDMasterPattern'.
    lazy
        Open the data lazily without actually reading the data from disc
        until required. Allows opening arbitrary sized datasets. Default
        is False.

    Returns
    -------
    Signal or subclass
    """
    # Check if parameter values are allowed
    if (
        "float" in dtype.name
        or "int" in dtype.name
        or "void" in dtype.name
        or "bool" in dtype.name
        or "object" in dtype.name
    ):
        dtype = "real"
    else:
        raise ValueError(f"Data type {dtype.name!r} not understood")
    if not isinstance(signal_dimension, int) or signal_dimension < 0:
        raise ValueError(
            f"Signal dimension must be a positive integer and not {signal_dimension!r}"
        )

    # Get possible signal classes
    signals = {}
    for k, v in find_subclasses(kikuchipy.signals, BaseSignal).items():
        if v._lazy == lazy:
            signals[k] = v

    # Get signals matching both input signal's dtype and signal dimension
    dtype_matches = [s for s in signals.values() if s._dtype == dtype]
    dtype_dim_matches = [
        s for s in dtype_matches if s._signal_dimension == signal_dimension
    ]
    dtype_dim_type_matches = [
        s
        for s in dtype_dim_matches
        if signal_type == s._signal_type or signal_type in s._alias_signal_types
    ]

    if len(dtype_dim_type_matches) == 1:
        matches = dtype_dim_type_matches
    else:
        raise ValueError(
            f"No kikuchipy signals match dtype {dtype!r}, signal dimension "
            f"'{signal_dimension}' and signal_type {signal_type!r}"
        )

    return matches[0]


def _save(
    filename: str | Path,
    signal: "EBSD | LazyEBSD",
    overwrite: bool | None = None,
    add_scan: bool | None = None,
    **kwargs,
) -> None:
    """Write signal to a file in a supported format.

    This function is a modified version of :func:`hyperspy.io.save`.

    Parameters
    ----------
    filename
        File path including name of new file.
    signal
        Signal instance.
    overwrite
        Whether to overwrite file or not if it already exists.
    add_scan
        Whether to add the signal to an already existing h5ebsd file or
        not. If the file does not exist the signal is written to a new
        file.
    **kwargs
        Keyword arguments passed to the writer.
    """
    filename = str(filename)

    ext = os.path.splitext(filename)[1][1:]
    if ext == "":  # Will write to kikuchipy's h5ebsd format
        ext = "h5"
        filename = filename + "." + ext

    writer = None
    for plugin in plugins:
        if ext.lower() in plugin.file_extensions and plugin.writes:
            writer = plugin
            break

    if writer is None:
        raise ValueError(
            f"{ext!r} does not correspond to any supported format. Supported file "
            f"extensions are: {strlist2enumeration(default_write_ext)!r}"
        )
    else:
        sd = signal.axes_manager.signal_dimension
        nd = signal.axes_manager.navigation_dimension
        if writer.writes is not True and (sd, nd) not in writer.writes:
            # Get writers that can write this data
            writing_plugins = []
            for plugin in plugins:
                if (
                    plugin.writes is True
                    or plugin.writes is not False
                    and (sd, nd) in plugin.writes
                ):
                    writing_plugins.append(plugin)
            raise ValueError(
                "This file format cannot write this data. The following formats can: "
                f"{strlist2enumeration(writing_plugins)!r}"
            )

        _ensure_directory(filename)
        is_file = os.path.isfile(filename)

        # Check if we are to add signal to an already existing h5ebsd file
        if (
            writer.format_name == "kikuchipy_h5ebsd"
            and overwrite is not True
            and is_file
        ):
            if add_scan is None:
                q = f"Add scan to {filename!r} (y/n)?\n"
                add_scan = _get_input_bool(q)
            if add_scan:
                overwrite = True  # So that the 2nd statement below triggers
            kwargs["add_scan"] = add_scan

        # Determine if signal is to be written to file or not
        if overwrite is None:
            write = overwrite_method(filename)  # Ask what to do
        elif overwrite is True or (overwrite is False and not is_file):
            write = True  # Write the file
        elif overwrite is False and is_file:
            write = False  # Don't write the file
        else:
            raise ValueError(
                "overwrite parameter can only be None, True or False, and not "
                f"{overwrite}"
            )

        # Finally, write file
        if write:
            writer.file_writer(filename, signal, **kwargs)
            directory, filename = os.path.split(os.path.abspath(filename))
            signal.tmp_parameters.set_item("folder", directory)
            signal.tmp_parameters.set_item("filename", os.path.splitext(filename)[0])
            signal.tmp_parameters.set_item("extension", ext)
