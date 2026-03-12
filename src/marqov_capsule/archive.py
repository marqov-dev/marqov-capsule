"""
Archive utilities for packing and unpacking capsule directories.

Produces deterministic gzipped tarballs suitable for content-addressed
storage. Determinism is achieved by:
  - Sorting archive members alphabetically
  - Zeroing tar-entry timestamps (mtime=0)
  - Fixed permissions (0o644 for files, 0o755 for directories)
  - Zeroing the gzip header timestamp (mtime=0)
"""

import gzip
import hashlib
import io
import tarfile
from pathlib import Path
from typing import Optional, Union


def pack_capsule(
    capsule_dir: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Create a deterministic gzipped tarball from a capsule directory.

    The archive is byte-reproducible: packing the same directory twice
    always yields identical bytes.

    Args:
        capsule_dir: Path to the capsule directory to pack.
        output_path: Where to write the archive.  Defaults to
            ``{name}.capsule`` next to the capsule directory, where
            *name* is derived from the directory name (stripping a
            trailing ``.capsule`` suffix if present, then re-adding it).

    Returns:
        Path to the created archive file.

    Raises:
        FileNotFoundError: If the capsule directory or its ``.checksums``
            file does not exist.
    """
    capsule_dir = Path(capsule_dir)

    if not capsule_dir.is_dir():
        raise FileNotFoundError(f"Capsule directory not found: {capsule_dir}")

    checksums_path = capsule_dir / ".checksums"
    if not checksums_path.exists():
        raise FileNotFoundError(
            f".checksums not found in {capsule_dir}. "
            "Seal the capsule first (save_capsule generates .checksums)."
        )

    if output_path is None:
        # Derive archive name from directory name.
        dir_name = capsule_dir.name  # e.g. "my-wf.capsule"
        if dir_name.endswith(".capsule"):
            archive_name = dir_name  # already has .capsule
        else:
            archive_name = dir_name + ".capsule"
        # Place archive next to (not inside) the capsule directory.
        # Resolve the capsule_dir to an absolute path so that .parent
        # is meaningful even when given a relative path.
        resolved = capsule_dir.resolve()
        candidate = resolved.parent / archive_name
        if candidate == resolved:
            # The directory and archive share the same path — place the
            # archive one level up to avoid the collision.
            candidate = resolved.parent.parent / archive_name
        output_path = candidate
    else:
        output_path = Path(output_path)

    # Build a deterministic tar into an in-memory buffer, then gzip with
    # mtime=0 so the gzip header is also deterministic.
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
        _add_directory_deterministic(tf, capsule_dir, capsule_dir.name)
    tar_bytes = tar_buf.getvalue()

    # gzip with mtime=0 and empty filename for full determinism.
    # GzipFile embeds the filename in the header by default when given
    # a file object; passing filename="" suppresses it so archives
    # written to different paths are still byte-identical.
    with open(output_path, "wb") as fout:
        with gzip.GzipFile(
            filename="", fileobj=fout, mode="wb", mtime=0
        ) as gz:
            gz.write(tar_bytes)

    return output_path


def unpack_capsule(
    archive_path: Union[str, Path],
    output_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Extract a capsule archive to a directory.

    Args:
        archive_path: Path to the ``.capsule`` archive file.
        output_dir: Directory to extract into.  Defaults to the current
            working directory.  The archive's top-level directory is
            preserved, so ``foo.capsule`` extracts to
            ``<output_dir>/foo.capsule/``.

    Returns:
        Path to the extracted capsule directory.

    Raises:
        FileNotFoundError: If the archive does not exist.
        ValueError: If the archive does not contain ``capsule.yaml``.
    """
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    if output_dir is None:
        output_dir = Path.cwd()
    else:
        output_dir = Path(output_dir)

    with tarfile.open(str(archive_path), "r:gz") as tf:
        # Validate that the archive contains capsule.yaml
        member_names = tf.getnames()
        has_capsule_yaml = any(
            name.endswith("/capsule.yaml") or name == "capsule.yaml"
            for name in member_names
        )
        if not has_capsule_yaml:
            raise ValueError(
                f"Archive does not contain capsule.yaml: {archive_path}"
            )

        # Use data filter for safe extraction (Python 3.12+)
        tf.extractall(path=str(output_dir), filter="data")

        # Determine the top-level directory in the archive
        top_dirs = {name.split("/")[0] for name in member_names if "/" in name}
        if len(top_dirs) == 1:
            capsule_dir_name = top_dirs.pop()
        else:
            # Fallback: derive from archive filename
            capsule_dir_name = archive_path.stem
            if not capsule_dir_name.endswith(".capsule"):
                capsule_dir_name += ".capsule"

    return output_dir / capsule_dir_name


def content_id(capsule_dir_or_archive: Union[str, Path]) -> str:
    """Compute the content identifier for a capsule.

    The content ID is the SHA-256 hash of the ``.checksums`` file
    contents, formatted as ``sha256:<hex>``.

    Works on both capsule directories (reads ``.checksums`` directly)
    and archive files (extracts the ``.checksums`` member without full
    extraction).

    Args:
        capsule_dir_or_archive: Path to a capsule directory or a
            ``.capsule`` archive file.

    Returns:
        Content ID string in the format ``sha256:<64-hex-chars>``.

    Raises:
        FileNotFoundError: If the path does not exist or the
            ``.checksums`` file cannot be found.
    """
    path = Path(capsule_dir_or_archive)

    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path.is_dir():
        checksums_path = path / ".checksums"
        if not checksums_path.exists():
            raise FileNotFoundError(f".checksums not found in {path}")
        checksums_bytes = checksums_path.read_bytes()
    else:
        # Treat as archive — extract .checksums member without full extraction
        checksums_bytes = _extract_checksums_from_archive(path)

    digest = hashlib.sha256(checksums_bytes).hexdigest()
    return f"sha256:{digest}"


def _add_directory_deterministic(
    tf: tarfile.TarFile,
    source_dir: Path,
    arcname_prefix: str,
) -> None:
    """Add all files in *source_dir* to *tf* with deterministic metadata.

    Files are sorted alphabetically, timestamps zeroed, and permissions
    normalised (0o755 for directories, 0o644 for files).
    """
    # First add the directory entry itself
    dir_info = tarfile.TarInfo(name=arcname_prefix)
    dir_info.type = tarfile.DIRTYPE
    dir_info.mtime = 0
    dir_info.mode = 0o755
    dir_info.uid = 0
    dir_info.gid = 0
    dir_info.uname = ""
    dir_info.gname = ""
    tf.addfile(dir_info)

    # Collect all paths relative to source_dir, sorted
    all_paths = sorted(source_dir.rglob("*"))

    for entry in all_paths:
        rel = entry.relative_to(source_dir)
        arcname = f"{arcname_prefix}/{rel}"

        if entry.is_dir():
            info = tarfile.TarInfo(name=arcname)
            info.type = tarfile.DIRTYPE
            info.mtime = 0
            info.mode = 0o755
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            tf.addfile(info)
        elif entry.is_file():
            data = entry.read_bytes()
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            tf.addfile(info, io.BytesIO(data))


def _extract_checksums_from_archive(archive_path: Path) -> bytes:
    """Extract the .checksums member from a tar.gz archive without full extraction.

    Searches for a member whose name ends with ``/.checksums`` or is
    exactly ``.checksums``.

    Returns:
        The raw bytes of the .checksums file.

    Raises:
        FileNotFoundError: If no .checksums member is found.
    """
    with tarfile.open(str(archive_path), "r:gz") as tf:
        for member in tf.getmembers():
            if member.name.endswith("/.checksums") or member.name == ".checksums":
                f = tf.extractfile(member)
                if f is not None:
                    return f.read()

    raise FileNotFoundError(f".checksums not found in archive: {archive_path}")
