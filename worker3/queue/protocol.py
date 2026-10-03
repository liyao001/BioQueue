"""Protocol template: DB steps bound to settings and user-local binaries."""
import os

from QueueDB.models import Step
from worker3.step import _Step

class Protocol(object):
    def __init__(self, poj, settings):
        super(Protocol, self).__init__()
        # super(Protocol, self).__init__(poj, settings)
        self._ver = poj.ver
        self.raw_steps = Step.objects.filter(parent=poj).order_by("step_order")
        self._steps = []
        self._settings = settings

    @property
    def ver(self):
        return self._ver

    def customize_steps_by_user_dir(self, workspace_path, user_id):
        return [self._to_step(step, workspace_path, user_id) for step in self.raw_steps]

    def materialize_expanded(self, expanded, workspace_path, user_id):
        return [self._to_step(step, workspace_path, user_id) for step in expanded]

    def _to_step(self, step, workspace_path, user_id):
        sp = step.software

        if str(sp).strip() != _Step.SHELL_TAG and workspace_path is not None and os.path.exists(workspace_path):
            if user_id is not None:
                software_path = os.path.join(os.path.join(os.path.join(workspace_path, str(user_id)), "bin"),
                                             str(step.software))
                if os.path.exists(software_path) and os.path.isfile(software_path):
                    sp = software_path

        return _Step(software=sp.rstrip(),
                     parameter=str(step.parameter),
                     specify_output=step.specify_output,
                     md5_hex=step.hash,
                     env=step.env,
                     version_check=step.version_check,
                     force_local=step.force_local,
                     settings=self._settings,
                     gpu_step=bool(getattr(step, "gpu_step", 0)))
