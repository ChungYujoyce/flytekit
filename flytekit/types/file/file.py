from __future__ import annotations

import os
import pathlib
import typing

from flytekit.core.context_manager import FlyteContext
from flytekit.core.type_engine import TypeEngine, TypeTransformer
from flytekit.loggers import logger
from flytekit.models import types as _type_models
from flytekit.models.core import types as _core_types
from flytekit.models.literals import Blob, BlobMetadata, Literal, Scalar
from flytekit.models.types import LiteralType


def noop():
    ...


T = typing.TypeVar("T")


class FlyteFile(os.PathLike, typing.Generic[T]):
    """
    Since there is no native Python implementation of files and directories for the Flyte Blob type, (like how int
    exists for Flyte's Integer type) we need to create one so that users can express that their tasks take
    in or return a file. There is ``pathlib.Path`` of course, which is usable, but it made more sense to create a standalone
    type esp. since we can add on additional properties.

    Files (and directories) differ from the primitive types like floats and string in that flytekit typically uploads
    the contents of the files to the blob store connected with your Flyte installation. That is, the Python native
    literal that represents a file is typically just the path to the file on the local filesystem. However in Flyte,
    an instance of a file is represented by a :py:class:`Blob <flytekit.models.literals.Blob>` literal,
    with the ``uri`` field set to the location in the Flyte blob store (AWS/GCS etc.).

    The prefix for where uploads go is set by the raw output data prefix setting, which should be set at registration
    time. See the flytectl option for more information.

    In short, if a task returns ``"/path/to/file"`` and the task's signature is set to return ``FlyteFile``, then the
    contents of ``/path/to/file`` are uploaded.

    You can also make it so that the upload does not happen. There are a few different types you use for
    task/workflow signatures. Keep in mind that in the backend, in Admin and in the blob store, there is only one type
    that represents files, the :py:class:`Blob <flytekit.models.core.types.BlobType>` type.

    Whether or not the uploading happens, and the behavior of the translation between Python native values and Flyte
    literal values depends on a few things.

    * The declared Python type in the signature. These can be
      * :class:`python:flytekit.FlyteFile`
      * :class:`python:os.PathLike`
      * :class:`python:pathlib.Path`
      Note that ``os.PathLike`` is only a type in Python, you can't instantiate it.
    * The type of the Python native value we're returning. These can be
      * :py:class:`flytekit.FlyteFile`
      * :py:class:`pathlib.Path`
      * :py:class:`str`
    * Whether the value being converted is a "remote" path or not. For instance if a task returns a value of
      "http://www.google.com" as a ``FlyteFile``, obviously it doesn't make sense for us to try to upload that to the
      Flyte blob store. So no remote paths are uploaded. flytekit considers a path remote if it starts with ``s3://``,
      ``gs://``, ``http(s)://``, or even ``file://``.



    +-------------+---------------+---------------------------------------------+--------------------------------------+
    | Header 1    | Header 1      | Heeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeader 2   | Heeeeeeeeeeeeeeeeeeeeeeeeeeeeader 3  |
    +=============+===============+=============================================+======================================+
    | body row 111| body row 1111 | coooooooooooooooooooooooooooooooooolumn 2   | coooooooooooooooooooooooooooolumn 3  |
    +-------------+---------------+---------------------------------------------+--------------------------------------+
    | body row 222| body row 2222 | Ceeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeells may span                            columns.|
    +-------------+---------------+---------------------------------------------+--------------------------------------+
    | body row 333| body row 3333 | Ceeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeells may  | -                            Cells   |
    +-------------+---------------+ sppppppppppppppppppppppppppppppppppan rows. | -                            contain |
    | body row 444| body row 4444 |                                             | -                            blocks. |
    +-------------+---------------+---------------------------------------------+--------------------------------------+




    +-------------+---------------+---------------------------------------------+--------------------------------------+
    | Header 1    | Header 1      | Heeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeader 2   | Heeeeeeeeeeeeeeeeeeeeeeeeeeeeader 3  |
    +=============+===============+=============================================+======================================+
    | body row 111| body row 1111 | coooooooooooooooooooooooooooooooooolumn 2   | coooooooooooooooooooooooooooolumn 3  |
    +-------------+---------------+---------------------------------------------+--------------------------------------+
    | body row 222| body row 2222 | Ceeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeells may span                            columns.|
    +-------------+---------------+---------------------------------------------+--------------------------------------+
    | body row 333| body row 3333 | Ceeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeells may  | -                            Cells   |
    +-------------+---------------+ sppppppppppppppppppppppppppppppppppan rows. | -                            contain |
    | body row 444| body row 4444 |                                             | -                            blocks. |
    +-------------+---------------+---------------------------------------------+--------------------------------------+

    * :class:`python:os.PathLike`
      This is just a path on the filesystem accessible from the Python process. This is a native Python abstract class.

      .. code-block:: python

          def path_task() -> os.PathLike:
              return '/tmp/xyz.txt'

      If you specify a PathLike as an input, the task will receive a PathLike at task start, and you can open() it as
      normal. However, since we want to control when files are downloaded, Flyte provides its own PathLike object::

        from flytekit import types as flytekit_typing

        def t1(in1: flytekit_typing.FlyteFile) -> str:
            with open(in1, 'r') as fh:
                lines = fh.readlines()
                return "".join(lines)

      As mentioned above, since Flyte file types have a string embedded in it as part of the type, you can add a
      format by specifying a string after the class like so. ::

        def t2() -> flytekit_typing.FlyteFile["csv"]:
            from random import sample
            sequence = [i for i in range(20)]
            subset = sample(sequence, 5)
            results = ",".join([str(x) for x in subset])
            with open("/tmp/local_file.csv", "w") as fh:
                fh.write(results)
            return "/tmp/local_file.csv"

    How are these files handled?

    S3, http, https are all treated as remote - the behavior should be the same, they are never copied unless
    explicitly told to do so.

    Local paths always get uploaded, unless explicitly told not to do so.

    To specify non-default behavior:

    * Copy the S3 path to a specific location.
      ``FlyteFile("s3://bucket/path", remote_path="s3://other-bucket/path")``

    * Copy local path to a specific location.
      ``FlyteFile("/tmp/local_file", remote_path="s3://other-bucket/path")``

    * Do not copy local path, this will copy the string into the literal. For example, let's say your docker image has a
      thousand files in it, and you want to tell the next task, which file to look at. (Bad example, you shouldn't have
      that many files in your image.)
      ``FlyteFile("/tmp/local_file", remote_path=False)``

    * However, we have a shorthand.
      "file:///tmp/local_file" is treated as "remote" and is by default not copied.
    """

    @classmethod
    def extension(cls) -> str:
        return ""

    def __class_getitem__(cls, item: typing.Type) -> typing.Type[FlyteFile]:
        if item is None:
            return cls
        item = str(item)
        item = item.strip().lstrip("~").lstrip(".")
        if item == "":
            return cls

        class _SpecificFormatClass(FlyteFile):
            # Get the type engine to see this as kind of a generic
            __origin__ = FlyteFile

            @classmethod
            def extension(cls) -> str:
                return item

        return _SpecificFormatClass

    def __init__(self, path: str, downloader: typing.Callable = noop, remote_path=None):
        """
        :param path: The source path that users are expected to call open() on
        :param downloader: Optional function that can be passed that used to delay downloading of the actual fil
            until a user actually calls open().
        :param remote_path: If the user wants to return something and also specify where it should be uploaded to.
        """
        self._path = path
        self._downloader = downloader
        self._downloaded = False
        self._remote_path = remote_path
        self._remote_source = None

    def __fspath__(self):
        # This is where a delayed downloading of the file will happen
        if not self._downloaded:
            self._downloader()
            self._downloaded = True
        return self._path

    def __eq__(self, other):
        if isinstance(other, FlyteFile):
            return (
                self._path == other._path
                and self._remote_path == other._remote_path
                and self.extension() == other.extension()
            )
        else:
            return self._path == other

    @property
    def downloaded(self) -> bool:
        return self._downloaded

    @property
    def remote_path(self) -> typing.Optional[str]:
        return self._remote_path

    @property
    def path(self) -> str:
        return self._path

    @property
    def remote_source(self) -> str:
        """
        If this is an input to a task, and the original path is ``s3://something``, flytekit will download the
        file for the user. In case the user wants access to the original path, it will be here.
        """
        return self._remote_source

    def trigger_download(self):
        if self._downloader is not noop:
            self._downloader()
        else:
            raise ValueError(f"Attempting to trigger download on non-downloadable file {self}")

    def __repr__(self):
        return self._path

    def __str__(self):
        return self._path


class FlyteFilePathTransformer(TypeTransformer[FlyteFile]):
    def __init__(self):
        super().__init__(name="FlyteFilePath", t=FlyteFile)

    @staticmethod
    def get_format(t: typing.Type[FlyteFile]) -> str:
        return t.extension()

    def _blob_type(self, format: str) -> _core_types.BlobType:
        return _core_types.BlobType(format=format, dimensionality=_core_types.BlobType.BlobDimensionality.SINGLE)

    def get_literal_type(self, t: typing.Type[FlyteFile]) -> LiteralType:
        return _type_models.LiteralType(blob=self._blob_type(format=FlyteFilePathTransformer.get_format(t)))

    def to_literal(
        self,
        ctx: FlyteContext,
        python_val: typing.Union[FlyteFile, os.PathLike, str],
        python_type: typing.Type[FlyteFile],
        expected: LiteralType,
    ) -> Literal:
        remote_path = None
        should_upload = True

        if python_val is None:
            raise AssertionError("None value cannot be converted to a file.")

        # information used by all cases
        meta = BlobMetadata(type=self._blob_type(format=FlyteFilePathTransformer.get_format(python_type)))

        if isinstance(python_val, FlyteFile):
            source_path = python_val.path

            # If the object has a remote source, then we just convert it back. This means that if someone is just
            # going back and forth between a FlyteFile Python value and a Blob Flyte IDL value, we don't do anything.
            if python_val._remote_source is not None:
                return Literal(scalar=Scalar(blob=Blob(metadata=meta, uri=python_val._remote_source)))

            # If the user specified the remote_path to be False, that means no matter what, do not upload. Also if the
            # path given is already a remote path, say https://www.google.com, the concept of uploading to the Flyte
            # blob store doesn't make sense.
            if python_val.remote_path is False or ctx.file_access.is_remote(source_path):
                should_upload = False
            # If the type that's given is a simpler type, we also don't upload, but print a warning too.
            if issubclass(python_type, pathlib.Path) or python_type is os.PathLike:
                logger.warning(
                    f"Converting from a FlyteFile Python instance to a Blob Flyte object, but only a {python_type} was"
                    f" specified. Since a simpler type was specified, we'll skip uploading!"
                )
                should_upload = False

            # Set the remote destination if one was given instead of triggering a random one below
            remote_path = python_val.remote_path or None

        elif isinstance(python_val, pathlib.Path) or isinstance(python_val, str):
            if isinstance(python_val, pathlib.Path) and not python_val.is_file():
                raise ValueError(f"Error converting pathlib.Path {python_val} because it's not a file.")
            if isinstance(python_val, str):
                p = pathlib.Path(python_val)
                if not p.is_file():
                    raise ValueError(f"Error converting {python_val} because it's not a file.")

            source_path = str(python_val)
            # See comments above and the usage table
            if (
                ctx.file_access.is_remote(source_path)
                or issubclass(python_type, pathlib.Path)
                or python_type is os.PathLike
            ):
                should_upload = False
        else:
            raise AssertionError(f"Expected FlyteFile or os.PathLike object, received {type(python_val)}")

        # If we're uploading something, that means that the uri should always point to the upload destination.
        if should_upload:
            if remote_path is None:
                remote_path = ctx.file_access.get_random_remote_path(source_path)
            ctx.file_access.put_data(source_path, remote_path, is_multipart=False)
            return Literal(scalar=Scalar(blob=Blob(metadata=meta, uri=remote_path)))
        # If not uploading, then we can only take the original source path as the uri.
        else:
            return Literal(scalar=Scalar(blob=Blob(metadata=meta, uri=source_path)))

    def to_python_value(
        self, ctx: FlyteContext, lv: Literal, expected_python_type: typing.Union[typing.Type[FlyteFile]]
    ) -> FlyteFile:

        uri = lv.scalar.blob.uri

        # In this condition, we still return a FlyteFile instance, but it's a simple one that has no downloading tricks
        # Don't use the issubclass for the PathLike check because FlyteFile does actually subclass it
        if expected_python_type is os.PathLike or issubclass(expected_python_type, pathlib.Path):
            return expected_python_type(uri)

        # The rest of the logic is only for FlyteFile types.
        if not issubclass(expected_python_type, FlyteFile):
            raise TypeError(f"None of os.PathLike, pathlib.Path, or FlyteFile specified {expected_python_type}")

        # This is a local file path, like /usr/local/my_file, don't mess with it. Certainly, downloading it doesn't
        # make any sense.
        if not ctx.file_access.is_remote(uri):
            return expected_python_type(uri)

        # For the remote case, return an FlyteFile object that can download
        local_path = ctx.file_access.get_random_local_path(uri)

        def _downloader():
            return ctx.file_access.get_data(uri, local_path, is_multipart=False)

        expected_format = FlyteFilePathTransformer.get_format(expected_python_type)
        ff = FlyteFile[expected_format](local_path, _downloader)
        ff._remote_source = uri

        return ff


TypeEngine.register(FlyteFilePathTransformer(), additional_types=[pathlib.Path])
