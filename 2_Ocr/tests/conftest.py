"""
Pre-mock heavy ML dependencies so tests run without installing torch/docling.
Also mocks config to prevent sys.exit(1) when env vars are missing.
These are replaced before document_processor is imported.
"""
import sys
from unittest.mock import MagicMock

# Mock torch at sys.modules level so `import torch` in document_processor resolves to a Mock
torch_mock = MagicMock()
sys.modules['torch'] = torch_mock
sys.modules['torch.cuda'] = torch_mock.cuda

# Mock docling and all submodules it imports
for mod in [
    'docling',
    'docling.document_converter',
    'docling.datamodel',
    'docling.datamodel.base_models',
    'docling.datamodel.pipeline_options',
    'docling.backend',
    'docling.backend.pypdfium2_backend',
]:
    sys.modules[mod] = MagicMock()

# Mock config to prevent sys.exit(1) on import when env vars are missing
config_mock = MagicMock()
config_mock.Config = MagicMock()
sys.modules['config'] = config_mock
