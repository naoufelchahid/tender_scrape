"""
Tests for GPU assertion logic in document_processor.py.
All tests mock torch.cuda to avoid requiring real GPU hardware in CI.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestAssertGpuAvailable:
    """Tests for _assert_gpu_available() fail-fast behavior."""

    def test_raises_if_no_cuda(self):
        """Should raise RuntimeError when torch.cuda.is_available() returns False."""
        with patch("document_processor.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = False

            from document_processor import _assert_gpu_available
            with pytest.raises(RuntimeError, match="No CUDA GPU detected"):
                _assert_gpu_available()

    def test_passes_if_cuda_available(self):
        """Should return without error when GPU is detected."""
        with patch("document_processor.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            mock_torch.cuda.get_device_name.return_value = "Tesla T4"
            mock_props = MagicMock()
            mock_props.total_memory = 16 * 1024**3  # 16 GB
            mock_torch.cuda.get_device_properties.return_value = mock_props
            mock_torch.version.cuda = "12.1"

            from document_processor import _assert_gpu_available
            _assert_gpu_available()  # must not raise

    def test_logs_device_info_on_success(self, caplog):
        """Should log GPU name and VRAM when GPU is detected."""
        import logging
        with patch("document_processor.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            mock_torch.cuda.get_device_name.return_value = "Tesla T4"
            mock_props = MagicMock()
            mock_props.total_memory = 16 * 1024**3
            mock_torch.cuda.get_device_properties.return_value = mock_props
            mock_torch.version.cuda = "12.1"

            with caplog.at_level(logging.INFO, logger="ocr-service"):
                from document_processor import _assert_gpu_available
                _assert_gpu_available()

            assert "Tesla T4" in caplog.text
