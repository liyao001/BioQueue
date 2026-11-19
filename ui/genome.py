"""Turn job output files into igv.js tracks.

igv.js loads data by URL and, for indexed formats, requests the index at a
sibling URL. BioQueue file URLs are ``?trace=`` tokens, so the index has to
be found on disk and handed to igv explicitly.
"""

from __future__ import annotations

import os

from .files import (
    decode_trace,
    encode_trace,
    format_bytes,
    list_job_files,
    listed_display_name,
    resolve_job_file,
)

# Plain text formats are downloaded whole. Indexed formats are read by range.
MAX_PLAIN_BYTES = 200 * 1024 * 1024

GENOMES = (
    ("hg38", "Human — hg38 / GRCh38"),
    ("hg19", "Human — hg19 / GRCh37"),
    ("mm39", "Mouse — mm39 / GRCm39"),
    ("mm10", "Mouse — mm10 / GRCm38"),
    ("rn6", "Rat — rn6"),
    ("dm6", "Drosophila — dm6"),
    ("ce11", "C. elegans — ce11"),
    ("danRer11", "Zebrafish — danRer11"),
    ("sacCer3", "Yeast — sacCer3"),
    ("galGal6", "Chicken — galGal6"),
)

_INDEX_SUFFIXES = (".bai", ".crai", ".tbi", ".csi", ".fai", ".gzi")

# Longest matching suffix wins. role is track, reference, or (via suffixes) index.
_SPECS = (
    {
        "role": "track",
        "format": "bam",
        "suffixes": (".bam",),
        "index": "bam",
        "cap": False,
        "missing": "No .bai index next to this BAM. Run samtools index and leave the .bai in the same folder.",
    },
    {
        "role": "track",
        "format": "cram",
        "suffixes": (".cram",),
        "index": "cram",
        "cap": False,
        "missing": "No .crai index next to this CRAM. Run samtools index and leave the .crai in the same folder.",
    },
    {
        "role": "track",
        "format": "vcf",
        "suffixes": (".vcf.gz", ".vcf.bgz"),
        "index": "tabix",
        "cap": False,
        "missing": "No .tbi index next to this gzipped VCF. Run tabix and leave the .tbi in the same folder.",
    },
    {
        "role": "track",
        "format": "vcf",
        "suffixes": (".vcf",),
        "index": "",
        "cap": True,
        "missing": "",
    },
    {
        "role": "track",
        "format": "bed",
        "suffixes": (".bed.gz", ".bedgraph.gz", ".bdg.gz", ".narrowpeak.gz", ".broadpeak.gz"),
        "index": "tabix",
        "cap": False,
        "missing": "No .tbi index next to this gzipped file. Run tabix and leave the .tbi in the same folder.",
    },
    {
        "role": "track",
        "format": "gff",
        "suffixes": (".gff3.gz", ".gff.gz", ".gtf.gz"),
        "index": "tabix",
        "cap": False,
        "missing": "No .tbi index next to this gzipped annotation. Run tabix and leave the .tbi in the same folder.",
    },
    {
        "role": "track",
        "format": "bigwig",
        "suffixes": (".bigwig", ".bw"),
        "index": "",
        "cap": False,
        "missing": "",
    },
    {
        "role": "track",
        "format": "bigbed",
        "suffixes": (".bigbed", ".bb"),
        "index": "",
        "cap": False,
        "missing": "",
    },
    {
        "role": "track",
        "format": "bedgraph",
        "suffixes": (".bedgraph", ".bdg"),
        "index": "",
        "cap": True,
        "missing": "",
    },
    {
        "role": "track",
        "format": "bed",
        "suffixes": (".narrowpeak", ".broadpeak", ".bed"),
        "index": "",
        "cap": True,
        "missing": "",
    },
    {
        "role": "track",
        "format": "gff",
        "suffixes": (".gff3", ".gtf", ".gff"),
        "index": "",
        "cap": True,
        "missing": "",
    },
    {
        "role": "track",
        "format": "wig",
        "suffixes": (".wig",),
        "index": "",
        "cap": True,
        "missing": "",
    },
    {
        "role": "reference",
        "format": "fasta",
        "suffixes": (".fasta.gz", ".fna.gz", ".fa.gz"),
        "index": "fasta-gz",
        "cap": False,
        "missing": "This gzipped FASTA needs both a .fai and a .gzi beside it. Run samtools faidx on the .gz file.",
    },
    {
        "role": "reference",
        "format": "fasta",
        "suffixes": (".fasta", ".fna", ".fa"),
        "index": "fai",
        "cap": False,
        "missing": "No .fai index next to this FASTA. Run samtools faidx and leave the .fai in the same folder.",
    },
)


def classify(name):
    """Return a format spec, an index marker, or None."""
    base = os.path.basename(str(name or "")).lower()
    if not base:
        return None
    for suffix in _INDEX_SUFFIXES:
        if base.endswith(suffix):
            return {"role": "index", "format": "", "suffix": suffix}
    best = None
    best_len = 0
    for spec in _SPECS:
        for suffix in spec["suffixes"]:
            if base.endswith(suffix) and len(suffix) > best_len:
                best = spec
                best_len = len(suffix)
    return best


def index_candidates(filename, kind):
    """Sibling index filenames for an on-disk basename."""
    name = os.path.basename(filename or "")
    lower = name.lower()
    if kind == "bam" and lower.endswith(".bam"):
        return [name + ".bai", name[:-4] + ".bai"]
    if kind == "cram" and lower.endswith(".cram"):
        return [name + ".crai", name[:-5] + ".crai"]
    if kind == "tabix":
        return [name + ".tbi", name + ".csi"]
    if kind in ("fai", "fasta-gz"):
        return [name + ".fai"]
    if kind == "gzi":
        return [name + ".gzi"]
    return []


def _index_trace(job, trace, names):
    relative = decode_trace(trace)
    if not relative:
        return None
    parent = os.path.dirname(relative)
    for name in names:
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            continue
        candidate = os.path.join(parent, name) if parent else name
        encoded = encode_trace(candidate)
        if resolve_job_file(job, encoded):
            return encoded
    return None


def describe_igv_file(job, trace):
    """Describe one readable job file for igv.js.

    Returns None when the file is missing. ``ok`` is false when the type is
    unsupported or a required index is not in the same folder. Index traces
    are included so the view can build URLs; they are not filesystem paths.
    """
    path = resolve_job_file(job, trace)
    if not path:
        return None
    name = listed_display_name(job, trace) or os.path.basename(path)
    spec = classify(name)
    if spec is None or spec["role"] == "index":
        return {
            "ok": False,
            "detail": "IGV cannot open this file. Supported tracks are BAM, CRAM, VCF, BED, GFF, bigWig, and bigBed. A FASTA with its index can be the reference.",
            "role": spec["role"] if spec else "",
            "format": "",
            "name": name,
            "index_trace": None,
            "gzi_trace": None,
        }
    # Pair the index with the job-folder name. resolve_job_file follows
    # symlinks, so the target's basename can differ from sample.bam.
    filename = os.path.basename(str(name).replace("\\", "/")) or os.path.basename(path)
    index_trace = None
    gzi_trace = None
    if spec["index"] == "fasta-gz":
        index_trace = _index_trace(job, trace, index_candidates(filename, "fai"))
        gzi_trace = _index_trace(job, trace, index_candidates(filename, "gzi"))
        if not index_trace or not gzi_trace:
            return _unavailable(spec, name)
    elif spec["index"]:
        index_trace = _index_trace(job, trace, index_candidates(filename, spec["index"]))
        if not index_trace:
            return _unavailable(spec, name)
    elif spec["cap"]:
        size = os.path.getsize(path)
        if size > MAX_PLAIN_BYTES:
            return {
                "ok": False,
                "detail": "This file is {} and has no index, so IGV would download all of it. Compress it (bgzip and tabix) or download it instead.".format(
                    format_bytes(size)
                ),
                "role": spec["role"],
                "format": spec["format"],
                "name": name,
                "index_trace": None,
                "gzi_trace": None,
            }
    return {
        "ok": True,
        "detail": "",
        "role": spec["role"],
        "format": spec["format"],
        "name": name,
        "index_trace": index_trace,
        "gzi_trace": gzi_trace,
    }


def _unavailable(spec, name):
    return {
        "ok": False,
        "detail": spec["missing"],
        "role": spec["role"],
        "format": spec["format"],
        "name": name,
        "index_trace": None,
        "gzi_trace": None,
    }


def genomic_files(job, q="", limit=200):
    """IGV-viewable files in a job, indexes excluded."""
    needle = (q or "").strip().lower()
    found = []
    items = list_job_files(job)
    items.sort(key=lambda item: (item.get("name") or "").lower())
    for item in items:
        spec = classify(item.get("name") or "")
        if spec is None or spec["role"] == "index":
            continue
        name = item.get("name") or ""
        if needle and needle not in name.lower():
            continue
        found.append(
            {
                "name": name,
                "trace": item.get("trace") or "",
                "size_label": item.get("size_label") or "",
                "role": spec["role"],
                "format": spec["format"],
            }
        )
        if len(found) >= limit:
            break
    return found, len(found) >= limit
