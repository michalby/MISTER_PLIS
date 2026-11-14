"""Where a job runs (mister_plis/runners.py, docs/PREP_PLAN.md R8): a job is described as JSON (JobSpec), and the
JobManager hears from a runner through its events — threads (LocalRunner) or a process of its own."""

import io
import json
import threading

from mister_plis import inputs as I
from mister_plis import outputs as O
from mister_plis.jobs import JobManager, JobSpec, UploadStore
from mister_plis.runners import LocalRunner
from mister_plis.toolkit import Tool

from test_jobstore import _manager, _run


def _gpu_tool():
    t = Tool(id="t-gpu", name="Render", inputs=[I.File("scene", "Scene", required=False), I.Number("n", "N", default=2)],
             needs=("gpu", "program:blender"))

    @t.runner
    def run(p, ctx):
        ctx.log("rendering")
        return [O.Metric("Frames", p.n)]

    return t


class FakeRunner:
    """A runner elsewhere: it only gets JSON, and answers through the events."""

    def __init__(self):
        self.specs, self.cancelled = [], []

    def start(self, spec, tool, events):
        self.specs.append(json.loads(json.dumps(spec.to_dict())))  # all a runner elsewhere would get
        self.events = events

    def cancel(self, job_id):
        self.cancelled.append(job_id)

    def shutdown(self, wait=False):
        pass


def test_jobs_run_through_the_local_runner(tmp_path):
    m = _manager(tmp_path)
    assert isinstance(m.runner, LocalRunner)
    job = _run(m, _gpu_tool(), {"n": 3})
    assert job.outputs[0]["value"] in (3, "3") and "rendering" in job.saved_logs[0]


def test_a_job_is_described_as_json_and_its_needs_are_recorded(tmp_path):
    fake = FakeRunner()
    m = JobManager(tmp_path, UploadStore(tmp_path / "uploads"), runner=fake)
    up = m.uploads.save("scene.blend", io.BytesIO(b"BLENDER"))
    job = m.submit(_gpu_tool(), {"scene": [up.id], "n": "4"}, prefs={"name": "Ola"})
    spec = JobSpec.from_dict(fake.specs[0])
    assert spec.job_id == job.id and spec.tool_id == "t-gpu" and spec.record and spec.workdir == f"jobs/{job.id}"
    assert spec.needs == ["gpu", "program:blender"] and spec.params == {"scene": [up.id], "n": "4"}
    entry = spec.inputs["scene"][0]
    assert entry["name"] == "scene.blend" and (job.workdir / entry["path"]).read_bytes() == b"BLENDER"  # in the job folder
    rec = json.loads((job.workdir / "job.json").read_text(encoding="utf-8"))
    assert rec["tool"]["needs"] == ["gpu", "program:blender"] and rec["status"] == "queued"

    # the runner reports back: the job list records it as it always did
    events = fake.events
    events.started(job.id)
    assert job.status == "running"
    events.context(job.id).log("half way")
    events.finished(job.id, [{"type": "metric", "label": "Frames", "value": 4}], "", "", "done")
    assert job.status == "done" and job.done.is_set() and job.outputs[0]["value"] == 4 and "half way" in job.saved_logs[0]
    again = json.loads((job.workdir / "job.json").read_text(encoding="utf-8"))
    assert again["status"] == "done"

    m.cancel(m.submit(_gpu_tool(), {}))
    assert fake.cancelled  # the runner is told; the job's own context is cancelled too


def test_a_live_run_names_its_uploads_in_the_data_folder(tmp_path):
    fake = FakeRunner()
    m = JobManager(tmp_path, UploadStore(tmp_path / "uploads"), runner=fake)
    up = m.uploads.save("a.csv", io.BytesIO(b"x,y\n"))
    t = Tool(id="t-live", name="Live", live=True, inputs=[I.File("data", "Data", required=False)])
    t.run_fn = lambda p, ctx: []
    m.submit(t, {"data": [up.id]})
    spec = fake.specs[0]
    assert not spec["record"] and spec["inputs"]["data"][0]["path"] == f"uploads/{up.id}/a.csv"


def test_a_tool_says_what_it_needs_in_words():
    import pytest

    assert Tool(id="x", name="X").needs == ()
    with pytest.raises(ValueError, match="needs"):
        Tool(id="x", name="X", needs=("",))


def test_a_tools_slots_still_hold_jobs_back(tmp_path):
    """max_concurrent: one at a time, the next waits (behaviour unchanged by the runner seam)."""
    gate, running = threading.Event(), []
    t = Tool(id="t-one", name="One", max_concurrent=1, background=True)

    @t.runner
    def run(p, ctx):
        running.append(1)
        gate.wait(10)
        return []

    m = _manager(tmp_path)
    a, b = m.submit(t, {}), m.submit(t, {})
    for _ in range(100):
        if running and b.ctx.message:
            break
        threading.Event().wait(0.05)
    assert len(running) == 1 and b.status == "queued" and "free slot" in b.ctx.message
    gate.set()
    m.wait(a, 10), m.wait(b, 10)
    assert a.status == b.status == "done"
