import json

from django.urls import reverse

from ui3.tests import Ui3TestCase


class DagExplorerTests(Ui3TestCase):
    def test_login_required(self):
        response = self.client.get(reverse("ui3:dag"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/ui3/login/", response["Location"])

    def test_page_is_js_island(self):
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertContains(response, reverse("ui3:dag"))
        self.assertNotContains(response, "is-soon")
        page = self.client.get(reverse("ui3:dag"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'id="dag-cy"')
        self.assertContains(page, "Build DAG")
        self.assertContains(page, "ui3/dag.js")
        self.assertContains(page, "cytoscape")
        self.assertNotContains(page, "not in this HTMX slice yet")

    def test_card_links_to_dag(self):
        job = self.make_job()
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertContains(response, reverse("ui3:dag") + "?seeds={}".format(job.id))

    def test_graph_requires_root(self):
        self.login()
        response = self.client.get(reverse("ui3:dag_graph"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["detail"], "root is required and must be an integer")

    def test_graph_hides_other_users_job(self):
        other = self.make_job(user=self.other, job_name="secret-dag")
        self.login()
        response = self.client.get(reverse("ui3:dag_graph"), {"root": other.id})
        self.assertEqual(response.status_code, 404)

    def test_graph_walks_history_up_and_down(self):
        parent = self.make_job(job_name="dag-parent")
        child = self.make_job(
            job_name="dag-child",
            parameter="{{{{History:{}-out.txt}}}}".format(parent.id),
        )
        self.login()
        up = self.client.get(reverse("ui3:dag_graph"), {"root": child.id, "up": 1, "down": 0})
        self.assertEqual(up.status_code, 200)
        up_data = json.loads(up.content)
        self.assertEqual(up_data["root"], child.id)
        self.assertEqual({n["id"] for n in up_data["nodes"]}, {parent.id, child.id})
        self.assertIn({"from": parent.id, "to": child.id}, up_data["edges"])

        down = self.client.get(reverse("ui3:dag_graph"), {"root": parent.id, "up": 0, "down": 1})
        self.assertEqual(down.status_code, 200)
        down_data = json.loads(down.content)
        self.assertEqual({n["id"] for n in down_data["nodes"]}, {parent.id, child.id})
        self.assertIn({"from": parent.id, "to": child.id}, down_data["edges"])

    def test_search_and_seed_lookup(self):
        mine = self.make_job(job_name="seed-alpha")
        self.make_job(user=self.other, job_name="seed-beta", protocol=self.other_protocol)
        self.login()
        search = self.client.get(reverse("ui3:dag_search"), {"q": "seed-alpha"})
        self.assertEqual(search.status_code, 200)
        names = [row["job_name"] for row in json.loads(search.content)["results"]]
        self.assertIn("seed-alpha", names)
        self.assertNotIn("seed-beta", names)

        seeds = self.client.get(reverse("ui3:dag_jobs"), {"ids": "{},999999".format(mine.id)})
        self.assertEqual(seeds.status_code, 200)
        ids = [row["id"] for row in json.loads(seeds.content)["results"]]
        self.assertEqual(ids, [mine.id])
