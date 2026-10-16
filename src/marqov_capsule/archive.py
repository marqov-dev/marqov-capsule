"""
Archive utilities for packing and unpacking capsule directories.

Produces deterministic gzipped tarballs suitable for content-addressed
storage. Determinism is host-independent, achieved by:
  - Ordering members by the byte value of their in-archive path (not by
    ``Path`` objects, whose comparison folds case on some flavours)
  - Zeroing tar-entry timestamps (mtime=0) and uid/gid/owner names
  - Fixed permissions (0o644 files, 0o755 directories, 0o777 symlinks)
  - Zeroing the gzip header timestamp (mtime=0)

Payload symlinks are preserved as symlink members and never dereferenced:
following one would embed an out-of-tree target's bytes into the shipped
archive, matching the builder/verifier no-dereference policy.
"""

import gzip
import hashlib
import io
import os
import tarfile
import unicodedata
import warnings
from pathlib import Path, PurePosixPath
from typing import Optional, Union

import yaml

from marqov_capsule._canonical import load_manifest_yaml

# Upper bound on what one archive may inflate to when unpacked, in bytes. A
# gzip stream compresses zeros about 1000:1, so without a bound a few-kilobyte
# .capsule fills the destination disk. 1 GiB is far above any capsule this
# tool has produced; pass ``max_bytes`` to ``unpack_capsule`` to raise it, or
# ``None`` to remove it for an archive you trust.
MAX_UNPACK_BYTES = 1024**3

# Upper bound on the ``.checksums`` member, which is read fully into memory.
# At roughly 100 bytes a line, 16 MiB is over a hundred thousand payload files.
MAX_CHECKSUMS_BYTES = 16 * 1024**2

_PACKABLE_STATES = ("sealed", "archived")


def pack_capsule(
    capsule_dir: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
) -> Path:
    """Create a deterministic gzipped tarball from a sealed capsule directory.

    The archive is byte-reproducible: packing the same directory twice
    always yields identical bytes.

    Args:
        capsule_dir: Path to the capsule directory to pack.
        output_path: Where to write the archive.  When omitted, the archive
            is written into the current working directory as
            ``{name}.capsule``, where *name* is the (resolved) capsule
            directory's own name.  The output path is resolved relative to
            the cwd — never the capsule directory's parent or grandparent.
        overwrite: Replace an existing file at the output path. Off by
            default: an archive is a record distributed under an ID, and
            replacing one in place with another capsule's bytes is the
            mistake this refuses to make silently.

    Returns:
        Path to the created archive file.

    Raises:
        FileNotFoundError: If the capsule directory or its ``.checksums``
            file does not exist.
        FileExistsError: If the output path exists and ``overwrite`` is false.
        ValueError: If the directory is not a sealed capsule (its manifest is
            missing, unreadable, or not in the ``sealed``/``archived`` state),
            if a safe top-level archive name cannot be derived from
            the directory (e.g. the filesystem root), or if the resolved
            output path would overwrite the capsule directory itself.
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

    # A draft with a leftover .checksums is not a capsule to ship: its manifest
    # has no checksums_digest, so nothing binds the payload to it.
    state = _lifecycle_state(capsule_dir)
    if state not in _PACKABLE_STATES:
        raise ValueError(
            f"{capsule_dir} is not sealed (lifecycle_state: {state!r}). "
            "Seal the capsule before packing it."
        )

    # Derive the archive's single top-level member name from the *resolved*
    # directory name.  ``capsule_dir.name`` is unsafe: it is ``''`` for
    # ``.`` and ``'..'`` for ``..``, which produce empty / traversal-shaped
    # archive members that splatter into (or above) the extraction root.
    resolved = capsule_dir.resolve()
    arcname_prefix = resolved.name
    if not arcname_prefix or arcname_prefix in (".", ".."):
        raise ValueError(f"Cannot derive a safe archive name from directory {capsule_dir!r}")

    if output_path is None:
        # Default to the current working directory, not the capsule
        # directory's parent — writing next to a canonically-named
        # ``<name>.capsule`` directory collides with the directory itself,
        # and the old collision workaround silently wrote to the grandparent.
        archive_name = (
            arcname_prefix if arcname_prefix.endswith(".capsule") else arcname_prefix + ".capsule"
        )
        output_path = Path.cwd() / archive_name
    else:
        output_path = Path(output_path)

    # Never write the archive over the capsule directory it is packing.
    if output_path.resolve() == resolved:
        raise ValueError(
            f"Refusing to write the archive over the capsule directory: "
            f"{output_path}. Pass an explicit output path (-o)."
        )

    if not overwrite and (output_path.exists() or output_path.is_symlink()):
        raise FileExistsError(
            f"Archive already exists: {output_path}. "
            "Pass overwrite=True (CLI: --force) to replace it."
        )

    # Build a deterministic tar into an in-memory buffer, then gzip with
    # mtime=0 so the gzip header is also deterministic.
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
        _add_directory_deterministic(tf, capsule_dir, arcname_prefix)
    tar_bytes = tar_buf.getvalue()

    # gzip with mtime=0 and empty filename for full determinism.
    # GzipFile embeds the filename in the header by default when given
    # a file object; passing filename="" suppresses it so archives
    # written to different paths are still byte-identical.
    # "xb" makes the existence check above atomic: a file that appeared in
    # between is still not replaced.
    with open(output_path, "wb" if overwrite else "xb") as fout:
        with gzip.GzipFile(filename="", fileobj=fout, mode="wb", mtime=0) as gz:
            gz.write(tar_bytes)

    return output_path


def unpack_capsule(
    archive_path: Union[str, Path],
    output_dir: Optional[Union[str, Path]] = None,
    max_bytes: Optional[int] = MAX_UNPACK_BYTES,
) -> Path:
    """Extract a capsule archive to a directory.

    Args:
        archive_path: Path to the ``.capsule`` archive file.
        output_dir: Directory to extract into.  Defaults to the current
            working directory.  The archive's top-level directory is
            preserved, so ``foo.capsule`` extracts to
            ``<output_dir>/foo.capsule/``.
        max_bytes: Refuse an archive whose members inflate to more than this
            many bytes in total (default ``MAX_UNPACK_BYTES``). ``None``
            disables the limit.

    Returns:
        Path to the extracted capsule directory.

    Raises:
        FileNotFoundError: If the archive does not exist.
        ValueError: If the archive layout is ambiguous, lacks a regular
            ``capsule.yaml``, its destination capsule directory exists, or it
            would inflate past ``max_bytes``.
    """
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    if output_dir is None:
        output_dir = Path.cwd()
    else:
        output_dir = Path(output_dir)

    with _open_archive(archive_path) as tf:
        # Validate the complete layout before writing any files. One archive
        # represents one capsule; duplicate names would otherwise overwrite
        # earlier members, and multiple roots leave the return value ambiguous.
        capsule_dir_name, members_by_name = _single_root_layout(tf)
        manifest_name = f"{capsule_dir_name}/capsule.yaml"
        if manifest_name not in members_by_name or not members_by_name[manifest_name].isfile():
            raise ValueError(
                "Archive must contain a regular capsule.yaml under its top-level directory"
            )
        # .checksums is read by payload_digest and verify after extraction; a
        # link or directory member of that name would make tarfile follow the
        # link (KeyError / RecursionError) or hide the wrong type behind a
        # "not found" message. Refuse it up front (#124).
        checksums_name = f"{capsule_dir_name}/.checksums"
        if checksums_name in members_by_name and not members_by_name[checksums_name].isreg():
            raise ValueError(".checksums must be a regular file member of the archive")
        if checksums_name in members_by_name:
            _check_checksums_size(members_by_name[checksums_name])
        # Sizes come from the member headers, which bound what extraction
        # writes, so the limit is enforced before a single byte lands on disk.
        total = sum(m.size for m in members_by_name.values() if m.isreg())
        if max_bytes is not None and total > max_bytes:
            raise ValueError(
                f"archive inflates to {total} bytes, which exceeds the {max_bytes}-byte limit"
            )
        destination = output_dir / capsule_dir_name
        if destination.exists() or destination.is_symlink():
            raise ValueError(f"Capsule destination already exists: {destination}")

        # Safe extraction.  ``extractall(filter="data")`` (PEP 706) is the
        # right tool, but the ``filter`` keyword only exists on 3.12+ and the
        # 3.9.17+/3.10.12+/3.11.4+ backports — the ``requires-python`` floor
        # admits older 3.10/3.11 patch releases where it raises TypeError and
        # kills the whole unpack path.  Feature-detect it and fall back to a
        # hand-rolled safe extraction that guards traversal and links.
        try:
            if _extractall_filter_supported():
                tf.extractall(path=str(output_dir), filter="data")
            else:
                _safe_extractall(tf, output_dir)
        except EOFError as exc:
            raise ValueError(f"archive is truncated or corrupt: {archive_path}") from exc

    return output_dir / capsule_dir_name


class _open_archive:
    """``tarfile.open(path, "r:gz")`` whose read errors are ``ValueError``.

    A gzip stream cut off after its header raises ``EOFError`` from inside
    tarfile — neither an ``OSError`` nor a ``TarError`` — and a stream that is
    not gzip at all raises ``tarfile.ReadError``. Both are "this is not a
    capsule archive", which the public API documents as ``ValueError`` (#124).
    """

    def __init__(self, archive_path: Path):
        self.archive_path = archive_path
        self._tf: Optional[tarfile.TarFile] = None

    def __enter__(self) -> tarfile.TarFile:
        try:
            self._tf = tarfile.open(str(self.archive_path), "r:gz")
            # Read the whole member table now so a truncated stream fails here,
            # as ValueError, rather than from a later getmembers()/extract.
            self._tf.getmembers()
        except EOFError as exc:
            self._close()
            raise ValueError(f"archive is truncated or corrupt: {self.archive_path}") from exc
        except tarfile.TarError as exc:
            self._close()
            raise ValueError(f"not a capsule archive: {self.archive_path}: {exc}") from exc
        return self._tf

    def __exit__(self, *exc_info):
        self._close()

    def _close(self):
        if self._tf is not None:
            self._tf.close()
            self._tf = None


def _single_root_layout(tf: tarfile.TarFile) -> tuple[str, dict[str, tarfile.TarInfo]]:
    """Validate member names and return ``(root dir name, members by name)``.

    Shared by ``unpack_capsule`` and ``payload_digest`` so both agree on what a
    well-formed archive is: safe relative names, no duplicates (byte-wise or
    after NFC), exactly one top-level directory (#94).
    """
    roots = set()
    normalized_names = set()
    members_by_name: dict[str, tarfile.TarInfo] = {}
    for member in tf.getmembers():
        name = member.name.rstrip("/")
        parts = PurePosixPath(name)
        if not name or parts.is_absolute() or ".." in parts.parts or parts.as_posix() != name:
            raise ValueError(f"Refusing unsafe archive member: {member.name!r}")
        if name in members_by_name:
            raise ValueError(f"Duplicate archive member: {name!r}")
        normalized = unicodedata.normalize("NFC", name)
        if normalized in normalized_names:
            raise ValueError(f"Archive members collide after Unicode normalization: {name!r}")
        normalized_names.add(normalized)
        members_by_name[name] = member
        roots.add(parts.parts[0])
    if len(roots) != 1:
        raise ValueError("Archive must contain a single top-level capsule directory")
    return roots.pop(), members_by_name


def payload_digest(capsule_dir_or_archive: Union[str, Path]) -> str:
    """SHA-256 of the ``.checksums`` bytes, as ``sha256:<hex>``.

    This is the digest of the *payload set*, not an identifier for the
    capsule. ``.checksums`` deliberately excludes ``capsule.yaml``, so two
    capsules with identical payloads but different manifests — different
    name, different ``sealed_by``, different backend claims — produce the
    same value. It was previously exported as ``content_id``, which
    overclaimed: naming a capsule by this is the layer-1-only identity that
    #14 was about.

    It is also, by construction, the same number the manifest already stores
    as ``checksums_digest``. Use ``compute_capsule_id`` for identity.

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
        if checksums_path.is_symlink() or not checksums_path.is_file():
            raise ValueError(".checksums must be a regular file, not a symlink")
        checksums_bytes = checksums_path.read_bytes()
    else:
        # Treat as archive — extract .checksums member without full extraction
        checksums_bytes = _extract_checksums_from_archive(path)

    digest = hashlib.sha256(checksums_bytes).hexdigest()
    return f"sha256:{digest}"


def _lifecycle_state(capsule_dir: Path) -> Optional[str]:
    """The ``lifecycle_state`` declared by ``capsule_dir/capsule.yaml``."""
    manifest_path = capsule_dir / "capsule.yaml"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError(f"{capsule_dir} is not sealed: it has no capsule.yaml")
    try:
        manifest = load_manifest_yaml(manifest_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ValueError(f"{manifest_path} could not be parsed: {exc.__class__.__name__}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"{manifest_path} must be a YAML mapping")
    state = manifest.get("lifecycle_state")
    return state if isinstance(state, str) else None


def _check_checksums_size(member: tarfile.TarInfo) -> None:
    if member.size > MAX_CHECKSUMS_BYTES:
        raise ValueError(
            f".checksums member is {member.size} bytes, which exceeds the "
            f"{MAX_CHECKSUMS_BYTES}-byte limit"
        )


def _add_directory_deterministic(
    tf: tarfile.TarFile,
    source_dir: Path,
    arcname_prefix: str,
) -> None:
    """Add all files in *source_dir* to *tf* with deterministic metadata.

    Members are ordered by the byte value of their in-archive path, and
    every field that could vary across hosts is normalised: timestamps
    zeroed, ids/owner names zeroed, and modes fixed (0o755 for directories,
    0o644 for files, 0o777 for symlinks).  Ordering is taken over the
    archive-name *string* rather than over ``Path`` objects, because
    ``Path`` comparison is case-folding on some flavours — which would order
    members differently on Windows than on POSIX and break the "OS
    Independent" byte-reproducibility guarantee.

    Symlinks are stored as symlink members (``SYMTYPE``); they are never
    dereferenced.  Following a payload symlink would embed the *target's*
    bytes — a file that may live outside the capsule — into the shipped
    archive, exactly the exfiltration the builder/verifier no-dereference
    policy exists to prevent.
    """
    # First add the directory entry itself
    tf.addfile(_norm_tarinfo(arcname_prefix, tarfile.DIRTYPE, mode=0o755))

    # Collect (arcname, entry) pairs and sort by the arcname string so the
    # ordering is a pure byte order, independent of the host's path flavour.
    entries = []
    for entry in source_dir.rglob("*"):
        rel = entry.relative_to(source_dir).as_posix()
        entries.append((f"{arcname_prefix}/{rel}", entry))
    entries.sort(key=lambda pair: pair[0])

    for arcname, entry in entries:
        # A symlink must be recognised *before* is_dir()/is_file(), both of
        # which follow the link.  Preserve it as a symlink member.
        if entry.is_symlink():
            info = _norm_tarinfo(arcname, tarfile.SYMTYPE, mode=0o777)
            info.linkname = os.readlink(entry)
            tf.addfile(info)
        elif entry.is_dir():
            tf.addfile(_norm_tarinfo(arcname, tarfile.DIRTYPE, mode=0o755))
        elif entry.is_file():
            data = entry.read_bytes()
            info = _norm_tarinfo(arcname, tarfile.REGTYPE, mode=0o644)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def _norm_tarinfo(name: str, typeflag: bytes, mode: int) -> tarfile.TarInfo:
    """A ``TarInfo`` with every host-varying field normalised to a constant."""
    info = tarfile.TarInfo(name=name)
    info.type = typeflag
    info.mtime = 0
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _extractall_filter_supported() -> bool:
    """Whether ``TarFile.extractall`` accepts the PEP 706 ``filter`` keyword.

    The ``filter=`` parameter and the module-level ``tarfile.data_filter``
    were introduced together in Python 3.12 and backported to the same set
    of patch releases (3.9.17+, 3.10.12+, 3.11.4+).  The presence of
    ``data_filter`` is therefore a reliable proxy for ``filter`` support and
    avoids a probe-by-exception.
    """
    return hasattr(tarfile, "data_filter")


def _safe_extractall(tf: tarfile.TarFile, output_dir: Path) -> None:
    """Extract every member of *tf* into *output_dir*, refusing anything that
    would escape it — a stand-in for ``filter="data"`` on interpreters that
    predate PEP 706.

    Guards, mirroring the data filter's intent:
      - reject absolute member names and any ``..`` path component;
      - reject any member whose destination resolves outside *output_dir*;
      - reject device/fifo members;
      - for symlinks/hardlinks, reject link targets that resolve outside
        *output_dir* (an outside target is the exfiltration vector the whole
        no-dereference policy exists to close).
    """
    base = output_dir.resolve()
    for member in tf.getmembers():
        name = member.name
        member_path = PurePosixPath(name)
        if os.path.isabs(name) or member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError(f"Refusing unsafe archive member: {name!r}")
        target = (base / name).resolve()
        if target != base and base not in target.parents:
            raise ValueError(f"Archive member escapes destination: {name!r}")
        if member.isdev():
            raise ValueError(f"Refusing device member: {name!r}")
        if member.issym() or member.islnk():
            # A symlink target is relative to the link's own directory; a
            # hardlink target is relative to the archive root.
            anchor = target.parent if member.issym() else base
            link_target = (anchor / member.linkname).resolve()
            if link_target != base and base not in link_target.parents:
                raise ValueError(
                    f"Archive link target escapes destination: {name!r} -> {member.linkname!r}"
                )
        # Members are vetted above; suppress the pre-3.14 "no filter" warning.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tf.extract(member, path=str(output_dir))


def _extract_checksums_from_archive(archive_path: Path) -> bytes:
    """Read the *root* ``.checksums`` member of a capsule archive without
    extracting anything to disk.

    Only ``<root>/.checksums`` counts. Members are stored in byte order, so a
    payload subdirectory sorting before ``.`` (``-data/``, ``#notes/`` …) that
    carries its own ``.checksums`` — legal payload, since only the root file
    is excluded from checksumming — used to be found first, and ``pack``
    reported the digest of the decoy (#94).

    Returns:
        The raw bytes of the .checksums file.

    Raises:
        FileNotFoundError: If the root has no ``.checksums`` member.
        ValueError: If the archive is malformed, has zero or several roots,
            or its ``.checksums`` member is not a regular file (#124).
    """
    with _open_archive(archive_path) as tf:
        root, members_by_name = _single_root_layout(tf)
        member = members_by_name.get(f"{root}/.checksums")
        if member is None:
            raise FileNotFoundError(f".checksums not found in archive: {archive_path}")
        if not member.isreg():
            raise ValueError(".checksums must be a regular file member of the archive")
        _check_checksums_size(member)
        f = tf.extractfile(member)
        if f is None:
            raise ValueError(".checksums must be a regular file member of the archive")
        try:
            return f.read()
        except EOFError as exc:
            raise ValueError(f"archive is truncated or corrupt: {archive_path}") from exc
