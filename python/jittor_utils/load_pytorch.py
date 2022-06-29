import pickle
import inspect
import difflib
import os
import io
import shutil
import struct
import sys
import jittor as jt
import tarfile
import tempfile
import warnings
import numpy as np
from typing import Any, BinaryIO, cast, Dict, Optional, Type, Tuple, Union, IO, List
from contextlib import closing, contextmanager

loaded_storages = {}

def _maybe_decode_ascii(bytes_str: Union[bytes, str]) -> str:
    if isinstance(bytes_str, bytes):
        return bytes_str.decode('ascii')
    return bytes_str

def load_tensor(dtype, numel, key, location):
    name = os.path.join("archive", "data", str(key))
    f = open(name, "rb")
    loaded_storages[key] = np.frombuffer(f.read(), dtype).copy()

def get_dtype_size(dtype):
    if dtype is np.float32 or dtype is np.int32:
        return 4
    elif dtype is np.float64 or dtype is np.int64:
        return 8
    elif dtype is np.float16 or dtype is np.int16:
        return 2
    else:
        return 1

def persistent_load(saved_id):
    assert isinstance(saved_id, tuple)
    typename = _maybe_decode_ascii(saved_id[0])
    data = saved_id[1:]
    assert typename == 'storage', \
        f"Unknown typename for persistent_load, expected 'storage' but got '{typename}'"
    storage_type, key, location, numel = data
    dtype = storage_type.dtype
    if key not in loaded_storages:
        nbytes = numel * get_dtype_size(dtype)
        load_tensor(dtype, nbytes, key, _maybe_decode_ascii(location))
    return loaded_storages[key]

def _dtype_to_storage_type_map():
    return {
        np.float16: 'HalfStorage',
        np.float32: 'FloatStorage',
        np.int64: 'LongStorage',
        np.int32: 'IntStorage',
        np.int16: 'ShortStorage',
        np.int8: 'CharStorage'
    }

def _storage_type_to_dtype_map():
    dtype_map = {
        val: key for key, val in _dtype_to_storage_type_map().items()}
    return dtype_map

def _get_dtype_from_pickle_storage_type(pickle_storage_type: str):
    try:
        return _storage_type_to_dtype_map()[pickle_storage_type]
    except KeyError:
        raise KeyError(
            f'pickle storage type "{pickle_storage_type}" is not recognized')

class StorageType():
    def __init__(self, name):
        self.dtype = _get_dtype_from_pickle_storage_type(name)

    def __str__(self):
        return f'StorageType(dtype={self.dtype})'

# Need to subclass Unpickler instead of directly monkey-patching the find_class method
# because it's marked readonly in pickle.
# The type: ignore is because mypy can't statically determine the type of this class.
def jittor_rebuild(storage, storage_offset, size, stride, requires_grad, backward_hooks):
    # print(storage, size)
    if len(size) == 0:
        return jt.array(storage)
    return jt.array(storage).reshape(size)

class UnpicklerWrapper(pickle.Unpickler):  # type: ignore[name-defined]
    def find_class(self, mod_name, name):
        if type(name) is str and 'Storage' in name:
            try:
                return StorageType(name)
            except KeyError:
                pass
        if type(name) is str and '_rebuild_tensor_v2' in name:
            return super().find_class("jittor_utils.load_pytorch", "jittor_rebuild")
        return super().find_class(mod_name, name)

def _check_seekable(f) -> bool:
    def raise_err_msg(patterns, e):
        for p in patterns:
            if p in str(e):
                msg = (str(e) + ". You can only load from a file that is seekable."
                                + " Please pre-load the data into a buffer like io.BytesIO and"
                                + " try to load from it instead.")
                raise type(e)(msg)
        raise e

    try:
        f.seek(f.tell())
        return True
    except (io.UnsupportedOperation, AttributeError) as e:
        raise_err_msg(["seek", "tell"], e)
    return False

def load_pytorch(fn_name):
    if not fn_name.endswith(".pth"):
        print("This function is designed to load pytorch pth format files.")
        return None
    else:
        shutil.unpack_archive(fn_name, format='zip')
        f = open("archive/data.pkl", "rb")
        data_file = io.BytesIO(f.read())
        pickle_load_args = {'encoding': 'utf-8'}
        unpickler = UnpicklerWrapper(data_file,  **pickle_load_args)
        unpickler.persistent_load = persistent_load
        result = unpickler.load()
        shutil.rmtree("archive")
        return result

if __name__ == "__main__":
    result = load_pytorch("van_base.pth")
    for key, val in result.items():
        print(key, val.shape)