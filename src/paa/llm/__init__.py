"""模型适配层：只负责把消息变成回复，不拼提示词、不存记忆。"""

from .client import Completion, ModelClient, ModelError
from .router import BrainRouter, RoutedCompletion

__all__ = ["BrainRouter", "Completion", "ModelClient", "ModelError", "RoutedCompletion"]
