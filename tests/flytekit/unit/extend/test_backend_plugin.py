import typing

import grpc
from flyteidl.service import plugin_system_pb2

from flytekit.extend.backend.base_plugin import BackendPluginBase, BackendPluginRegistry
from flytekit.models.literals import LiteralMap
from flytekit.models.task import TaskTemplate


class DummyPlugin(BackendPluginBase):
    def __init__(self):
        super().__init__(task_type="dummy")

    def initialize(self):
        pass

    def create(
        self,
        context: grpc.ServicerContext,
        inputs: typing.Optional[LiteralMap],
        output_prefix: str,
        task_template: TaskTemplate,
    ) -> plugin_system_pb2.TaskCreateResponse:
        return plugin_system_pb2.TaskCreateResponse(job_id="dummy_id")

    def get(self, context: grpc.ServicerContext, job_id: str) -> plugin_system_pb2.TaskGetResponse:
        return plugin_system_pb2.TaskGetResponse(state=plugin_system_pb2.SUCCEEDED)

    def delete(self, context: grpc.ServicerContext, job_id) -> plugin_system_pb2.TaskDeleteResponse:
        return plugin_system_pb2.TaskDeleteResponse()


BackendPluginRegistry.register(DummyPlugin())


def test_base_plugin():
    p = BackendPluginBase(task_type="dummy")
    assert p.task_type == "dummy"
    p.create(None, "/tmp", None)
    p.get("id")
    p.delete("id")


def test_dummy_plugin():
    p = BackendPluginRegistry.get_plugin("dummy")
    assert p.create(None, "/tmp", None).job_id == "dummy_id"
    assert p.get("id").state == plugin_system_pb2.SUCCEEDED
    assert p.delete("id") == plugin_system_pb2.TaskDeleteResponse()