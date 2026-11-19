import os
import tempfile
from pathlib import Path
from urllib.parse import quote

from django.urls import reverse

from QueueDB.models import CrossAccess
from ui.files import encode_trace, list_job_files
from ui.genome import GENOMES, classify, describe_igv_file, index_candidates
from ui.tests import Ui3TestCase


def _body(response):
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


class IgvClassifyTests(Ui3TestCase):
    def test_suffixes_pick_tracks_indexes_and_references(self):
        self.assertEqual(classify("align/sample.bam")["format"], "bam")
        self.assertEqual(classify("sample.BAM")["role"], "track")
        self.assertEqual(classify("sample.cram")["format"], "cram")
        self.assertEqual(classify("vars.vcf.gz")["format"], "vcf")
        self.assertEqual(classify("vars.vcf.gz")["index"], "tabix")
        self.assertEqual(classify("ann.bed")["format"], "bed")
        self.assertEqual(classify("ann.bedgraph")["format"], "bedgraph")
        self.assertEqual(classify("cov.bw")["format"], "bigwig")
        self.assertEqual(classify("ref.fasta")["role"], "reference")
        self.assertEqual(classify("ref.fa.gz")["index"], "fasta-gz")
        self.assertEqual(classify("sample.bam.bai")["role"], "index")
        self.assertEqual(classify("vars.vcf.gz.tbi")["role"], "index")
        self.assertEqual(classify("ref.fa.fai")["role"], "index")
        self.assertIsNone(classify("hello.txt"))
        self.assertEqual(
            index_candidates("Sample.bam", "bam"),
            ["Sample.bam.bai", "Sample.bai"],
        )
        self.assertEqual(
            index_candidates("Sample.cram", "cram"),
            ["Sample.cram.crai", "Sample.crai"],
        )


class IgvBrowserTests(Ui3TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def _job(self, files, user=None, **kwargs):
        owner = user or self.user
        job = self.make_job(user=owner, result="out", run_dir=self.tmp, **kwargs)
        folder = os.path.join(self.tmp, str(owner.id), "out")
        for name, data in files.items():
            path = os.path.join(folder, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            mode = "wb" if isinstance(data, bytes) else "w"
            with open(path, mode) as fh:
                fh.write(data)
        return job

    def _trace(self, job, name):
        found = {item["name"]: item["trace"] for item in list_job_files(job)}
        self.assertIn(name, found)
        return found[name]

    def test_page_lists_genomes_and_readable_jobs(self):
        self._job({"region.bed": "chr1\t1\t10\n"}, job_name="liver-igv")
        secret = self.make_job(user=self.other, job_name="hidden-from-alice")
        self.login()
        page = self.client.get(reverse("ui3:igv"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Genome browser")
        self.assertContains(page, '<summary class="is-active">')
        self.assertContains(page, "<i class=\"fas fa-ellipsis\"></i> More")
        self.assertContains(page, "Export this session")
        self.assertContains(page, 'id="igv-save"')
        self.assertContains(page, 'id="igv-window"')
        self.assertContains(page, 'id="igv-session-file"')
        self.assertContains(page, "igv@3.8.10/dist/igv.min.js")
        script = (Path(__file__).resolve().parents[1] / "static" / "ui3" / "igv.js").read_text()
        body = script.split("function dropBrowser", 1)[1].split("function browserError", 1)[0]
        self.assertLess(body.find("igv.removeBrowser"), body.find("igv.createBrowser"))
        self.assertLess(body.find("dropBrowser(browser)"), body.find("igv.createBrowser"))
        self.assertIn("dropBrowser(created)", body)
        self.assertContains(page, "hg38")
        self.assertContains(page, "liver-igv")
        self.assertNotContains(page, "hidden-from-alice")
        parent = self.make_job(job_name="array-parent")
        self.make_job(job_name="array-child", parent_job=parent)
        listed = self.client.get(reverse("ui3:igv_jobs"), {"q": "array-"})
        self.assertContains(listed, "array-parent")
        self.assertNotContains(listed, "array-child")
        for index in range(16):
            self.make_job(job_name="page-job-{:02d}".format(index))
        first = self.client.get(reverse("ui3:igv_jobs"), {"q": "page-job"})
        self.assertContains(first, "page-job-15")
        self.assertNotContains(first, "page-job-00")
        self.assertContains(first, 'aria-label="Next page"')
        second = self.client.get(reverse("ui3:igv_jobs"), {"q": "page-job", "page": "2"})
        self.assertContains(second, "page-job-00")
        self.assertNotContains(second, "page-job-15")
        self.assertContains(second, "2 / 2")
        self.assertContains(page, reverse("ui3:igv_track"))
        self.assertContains(
            page,
            'data-genomes="{}"'.format(",".join(gid for gid, _label in GENOMES)),
        )
        self.client.logout()
        anon = self.client.get(reverse("ui3:igv"))
        self.assertEqual(anon.status_code, 302)
        self.assertIn("/ui/login/", anon["Location"])
        self.assertTrue(secret.pk)

    def test_track_pairs_bam_with_bai_and_serves_ranges(self):
        job = self._job({
            "align/sample.bam": b"abcdefghij",
            "align/sample.bai": b"IDX",
            "region.bed": "chr1\t1\t2\n",
            "ref.fa": ">chr1\nAC\n",
            "ref.fa.fai": "chr1\t2\t6\t2\t3\n",
            "notes.txt": "hello",
        })
        bam = self._trace(job, "align/sample.bam")
        self.login()
        described = self.client.get(reverse("ui3:igv_track"), {"job": job.id, "trace": bam})
        self.assertEqual(described.status_code, 200)
        payload = described.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["format"], "bam")
        self.assertEqual(payload["name"], "align/sample.bam")
        self.assertIn(reverse("ui3:job_file_bytes", args=[job.id]), payload["url"])
        self.assertTrue(payload["indexURL"])
        index = self.client.get(payload["indexURL"])
        self.assertEqual(index.status_code, 200)
        self.assertEqual(_body(index), b"IDX")
        self.assertNotIn("Content-Encoding", index)
        ranged = self.client.get(payload["url"], HTTP_RANGE="bytes=2-5")
        self.assertEqual(ranged.status_code, 206)
        self.assertEqual(_body(ranged), b"cdef")
        self.assertEqual(ranged["Content-Range"], "bytes 2-5/10")
        self.assertEqual(ranged["Accept-Ranges"], "bytes")
        self.assertEqual(ranged["Content-Type"], "application/octet-stream")
        suffix = self.client.get(payload["url"], HTTP_RANGE="bytes=-3")
        self.assertEqual(suffix.status_code, 206)
        self.assertEqual(_body(suffix), b"hij")
        whole = self.client.head(payload["url"])
        self.assertEqual(whole.status_code, 200)
        self.assertEqual(whole["Content-Length"], "10")
        self.assertEqual(b"", whole.content)
        missing = self.client.get(payload["url"], HTTP_RANGE="bytes=50-60")
        self.assertEqual(missing.status_code, 416)
        bed = self.client.get(
            reverse("ui3:igv_track"),
            {"job": job.id, "trace": self._trace(job, "region.bed")},
        )
        self.assertTrue(bed.json()["ok"])
        self.assertIsNone(bed.json()["indexURL"])
        fasta = self.client.get(
            reverse("ui3:igv_track"),
            {"job": job.id, "trace": self._trace(job, "ref.fa")},
        )
        self.assertEqual(fasta.json()["role"], "reference")
        self.assertTrue(fasta.json()["indexURL"])
        text = self.client.get(
            reverse("ui3:igv_track"),
            {"job": job.id, "trace": self._trace(job, "notes.txt")},
        )
        self.assertFalse(text.json()["ok"])

    def test_symlink_index_uses_the_link_name(self):
        job = self._job({
            "align/lib1.bam": b"LIB1DATA!!",
            "align/sample.bam.bai": b"LINKIDX",
        })
        folder = os.path.join(self.tmp, str(self.user.id), "out", "align")
        os.symlink("lib1.bam", os.path.join(folder, "sample.bam"))
        info = describe_igv_file(job, self._trace(job, "align/sample.bam"))
        self.assertTrue(info["ok"])
        self.assertEqual(info["name"], "align/sample.bam")
        self.login()
        described = self.client.get(reverse("ui3:igv_track"), {
            "job": job.id,
            "trace": self._trace(job, "align/sample.bam"),
        })
        self.assertTrue(described.json()["ok"])
        index = self.client.get(described.json()["indexURL"])
        self.assertEqual(_body(index), b"LINKIDX")

    def test_missing_index_and_other_users_are_refused(self):
        job = self._job({"alone.bam": b"BAM", "vars.vcf.gz": b"\x1f\x8bvcf"})
        self.login()
        bam = self.client.get(
            reverse("ui3:igv_track"),
            {"job": job.id, "trace": self._trace(job, "alone.bam")},
        )
        self.assertFalse(bam.json()["ok"])
        self.assertIn(".bai", bam.json()["detail"])
        gz = self.client.get(reverse("ui3:job_file_bytes", args=[job.id]), {
            "trace": self._trace(job, "vars.vcf.gz"),
        })
        self.assertEqual(gz.status_code, 200)
        self.assertNotIn("Content-Encoding", gz)
        self.assertEqual(gz["Content-Type"], "application/octet-stream")
        escaped = self.client.get(reverse("ui3:job_file_bytes", args=[job.id]), {
            "trace": encode_trace("../secret"),
        })
        self.assertEqual(escaped.status_code, 404)
        self.login("bob")
        denied = self.client.get(
            reverse("ui3:igv_track"),
            {"job": job.id, "trace": self._trace(job, "alone.bam")},
        )
        self.assertEqual(denied.status_code, 404)
        raw = self.client.get(reverse("ui3:job_file_bytes", args=[job.id]), {
            "trace": self._trace(job, "alone.bam"),
        })
        self.assertEqual(raw.status_code, 403)

    def test_shared_job_and_plain_file_cap(self):
        job = self._job(
            {"shared.bed": "chr1\t1\t2\n", "big.vcf": "x" * 20},
            user=self.other,
            job_name="shared-call",
        )
        CrossAccess.objects.create(user=self.other, grantee=self.user, allow_read=1)
        self.login()
        jobs = self.client.get(reverse("ui3:igv_jobs"), {"q": "shared-call"})
        self.assertContains(jobs, "shared-call")
        self.assertContains(jobs, "(shared)")
        files = self.client.get(reverse("ui3:igv_files"), {"job": job.id})
        self.assertContains(files, "shared.bed")
        self.assertContains(files, "big.vcf")
        from unittest.mock import patch

        with patch("ui.genome.MAX_PLAIN_BYTES", 8):
            info = describe_igv_file(job, self._trace(job, "big.vcf"))
        self.assertFalse(info["ok"])
        self.assertIn("no index", info["detail"])
        bed = describe_igv_file(job, self._trace(job, "shared.bed"))
        self.assertTrue(bed["ok"])

    def test_file_browser_links_genome_files(self):
        job = self._job({
            "region.bed": "chr1\t1\t10\n",
            "hello.txt": "abc",
            "sample.bam": b"BAM",
            "sample.bam.bai": b"BAI",
        })
        self.login()
        page = self.client.get(reverse("ui3:job_files", args=[job.id]))
        bed = self._trace(job, "region.bed")
        text = self._trace(job, "hello.txt")
        index = self._trace(job, "sample.bam.bai")
        self.assertContains(page, "?add={}:{}".format(job.id, quote(bed)))
        self.assertContains(page, "Open in IGV")
        self.assertContains(page, "job-files-igv-selected")
        self.assertNotContains(page, "?add={}:{}".format(job.id, quote(text)))
        self.assertNotContains(page, "?add={}:{}".format(job.id, quote(index)))
        self.assertContains(page, 'data-igv-role="track"')
        self.assertContains(page, 'data-igv-role=""')
